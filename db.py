import json
import sqlite3
import threading
import os
import fcntl
from pathlib import Path

from novel_utils import normalize_audience_type


class DatabaseManager:
    def __init__(self, db_name=None):
        if db_name is None:
            db_name = Path(__file__).resolve().parent / "novel_memory.db"
        self.db_path = str(db_name)
        self.lock_path = self.db_path + ".lock"
        self.lock = threading.RLock()
        self._local = threading.local()

        # 工业级：基于文件锁的原子化初始化，解决高并发下的 "Database is locked" 竞争
        self._safe_init_db()

    @property
    def conn(self):
        """线程本地连接，避免多线程共享同一个 sqlite 连接。"""
        if not hasattr(self._local, "conn"):
            self._local.conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
            self._configure_db(self._local.conn)
        return self._local.conn

    @property
    def cursor(self):
        """线程本地游标，解决多线程并发下的 Recursive use of cursors 错误"""
        if not hasattr(self._local, "cursor"):
            self._local.cursor = self.conn.cursor()
        return self._local.cursor

    def _configure_db(self, connection):
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("PRAGMA busy_timeout=30000")
        connection.commit()

    def _json_dumps(self, value):
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False)

    def _json_loads(self, value, default=None):
        if value in (None, ""):
            return default
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return default

    def _merge_text(self, existing, new_text):
        return f"{existing} | {new_text}".strip(" |") if existing else new_text

    def _fetchall_as_dicts(self):
        columns = [desc[0] for desc in self.cursor.description]
        return [dict(zip(columns, row)) for row in self.cursor.fetchall()]

    def _ensure_table_columns(self, table_name, column_defs):
        self.cursor.execute(f"PRAGMA table_info({table_name})")
        existing_columns = {row[1] for row in self.cursor.fetchall()}
        for column_name, column_sql in column_defs.items():
            if column_name not in existing_columns:
                self.cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}")

    def _safe_init_db(self):
        """带文件锁的初始化，确保多进程/多线程并发时只有一个在执行 schema 变更"""
        with open(self.lock_path, "w") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX)
                self.init_db()
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def init_db(self):
        # 兼容旧版基础数据表
        self.cursor.execute(
            """CREATE TABLE IF NOT EXISTS gold_library (
            id INTEGER PRIMARY KEY,
            content TEXT
        )"""
        )
        self.cursor.execute(
            """CREATE TABLE IF NOT EXISTS sandbox_library (
            id INTEGER PRIMARY KEY,
            content TEXT,
            score INTEGER
        )"""
        )
        self.cursor.execute(
            """CREATE TABLE IF NOT EXISTS foreshadowing (
            id INTEGER PRIMARY KEY,
            item TEXT,
            resolved BOOLEAN
        )"""
        )
        self.cursor.execute(
            """CREATE TABLE IF NOT EXISTS learned_files (
            id INTEGER PRIMARY KEY,
            file_path TEXT UNIQUE
        )"""
        )
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS reference_fingerprint_bundles (
                book_id TEXT PRIMARY KEY,
                source_paths_json TEXT,
                payload_json TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # 动态规则表
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS rules_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT,
                rule_text TEXT,
                trigger_count INTEGER DEFAULT 0,
                success_score REAL DEFAULT 1.0,
                bayesian_weight REAL DEFAULT 1.0,
                is_active BOOLEAN DEFAULT 1
            )
            """
        )
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS causal_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parent_id INTEGER,
                child_id INTEGER,
                link_type TEXT,
                description TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # 新版生产资产表
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS books (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                audience_type TEXT,
                narrative_kernel TEXT,
                master_style TEXT,
                world_setting TEXT,
                initial_conflict TEXT,
                genesis_json TEXT,
                skeleton_json TEXT,
                status TEXT DEFAULT 'created',
                latest_chapter_index INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS chapters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id TEXT NOT NULL,
                chapter_index INTEGER NOT NULL,
                title TEXT NOT NULL,
                chapter_type TEXT,
                skeleton_json TEXT,
                history_context TEXT,
                summary TEXT,
                status TEXT DEFAULT 'planned',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(book_id, chapter_index)
            )
            """
        )
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS chapter_drafts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id TEXT NOT NULL,
                chapter_id INTEGER,
                chapter_index INTEGER NOT NULL,
                draft_stage TEXT NOT NULL,
                candidate_label TEXT,
                content TEXT NOT NULL,
                seed_prompt TEXT,
                model_name TEXT,
                evaluation_json TEXT,
                is_selected BOOLEAN DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS chapter_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id TEXT NOT NULL,
                chapter_id INTEGER,
                chapter_index INTEGER NOT NULL,
                draft_id INTEGER,
                reviewer_name TEXT NOT NULL,
                passed BOOLEAN,
                raw_feedback TEXT,
                score_json TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS chapter_finals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id TEXT NOT NULL,
                chapter_id INTEGER,
                chapter_index INTEGER NOT NULL,
                source_draft_id INTEGER,
                editor_type TEXT DEFAULT 'machine',
                content TEXT NOT NULL,
                summary TEXT,
                source_path TEXT,
                final_metadata_json TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS chapter_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id TEXT NOT NULL,
                chapter_id INTEGER,
                chapter_index INTEGER NOT NULL,
                final_id INTEGER,
                metric_name TEXT NOT NULL,
                score REAL NOT NULL,
                details TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS learning_pairs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id TEXT NOT NULL,
                chapter_id INTEGER,
                chapter_index INTEGER NOT NULL,
                source_draft_id INTEGER,
                source_final_id INTEGER,
                draft_text TEXT NOT NULL,
                final_text TEXT NOT NULL,
                pair_source TEXT DEFAULT 'human_edit',
                source_path TEXT,
                final_source_path TEXT,
                status TEXT DEFAULT 'pending',
                learned_rule_json TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                processed_at DATETIME
            )
            """
        )
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS character_states (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id TEXT NOT NULL,
                character_name TEXT NOT NULL,
                state_json TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(book_id, character_name)
            )
            """
        )
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS foreshadow_registry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id TEXT NOT NULL,
                description TEXT NOT NULL,
                priority TEXT DEFAULT 'B',
                target_chapter INTEGER,
                resolved BOOLEAN DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                resolved_at DATETIME
            )
            """
        )
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS rule_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_id INTEGER,
                category TEXT NOT NULL,
                book_id TEXT,
                chapter_index INTEGER,
                metric_name TEXT,
                delta REAL,
                reason TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS expert_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                audience TEXT DEFAULT 'all',
                original_text TEXT NOT NULL,
                improved_text TEXT NOT NULL,
                score REAL DEFAULT 0,
                source TEXT DEFAULT 'human',
                is_active BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS generation_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id TEXT UNIQUE,
                title_seed TEXT NOT NULL,
                total_chapters INTEGER DEFAULT 10,
                candidate_count INTEGER DEFAULT 1,
                priority INTEGER DEFAULT 100,
                status TEXT DEFAULT 'pending',
                rate_limit_group TEXT DEFAULT 'default',
                max_attempts INTEGER DEFAULT 3,
                error_text TEXT,
                attempts INTEGER DEFAULT 0,
                scheduled_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                next_run_after DATETIME DEFAULT CURRENT_TIMESTAMP,
                started_at DATETIME,
                finished_at DATETIME,
                lease_expires_at DATETIME,
                worker_id TEXT,
                last_heartbeat_at DATETIME,
                rollback_state_json TEXT
            )
            """
        )

        self._ensure_table_columns("books", {"skeleton_json": "skeleton_json TEXT"})
        self._ensure_table_columns("chapter_drafts", {"candidate_label": "candidate_label TEXT"})
        self._ensure_table_columns("chapter_finals", {"source_path": "source_path TEXT"})
        self._ensure_table_columns(
            "expert_samples",
            {
                "audience": "audience TEXT DEFAULT 'all'",
                "score": "score REAL DEFAULT 0",
                "source": "source TEXT DEFAULT 'human'",
                "is_active": "is_active BOOLEAN DEFAULT 1",
                "created_at": "created_at DATETIME DEFAULT CURRENT_TIMESTAMP",
            },
        )
        self._ensure_table_columns(
            "learning_pairs",
            {
                "source_path": "source_path TEXT",
                "final_source_path": "final_source_path TEXT",
                "rule_status": "rule_status TEXT DEFAULT 'pending'",
                "skill_status": "skill_status TEXT DEFAULT 'pending'",
                "rule_payload_json": "rule_payload_json TEXT",
                "skill_payload_json": "skill_payload_json TEXT",
            },
        )
        self._ensure_table_columns(
            "generation_tasks",
            {
                "candidate_count": "candidate_count INTEGER DEFAULT 1",
                "rate_limit_group": "rate_limit_group TEXT DEFAULT 'default'",
                "max_attempts": "max_attempts INTEGER DEFAULT 3",
                "next_run_after": "next_run_after DATETIME DEFAULT CURRENT_TIMESTAMP",
                "lease_expires_at": "lease_expires_at DATETIME",
                "worker_id": "worker_id TEXT",
                "last_heartbeat_at": "last_heartbeat_at DATETIME",
                "rollback_state_json": "rollback_state_json TEXT",
            },
        )

        self.cursor.execute(
            """
            UPDATE learning_pairs
            SET rule_status = COALESCE(rule_status, CASE WHEN status = 'processed' THEN 'processed' ELSE 'pending' END),
                skill_status = COALESCE(skill_status, CASE WHEN status = 'processed' THEN 'processed' ELSE 'pending' END)
            """
        )
        self.cursor.execute(
            """
            UPDATE learning_pairs
            SET status = CASE
                WHEN COALESCE(rule_status, 'pending') = 'processed'
                 AND COALESCE(skill_status, 'pending') = 'processed' THEN 'processed'
                WHEN COALESCE(rule_status, 'pending') = 'pending'
                 AND COALESCE(skill_status, 'pending') = 'pending' THEN 'pending'
                ELSE 'partial'
            END
            """
        )
        self.cursor.execute(
            """
            UPDATE learning_pairs
            SET processed_at = COALESCE(processed_at, created_at)
            WHERE status = 'processed' AND processed_at IS NULL
            """
        )

        # 为了支持几万到几亿级别的数据并发，必须创建索引
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_books_status ON books(status)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_chapters_book_id ON chapters(book_id)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_chapter_drafts_book_idx ON chapter_drafts(book_id, chapter_index)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_chapter_finals_book_idx ON chapter_finals(book_id, chapter_index)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_generation_tasks_status ON generation_tasks(status)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_rules_ledger_category ON rules_ledger(category)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_learning_pairs_status ON learning_pairs(status)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_learning_pairs_rule_status ON learning_pairs(rule_status)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_learning_pairs_skill_status ON learning_pairs(skill_status)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_character_states_book_char ON character_states(book_id, character_name)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_foreshadow_registry_book_resolved ON foreshadow_registry(book_id, resolved, target_chapter)")

        self.conn.commit()

        # 费用与用量追踪表 (Usage Tracking)
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS usage_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id TEXT,
                chapter_index INTEGER,
                model TEXT,
                prompt_tokens INTEGER,
                completion_tokens INTEGER,
                total_tokens INTEGER,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.conn.commit()

        self._init_default_rules()

    def log_usage(self, book_id, chapter_index, model, prompt_tokens, completion_tokens, total_tokens):
        """记录 LLM 调用用量"""
        with self.lock:
            self.cursor.execute(
                """
                INSERT INTO usage_logs (book_id, chapter_index, model, prompt_tokens, completion_tokens, total_tokens)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (book_id, chapter_index, model, prompt_tokens, completion_tokens, total_tokens)
            )
            self.conn.commit()

    def _init_default_rules(self):
        defaults = [
            ("no_ai_flavor", "拒绝解释性尾注（不写“——那是XXX”）；拒绝回声头排比；长短句极端错落。"),
            ("demographic_quarantine_male", "男频主攻杀伐果断/逻辑闭环/宏大叙事。"),
            ("demographic_quarantine_female", "女频主攻情感拉扯/修罗场/微表情侧写。"),
            ("strict_disguise_logic", "多重马甲身份，绝不可暴露生理特征。"),
            ("zero_cliche", "每段情节反向变异老旧桥段设计。"),
            ("setting_absolute_compliance", "古代严禁现代思维或跨界道具。"),
            ("opening_hook", "楔子前100字必须直接爆发冲突或悬念，严禁慢热铺陈。"),
            ("continuity_payoff", "伏笔必须按章回收，重要伏笔不得拖到结构失衡。"),
        ]

        inserted = 0
        for category, rule_text in defaults:
            self.cursor.execute("SELECT 1 FROM rules_ledger WHERE category = ? LIMIT 1", (category,))
            if not self.cursor.fetchone():
                self.add_dynamic_rule(category, rule_text, initial_weight=1.0)
                inserted += 1
        if inserted:
            print(f"🚀 [数据库初始化] 已补齐 {inserted} 条系统根规则。")

    # ====== 技能样本管理 (Skill Sample Management) ======
    def add_expert_sample(self, category, audience, original_text, improved_text, score, source="human"):
        self.cursor.execute(
            """
            INSERT INTO expert_samples (category, audience, original_text, improved_text, score, source)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (category, audience, original_text, improved_text, score, source)
        )
        self.conn.commit()

    def get_expert_samples(self, category, audience=None, limit=3):
        """获取指定类别的高分样本，用于 Few-Shot 注入"""
        if audience:
            query = "SELECT original_text, improved_text FROM expert_samples WHERE category = ? AND (audience = ? OR audience = 'all') AND is_active = 1 ORDER BY score DESC LIMIT ?"
            self.cursor.execute(query, (category, audience, limit))
        else:
            query = "SELECT original_text, improved_text FROM expert_samples WHERE category = ? AND is_active = 1 ORDER BY score DESC LIMIT ?"
            self.cursor.execute(query, (category, limit))
        
        return [{"original": r[0], "improved": r[1]} for r in self.cursor.fetchall()]

    def save_reference_fingerprint_bundle(self, book_id, source_paths, payload):
        self.cursor.execute(
            """
            INSERT INTO reference_fingerprint_bundles (book_id, source_paths_json, payload_json)
            VALUES (?, ?, ?)
            ON CONFLICT(book_id) DO UPDATE SET
                source_paths_json = excluded.source_paths_json,
                payload_json = excluded.payload_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (book_id, self._json_dumps(source_paths or []), self._json_dumps(payload or {})),
        )
        self.conn.commit()

    def get_reference_fingerprint_bundle(self, book_id):
        self.cursor.execute(
            "SELECT payload_json FROM reference_fingerprint_bundles WHERE book_id = ? LIMIT 1",
            (book_id,),
        )
        row = self.cursor.fetchone()
        return self._json_loads(row[0], {}) if row else {}

    def get_skill_rules(self, category, audience=None, limit=5):
        categories = [f"skill_rule_{category}"]
        if audience:
            categories.insert(0, f"skill_rule_{category}_{audience}")

        placeholders = ",".join(["?"] * len(categories))
        self.cursor.execute(
            f"""
            SELECT rule_text
            FROM rules_ledger
            WHERE category IN ({placeholders})
              AND is_active = 1
              AND bayesian_weight >= 0.3
            ORDER BY bayesian_weight DESC, id DESC
            LIMIT ?
            """,
            (*categories, limit),
        )
        return [row[0] for row in self.cursor.fetchall()]

    # 规则系统
    def get_active_axioms(self):
        """组合并返回当前所有依然存活的规则供 Agent 使用"""
        self.cursor.execute(
            "SELECT category, rule_text FROM rules_ledger WHERE is_active = 1 AND bayesian_weight >= 0.3"
        )
        rows = self.cursor.fetchall()
        axioms = {
            "demographic_quarantine": {},
            "no_ai_flavor": "",
            "zero_cliche": "",
            "plot_logic_guidance": "",
            "opening_hook": "",
            "continuity_payoff": "",
            "strict_disguise_logic": "",
            "setting_absolute_compliance": "",
        }
        for category, text in rows:
            if category.startswith("demographic_quarantine_male_"):
                axioms["demographic_quarantine"]["male_oriented"] = self._merge_text(
                    axioms["demographic_quarantine"].get("male_oriented", ""),
                    text,
                )
                if any(marker in category for marker in ("learned_style", "style_dna", "paired_revision_style")):
                    axioms["no_ai_flavor"] = self._merge_text(axioms["no_ai_flavor"], text)
                if "plot_logic" in category:
                    axioms["plot_logic_guidance"] = self._merge_text(axioms["plot_logic_guidance"], text)
            elif category.startswith("demographic_quarantine_female_"):
                axioms["demographic_quarantine"]["female_oriented"] = self._merge_text(
                    axioms["demographic_quarantine"].get("female_oriented", ""),
                    text,
                )
                if any(marker in category for marker in ("learned_style", "style_dna", "paired_revision_style")):
                    axioms["no_ai_flavor"] = self._merge_text(axioms["no_ai_flavor"], text)
                if "plot_logic" in category:
                    axioms["plot_logic_guidance"] = self._merge_text(axioms["plot_logic_guidance"], text)
            elif category.startswith("demographic_quarantine_"):
                sub_cat = category.replace("demographic_quarantine_", "") + "_oriented"
                axioms["demographic_quarantine"][sub_cat] = self._merge_text(
                    axioms["demographic_quarantine"].get(sub_cat, ""),
                    text,
                )
            elif any(
                marker in category for marker in (
                    "learned_style",
                    "style_dna",
                    "extracted_style_rule",
                    "paired_revision_style",
                )
            ):
                axioms["no_ai_flavor"] = self._merge_text(axioms["no_ai_flavor"], text)
            elif "plot_logic" in category:
                axioms["plot_logic_guidance"] = self._merge_text(axioms["plot_logic_guidance"], text)
            elif category in axioms:
                axioms[category] = self._merge_text(axioms[category], text)
            else:
                axioms[category] = self._merge_text(axioms.get(category, ""), text)
        return axioms

    def add_dynamic_rule(self, category, rule_text, initial_weight=0.8):
        self.cursor.execute(
            "INSERT INTO rules_ledger (category, rule_text, bayesian_weight) VALUES (?, ?, ?)",
            (category, rule_text, initial_weight),
        )
        self.conn.commit()
        return self.cursor.lastrowid

    def adjust_rule_weight(self, category, delta, reason, metric_name=None, book_id=None, chapter_index=None):
        self.cursor.execute(
            """
            SELECT id, category, bayesian_weight, success_score
            FROM rules_ledger
            WHERE is_active = 1 AND (category = ? OR category LIKE ?)
            """,
            (category, f"{category}_%"),
        )
        rows = self.cursor.fetchall()
        if not rows:
            return 0

        adjusted = 0
        for rule_id, matched_category, old_weight, old_success in rows:
            new_weight = max(0.05, min(2.5, old_weight + delta))
            new_success = max(0.0, min(5.0, old_success + delta))
            is_active = 1 if new_weight >= 0.3 else 0
            self.cursor.execute(
                """
                UPDATE rules_ledger
                SET bayesian_weight = ?,
                    success_score = ?,
                    trigger_count = trigger_count + 1,
                    is_active = ?
                WHERE id = ?
                """,
                (new_weight, new_success, is_active, rule_id),
            )
            self.cursor.execute(
                """
                INSERT INTO rule_feedback (rule_id, category, book_id, chapter_index, metric_name, delta, reason)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (rule_id, matched_category, book_id, chapter_index, metric_name, delta, reason),
            )
            adjusted += 1
        self.conn.commit()
        return adjusted

    def reward_rule(self, category, reward=0.03, reason="positive_feedback", metric_name=None, book_id=None, chapter_index=None):
        return self.adjust_rule_weight(category, abs(reward), reason, metric_name, book_id, chapter_index)

    def penalize_rule(self, category):
        """兼容旧接口"""
        return self.adjust_rule_weight(category, -0.2, "legacy_penalty")

    def apply_metric_feedback(self, audience_type, evaluation_metrics, book_id=None, chapter_index=None):
        normalized_audience = normalize_audience_type(audience_type)
        demographic_root = (
            "demographic_quarantine_male"
            if normalized_audience == "male_oriented"
            else "demographic_quarantine_female"
        )
        category_map = {
            "hook_strength": ["opening_hook"],
            "audience_alignment": [demographic_root],
            "ai_scent": ["no_ai_flavor", "paired_revision_style", "extracted_style_rule"],
            "stylistic_integrity": ["no_ai_flavor", "paired_revision_style", "extracted_style_rule"],
            "style_humanity": [demographic_root, "no_ai_flavor", "paired_revision_style", "extracted_style_rule"],
            "truth_consistency": ["strict_disguise_logic", "setting_absolute_compliance"],
            "foreshadow_closure": ["continuity_payoff"],
            "coherence": ["setting_absolute_compliance", "zero_cliche"],
        }

        for metric_name, score in evaluation_metrics.items():
            if metric_name == "overall" or metric_name not in category_map:
                continue

            # 权重漂移逻辑：高分奖励，低分重罚
            if score < 60:
                delta = -0.15
            elif score < 75:
                delta = -0.06
            elif score >= 92:
                delta = 0.08
            elif score >= 85:
                delta = 0.04
            else:
                continue

            for category in category_map[metric_name]:
                reason = f"{metric_name}:{score}"
                # 针对所属分类进行精确打击/奖励
                self.adjust_rule_weight(
                    category=category,
                    delta=delta,
                    reason=reason,
                    metric_name=metric_name,
                    book_id=book_id,
                    chapter_index=chapter_index,
                )

    def cleanup_bad_rules(self):
        """清除由于超时或报错产生的垃圾规则"""
        bad_keywords = ["Error generation", "Request timed out", "connection error"]
        for keyword in bad_keywords:
            self.cursor.execute("DELETE FROM rules_ledger WHERE rule_text LIKE ?", (f"%{keyword}%",))
        self.conn.commit()
        print("🧹 [规则清洗] 已清除所有异常生成的垃圾规则。")

    def get_rule_categories_needing_distillation(self, threshold=5):
        """查找哪些分类下的活跃碎片规则过多，需要蒸馏"""
        self.cursor.execute(
            """
            SELECT category, COUNT(id) AS cnt 
            FROM rules_ledger 
            WHERE is_active = 1 
            GROUP BY category 
            HAVING cnt >= ?
            """,
            (threshold,)
        )
        return [row[0] for row in self.cursor.fetchall()]

    def get_rules_by_category(self, category):
        self.cursor.execute("SELECT id, rule_text FROM rules_ledger WHERE category = ? AND is_active = 1", (category,))
        return self.cursor.fetchall()

    def replace_distilled_rules(self, category, old_rule_ids, distilled_rule_text):
        """将旧的碎片归档并插入统一元规则"""
        if not old_rule_ids:
            return
        placeholders = ",".join(["?"] * len(old_rule_ids))
        self.cursor.execute(
            f"UPDATE rules_ledger SET is_active = 0, bayesian_weight = 0 WHERE id IN ({placeholders})",
            old_rule_ids
        )
        self.add_dynamic_rule(category, distilled_rule_text, initial_weight=1.5) # 蒸馏后的元规则拥有较高初始权重
        self.conn.commit()

    # 旧版简单库
    def add_gold(self, content):
        self.cursor.execute("INSERT INTO gold_library (content) VALUES (?)", (content,))
        self.conn.commit()
        return self.cursor.lastrowid

    def add_sandbox(self, content):
        self.cursor.execute("INSERT INTO sandbox_library (content, score) VALUES (?, ?)", (content, 0))
        self.conn.commit()
        return self.cursor.lastrowid

    def get_latest_sandbox_and_gold(self):
        self.cursor.execute("SELECT content FROM sandbox_library ORDER BY id DESC LIMIT 1")
        sandbox = self.cursor.fetchone()
        self.cursor.execute("SELECT content FROM gold_library ORDER BY id DESC LIMIT 1")
        gold = self.cursor.fetchone()
        return sandbox[0] if sandbox else "", gold[0] if gold else ""

    def clear_and_load_gold(self, content_list):
        """清除旧 Gold 库并载入新的样本内容"""
        self.cursor.execute("DELETE FROM gold_library")
        for content in content_list:
            if len(content.strip()) > 10:
                self.cursor.execute("INSERT INTO gold_library (content) VALUES (?)", (content.strip(),))
        self.conn.commit()
        print(f"✅ [Gold 库更新] 已成功载入 {len(content_list)} 条原著样本。")

    def is_file_learned(self, file_path):
        self.cursor.execute("SELECT 1 FROM learned_files WHERE file_path = ?", (file_path,))
        return self.cursor.fetchone() is not None

    def mark_file_learned(self, file_path):
        try:
            self.cursor.execute("INSERT INTO learned_files (file_path) VALUES (?)", (file_path,))
            self.conn.commit()
        except sqlite3.IntegrityError:
            pass

    def add_foreshadowing(self, item):
        self.cursor.execute("INSERT INTO foreshadowing (item, resolved) VALUES (?, ?)", (item, False))
        self.conn.commit()

    def get_unresolved_foreshadows(self):
        self.cursor.execute("SELECT id, item FROM foreshadowing WHERE resolved = False")
        return self.cursor.fetchall()

    def add_causal_link(self, parent_id, child_id, link_type, description):
        self.cursor.execute(
            "INSERT INTO causal_links (parent_id, child_id, link_type, description) VALUES (?, ?, ?, ?)",
            (parent_id, child_id, link_type, description),
        )
        self.conn.commit()

    def get_causal_chain(self):
        self.cursor.execute("SELECT * FROM causal_links ORDER BY timestamp DESC")
        return self.cursor.fetchall()

    # 结构化书籍/章节资产
    def create_or_update_book(self, book_id, title, genesis=None, skeleton=None, status="created"):
        genesis = genesis or {}
        skeleton = skeleton or {}
        self.cursor.execute(
            """
            INSERT INTO books (
                id, title, audience_type, narrative_kernel, master_style,
                world_setting, initial_conflict, genesis_json, skeleton_json, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                audience_type = excluded.audience_type,
                narrative_kernel = excluded.narrative_kernel,
                master_style = excluded.master_style,
                world_setting = excluded.world_setting,
                initial_conflict = excluded.initial_conflict,
                genesis_json = excluded.genesis_json,
                skeleton_json = excluded.skeleton_json,
                status = excluded.status,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                book_id,
                title,
                str(genesis.get("audience_type") or ""),
                str(genesis.get("narrative_kernel") or ""),
                str(genesis.get("master_style") or ""),
                str(genesis.get("world_setting") or ""),
                str(genesis.get("initial_conflict") or ""),
                self._json_dumps(genesis),
                self._json_dumps(skeleton),
                status,
            ),
        )
        self.conn.commit()

    def get_book(self, book_id):
        self.cursor.execute("SELECT * FROM books WHERE id = ?", (book_id,))
        row = self.cursor.fetchone()
        if not row:
            return None
        columns = [desc[0] for desc in self.cursor.description]
        data = dict(zip(columns, row))
        data["genesis_json"] = self._json_loads(data.get("genesis_json"), {})
        data["skeleton_json"] = self._json_loads(data.get("skeleton_json"), {})
        return data

    def update_book_status(self, book_id, status=None, latest_chapter_index=None):
        fields = []
        params = []
        if status is not None:
            fields.append("status = ?")
            params.append(status)
        if latest_chapter_index is not None:
            fields.append("latest_chapter_index = ?")
            params.append(latest_chapter_index)
        if not fields:
            return
        fields.append("updated_at = CURRENT_TIMESTAMP")
        params.append(book_id)
        self.cursor.execute(f"UPDATE books SET {', '.join(fields)} WHERE id = ?", params)
        self.conn.commit()

    def upsert_chapter_record(self, book_id, chapter_index, title, chapter_type, skeleton_data=None, history_context=None, status="planned"):
        self.cursor.execute(
            """
            INSERT INTO chapters (book_id, chapter_index, title, chapter_type, skeleton_json, history_context, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(book_id, chapter_index) DO UPDATE SET
                title = excluded.title,
                chapter_type = excluded.chapter_type,
                skeleton_json = excluded.skeleton_json,
                history_context = excluded.history_context,
                status = excluded.status,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                book_id,
                chapter_index,
                str(title or ""),
                str(chapter_type or ""),
                self._json_dumps(skeleton_data or {}),
                str(history_context or ""),
                str(status or ""),
            ),
        )
        self.conn.commit()
        self.cursor.execute("SELECT id FROM chapters WHERE book_id = ? AND chapter_index = ?", (book_id, chapter_index))
        return self.cursor.fetchone()[0]

    def update_chapter_record(self, book_id, chapter_index, status=None, summary=None, history_context=None):
        fields = []
        params = []
        if status is not None:
            fields.append("status = ?")
            params.append(str(status))
        if summary is not None:
            fields.append("summary = ?")
            params.append(str(summary))
        if history_context is not None:
            fields.append("history_context = ?")
            params.append(str(history_context))
        if not fields:
            return
        fields.append("updated_at = CURRENT_TIMESTAMP")
        params.extend([book_id, chapter_index])
        self.cursor.execute(
            f"UPDATE chapters SET {', '.join(fields)} WHERE book_id = ? AND chapter_index = ?",
            params,
        )
        self.conn.commit()

    def get_chapter(self, book_id, chapter_index):
        self.cursor.execute("SELECT * FROM chapters WHERE book_id = ? AND chapter_index = ?", (book_id, chapter_index))
        row = self.cursor.fetchone()
        if not row:
            return None
        columns = [desc[0] for desc in self.cursor.description]
        data = dict(zip(columns, row))
        data["skeleton_json"] = self._json_loads(data.get("skeleton_json"), {})
        return data

    # 运行时状态镜像
    def save_character_state_snapshot(self, book_id, character_name, state_payload):
        self.cursor.execute(
            """
            INSERT INTO character_states (book_id, character_name, state_json)
            VALUES (?, ?, ?)
            ON CONFLICT(book_id, character_name) DO UPDATE SET
                state_json = excluded.state_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (book_id, character_name, self._json_dumps(state_payload or {})),
        )
        self.conn.commit()

    def get_character_state_snapshot(self, book_id, character_name):
        self.cursor.execute(
            """
            SELECT state_json FROM character_states
            WHERE book_id = ? AND character_name = ?
            LIMIT 1
            """,
            (book_id, character_name),
        )
        row = self.cursor.fetchone()
        if not row:
            return {}
        res = self._json_loads(row[0], {}) or {}
        if not isinstance(res, dict):
            return {}
        return res

    def list_character_state_snapshots(self, book_id):
        self.cursor.execute("SELECT * FROM character_states WHERE book_id = ?", (book_id,))
        rows = self._fetchall_as_dicts()
        for row in rows:
            row["state_json"] = self._json_loads(row.get("state_json"), {})
        return rows

    def add_foreshadow_record(self, book_id, description, priority="B", target_chapter=None, resolved=False):
        self.cursor.execute(
            """
            INSERT INTO foreshadow_registry (book_id, description, priority, target_chapter, resolved, resolved_at)
            VALUES (?, ?, ?, ?, ?, CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END)
            """,
            (book_id, description, priority, target_chapter, 1 if resolved else 0, 1 if resolved else 0),
        )
        self.conn.commit()
        return self.cursor.lastrowid

    def resolve_foreshadow_record(self, foreshadow_id):
        self.cursor.execute(
            """
            UPDATE foreshadow_registry
            SET resolved = 1,
                resolved_at = COALESCE(resolved_at, CURRENT_TIMESTAMP),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (foreshadow_id,),
        )
        self.conn.commit()
        return self.cursor.rowcount > 0

    def get_due_foreshadow_records(self, book_id, current_chapter_index):
        self.cursor.execute(
            """
            SELECT * FROM foreshadow_registry
            WHERE book_id = ?
              AND resolved = 0
              AND (target_chapter IS NULL OR target_chapter <= ? OR priority = 'S')
            ORDER BY priority, target_chapter ASC, id ASC
            """,
            (book_id, current_chapter_index),
        )
        return self._fetchall_as_dicts()

    def list_unresolved_foreshadow_records(self, book_id):
        self.cursor.execute(
            """
            SELECT * FROM foreshadow_registry
            WHERE book_id = ? AND resolved = 0
            ORDER BY priority DESC, target_chapter ASC, id ASC
            """,
            (book_id,),
        )
        return self._fetchall_as_dicts()

    def add_chapter_draft(
        self,
        book_id,
        chapter_id,
        chapter_index,
        draft_stage,
        content,
        seed_prompt=None,
        model_name=None,
        evaluation=None,
        is_selected=False,
        candidate_label=None,
    ):
        self.cursor.execute(
            """
            INSERT INTO chapter_drafts (
                book_id, chapter_id, chapter_index, draft_stage, content,
                seed_prompt, model_name, evaluation_json, is_selected, candidate_label
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                book_id,
                chapter_id,
                chapter_index,
                draft_stage,
                content,
                seed_prompt,
                model_name,
                self._json_dumps(evaluation),
                1 if is_selected else 0,
                candidate_label,
            ),
        )
        self.conn.commit()
        draft_id = self.cursor.lastrowid
        if is_selected:
            self.mark_selected_draft(draft_id, book_id, chapter_index)
        return draft_id

    def mark_selected_draft(self, draft_id, book_id, chapter_index):
        self.cursor.execute(
            "UPDATE chapter_drafts SET is_selected = 0 WHERE book_id = ? AND chapter_index = ?",
            (book_id, chapter_index),
        )
        self.cursor.execute("UPDATE chapter_drafts SET is_selected = 1 WHERE id = ?", (draft_id,))
        self.conn.commit()

    def get_latest_selected_draft(self, book_id, chapter_index):
        self.cursor.execute(
            """
            SELECT id, content FROM chapter_drafts
            WHERE book_id = ? AND chapter_index = ? AND is_selected = 1
            ORDER BY id DESC LIMIT 1
            """,
            (book_id, chapter_index),
        )
        row = self.cursor.fetchone()
        return {"id": row[0], "content": row[1]} if row else None

    def add_chapter_review(self, book_id, chapter_id, chapter_index, draft_id, reviewer_name, passed, raw_feedback, score_payload=None):
        self.cursor.execute(
            """
            INSERT INTO chapter_reviews (
                book_id, chapter_id, chapter_index, draft_id, reviewer_name,
                passed, raw_feedback, score_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                book_id,
                chapter_id,
                chapter_index,
                draft_id,
                reviewer_name,
                1 if passed else 0,
                raw_feedback,
                self._json_dumps(score_payload),
            ),
        )
        self.conn.commit()
        return self.cursor.lastrowid

    def add_chapter_final(
        self,
        book_id,
        chapter_id,
        chapter_index,
        source_draft_id,
        content,
        summary,
        editor_type="machine",
        metadata=None,
        source_path=None,
    ):
        self.cursor.execute(
            """
            INSERT INTO chapter_finals (
                book_id, chapter_id, chapter_index, source_draft_id,
                editor_type, content, summary, source_path, final_metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                book_id,
                chapter_id,
                chapter_index,
                source_draft_id,
                editor_type,
                content,
                summary,
                source_path,
                self._json_dumps(metadata),
            ),
        )
        self.conn.commit()
        return self.cursor.lastrowid

    def add_chapter_score(self, book_id, chapter_id, chapter_index, final_id, metric_name, score, details=None):
        self.cursor.execute(
            """
            INSERT INTO chapter_scores (
                book_id, chapter_id, chapter_index, final_id,
                metric_name, score, details
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (book_id, chapter_id, chapter_index, final_id, metric_name, score, details),
        )
        self.conn.commit()
        return self.cursor.lastrowid

    def add_score_bundle(self, book_id, chapter_id, chapter_index, final_id, evaluation_payload):
        metrics = (evaluation_payload or {}).get("metrics", {})
        details = self._json_dumps(evaluation_payload)
        for metric_name, score in metrics.items():
            self.add_chapter_score(book_id, chapter_id, chapter_index, final_id, metric_name, score, details if metric_name == "overall" else None)

    def register_human_revision(
        self,
        book_id,
        chapter_index,
        content,
        summary=None,
        notes=None,
        source_draft_id=None,
        metadata=None,
        source_path=None,
    ):
        chapter = self.get_chapter(book_id, chapter_index)
        if not chapter:
            raise ValueError(f"章节不存在: {book_id}#{chapter_index}")

        selected_draft = None
        if source_draft_id:
            self.cursor.execute(
                "SELECT id, content FROM chapter_drafts WHERE id = ? AND book_id = ? AND chapter_index = ?",
                (source_draft_id, book_id, chapter_index),
            )
            row = self.cursor.fetchone()
            if row:
                selected_draft = {"id": row[0], "content": row[1]}
        if selected_draft is None:
            selected_draft = self.get_latest_selected_draft(book_id, chapter_index)
        final_id = self.add_chapter_final(
            book_id=book_id,
            chapter_id=chapter["id"],
            chapter_index=chapter_index,
            source_draft_id=selected_draft["id"] if selected_draft else None,
            content=content,
            summary=summary,
            editor_type="human",
            metadata={"notes": notes or "", **(metadata or {})},
            source_path=source_path,
        )
        if selected_draft:
            self.create_learning_pair(
                book_id=book_id,
                chapter_id=chapter["id"],
                chapter_index=chapter_index,
                source_draft_id=selected_draft["id"],
                source_final_id=final_id,
                draft_text=selected_draft["content"],
                final_text=content,
                pair_source="human_revision",
                source_path=source_path,
                final_source_path=source_path,
            )
        if summary:
            self.update_chapter_record(book_id, chapter_index, summary=summary)
        return final_id

    # 配对学习
    def create_learning_pair(
        self,
        book_id,
        chapter_id,
        chapter_index,
        source_draft_id,
        source_final_id,
        draft_text,
        final_text,
        pair_source="human_edit",
        source_path=None,
        final_source_path=None,
    ):
        if not draft_text or not final_text:
            return None
        self.cursor.execute(
            """
            SELECT id FROM learning_pairs
            WHERE book_id = ?
              AND chapter_index = ?
              AND COALESCE(source_draft_id, -1) = COALESCE(?, -1)
              AND COALESCE(source_final_id, -1) = COALESCE(?, -1)
            LIMIT 1
            """,
            (book_id, chapter_index, source_draft_id, source_final_id),
        )
        row = self.cursor.fetchone()
        if row:
            return row[0]

        self.cursor.execute(
            """
            INSERT INTO learning_pairs (
                book_id, chapter_id, chapter_index, source_draft_id, source_final_id,
                draft_text, final_text, pair_source, source_path, final_source_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                book_id,
                chapter_id,
                chapter_index,
                source_draft_id,
                source_final_id,
                draft_text,
                final_text,
                pair_source,
                source_path,
                final_source_path,
            ),
        )
        self.conn.commit()
        return self.cursor.lastrowid

    def get_pending_learning_pairs(self, limit=10, purpose="any"):
        if purpose == "rule":
            where_clause = "COALESCE(rule_status, 'pending') = 'pending'"
        elif purpose == "skill":
            where_clause = "COALESCE(skill_status, 'pending') = 'pending'"
        else:
            where_clause = (
                "COALESCE(rule_status, 'pending') = 'pending' "
                "OR COALESCE(skill_status, 'pending') = 'pending'"
            )
        self.cursor.execute(
            f"""
            SELECT * FROM learning_pairs
            WHERE {where_clause}
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (limit,),
        )
        rows = self._fetchall_as_dicts()
        return rows

    def mark_learning_pair_processed(self, pair_id, learned_rule_payload, purpose="all"):
        self.cursor.execute(
            """
            SELECT learned_rule_json, rule_status, skill_status
            FROM learning_pairs
            WHERE id = ?
            LIMIT 1
            """,
            (pair_id,),
        )
        row = self.cursor.fetchone()
        if not row:
            return False

        learned_payload = self._json_loads(row[0], {}) or {}
        rule_status = row[1] or "pending"
        skill_status = row[2] or "pending"
        rule_payload = None
        skill_payload = None

        if purpose == "rule":
            learned_payload["rule"] = learned_rule_payload
            rule_status = "processed"
            rule_payload = self._json_dumps(learned_rule_payload)
        elif purpose == "skill":
            learned_payload["skill"] = learned_rule_payload
            skill_status = "processed"
            skill_payload = self._json_dumps(learned_rule_payload)
        else:
            learned_payload["result"] = learned_rule_payload
            rule_status = "processed"
            skill_status = "processed"
            rule_payload = self._json_dumps(learned_rule_payload)
            skill_payload = self._json_dumps(learned_rule_payload)

        overall_status = "processed" if rule_status == "processed" and skill_status == "processed" else "partial"
        self.cursor.execute(
            """
            UPDATE learning_pairs
            SET status = ?,
                rule_status = ?,
                skill_status = ?,
                learned_rule_json = ?,
                rule_payload_json = COALESCE(?, rule_payload_json),
                skill_payload_json = COALESCE(?, skill_payload_json),
                processed_at = CASE WHEN ? = 'processed' THEN CURRENT_TIMESTAMP ELSE processed_at END
            WHERE id = ?
            """,
            (
                overall_status,
                rule_status,
                skill_status,
                self._json_dumps(learned_payload),
                rule_payload,
                skill_payload,
                overall_status,
                pair_id,
            ),
        )
        self.conn.commit()
        return True

    # 批量任务队列
    def enqueue_generation_task(
        self,
        book_id,
        title_seed,
        total_chapters=10,
        priority=100,
        candidate_count=1,
        max_attempts=3,
        rate_limit_group="default",
    ):
        self.cursor.execute(
            """
            INSERT INTO generation_tasks (
                book_id, title_seed, total_chapters, candidate_count, priority,
                status, rate_limit_group, max_attempts, error_text, next_run_after
            )
            VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, NULL, CURRENT_TIMESTAMP)
            ON CONFLICT(book_id) DO UPDATE SET
                title_seed = excluded.title_seed,
                total_chapters = excluded.total_chapters,
                candidate_count = excluded.candidate_count,
                priority = excluded.priority,
                rate_limit_group = excluded.rate_limit_group,
                max_attempts = excluded.max_attempts,
                status = 'pending',
                error_text = NULL,
                finished_at = NULL,
                next_run_after = CURRENT_TIMESTAMP,
                lease_expires_at = NULL,
                worker_id = NULL,
                last_heartbeat_at = NULL
            """,
            (book_id, title_seed, total_chapters, candidate_count, priority, rate_limit_group, max_attempts),
        )
        self.conn.commit()
        self.cursor.execute("SELECT id FROM generation_tasks WHERE book_id = ?", (book_id,))
        return self.cursor.fetchone()[0]

    def fetch_generation_tasks(self, status="ready", limit=20):
        if status == "ready":
            self.cursor.execute(
                """
                SELECT * FROM generation_tasks
                WHERE status IN ('pending', 'retrying')
                  AND (next_run_after IS NULL OR next_run_after <= CURRENT_TIMESTAMP)
                ORDER BY priority ASC, scheduled_at ASC
                LIMIT ?
                """,
                (limit,),
            )
        elif status:
            self.cursor.execute(
                """
                SELECT * FROM generation_tasks
                WHERE status = ?
                ORDER BY priority ASC, scheduled_at ASC
                LIMIT ?
                """,
                (status, limit),
            )
        else:
            self.cursor.execute(
                """
                SELECT * FROM generation_tasks
                ORDER BY scheduled_at DESC
                LIMIT ?
                """,
                (limit,),
            )
        return self._fetchall_as_dicts()

    def get_generation_task(self, task_id):
        self.cursor.execute("SELECT * FROM generation_tasks WHERE id = ?", (task_id,))
        row = self.cursor.fetchone()
        if not row:
            return None
        columns = [desc[0] for desc in self.cursor.description]
        record = dict(zip(columns, row))
        record["rollback_state_json"] = self._json_loads(record.get("rollback_state_json"), {})
        return record

    def claim_generation_task(self, task_id, worker_id=None, lease_seconds=900):
        lease_modifier = f"+{int(max(30, lease_seconds))} seconds"
        self.cursor.execute(
            """
            UPDATE generation_tasks
            SET status = 'running',
                attempts = attempts + 1,
                started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                error_text = NULL,
                worker_id = ?,
                last_heartbeat_at = CURRENT_TIMESTAMP,
                lease_expires_at = datetime(CURRENT_TIMESTAMP, ?)
            WHERE id = ?
              AND status IN ('pending', 'retrying')
              AND (next_run_after IS NULL OR next_run_after <= CURRENT_TIMESTAMP)
              AND (lease_expires_at IS NULL OR lease_expires_at <= CURRENT_TIMESTAMP)
            """,
            (worker_id, lease_modifier, task_id),
        )
        self.conn.commit()
        return self.cursor.rowcount > 0

    def heartbeat_generation_task(self, task_id, worker_id, lease_seconds=900):
        lease_modifier = f"+{int(max(30, lease_seconds))} seconds"
        self.cursor.execute(
            """
            UPDATE generation_tasks
            SET last_heartbeat_at = CURRENT_TIMESTAMP,
                lease_expires_at = datetime(CURRENT_TIMESTAMP, ?)
            WHERE id = ? AND status = 'running' AND worker_id = ?
            """,
            (lease_modifier, task_id, worker_id),
        )
        self.conn.commit()
        return self.cursor.rowcount > 0

    def set_task_rollback_state(self, task_id, rollback_state):
        self.cursor.execute(
            "UPDATE generation_tasks SET rollback_state_json = ? WHERE id = ?",
            (self._json_dumps(rollback_state), task_id),
        )
        self.conn.commit()

    def complete_generation_task(self, task_id):
        self.cursor.execute(
            """
            UPDATE generation_tasks
            SET status = 'completed',
                finished_at = CURRENT_TIMESTAMP,
                lease_expires_at = NULL,
                worker_id = NULL,
                last_heartbeat_at = NULL
            WHERE id = ?
            """,
            (task_id,),
        )
        self.conn.commit()

    def requeue_stale_generation_tasks(self, retry_delay_seconds=120):
        self.cursor.execute(
            """
            SELECT id, attempts, max_attempts
            FROM generation_tasks
            WHERE status = 'running'
              AND lease_expires_at IS NOT NULL
              AND lease_expires_at <= CURRENT_TIMESTAMP
            """
        )
        stale_tasks = self.cursor.fetchall()
        if not stale_tasks:
            return 0

        retry_modifier = f"+{int(max(30, retry_delay_seconds))} seconds"
        for task_id, attempts, max_attempts in stale_tasks:
            if attempts >= max_attempts:
                self.cursor.execute(
                    """
                    UPDATE generation_tasks
                    SET status = 'failed',
                        error_text = COALESCE(error_text, 'worker lease expired'),
                        finished_at = CURRENT_TIMESTAMP,
                        lease_expires_at = NULL,
                        worker_id = NULL,
                        last_heartbeat_at = NULL
                    WHERE id = ?
                    """,
                    (task_id,),
                )
            else:
                self.cursor.execute(
                    """
                    UPDATE generation_tasks
                    SET status = 'retrying',
                        error_text = COALESCE(error_text, 'worker lease expired'),
                        next_run_after = datetime(CURRENT_TIMESTAMP, ?),
                        finished_at = NULL,
                        lease_expires_at = NULL,
                        worker_id = NULL,
                        last_heartbeat_at = NULL
                    WHERE id = ?
                    """,
                    (retry_modifier, task_id),
                )
        self.conn.commit()
        return len(stale_tasks)

    def fail_generation_task(self, task_id, error_text, retry_delay_seconds=180, rollback_state=None):
        task = self.get_generation_task(task_id)
        if not task:
            return
        if rollback_state is not None:
            self.set_task_rollback_state(task_id, rollback_state)

        retry_modifier = f"+{int(max(30, retry_delay_seconds))} seconds"
        if task.get("attempts", 0) < task.get("max_attempts", 3):
            self.cursor.execute(
                """
                UPDATE generation_tasks
                SET status = 'retrying',
                    error_text = ?,
                    next_run_after = datetime(CURRENT_TIMESTAMP, ?),
                    finished_at = NULL,
                    lease_expires_at = NULL,
                    worker_id = NULL,
                    last_heartbeat_at = NULL
                WHERE id = ?
                """,
                (error_text[:1000], retry_modifier, task_id),
            )
        else:
            self.cursor.execute(
                """
                UPDATE generation_tasks
                SET status = 'failed',
                    error_text = ?,
                    finished_at = CURRENT_TIMESTAMP,
                    lease_expires_at = NULL,
                    worker_id = NULL,
                    last_heartbeat_at = NULL
                WHERE id = ?
                """,
                (error_text[:1000], task_id),
            )
        self.conn.commit()

    def _select_id_list(self, table_name, book_id):
        self.cursor.execute(f"SELECT id FROM {table_name} WHERE book_id = ?", (book_id,))
        return [row[0] for row in self.cursor.fetchall()]

    def _select_rows_for_book(self, table_name, book_id):
        self.cursor.execute(f"SELECT * FROM {table_name} WHERE book_id = ?", (book_id,))
        return self._fetchall_as_dicts()

    def _restore_rows_by_id(self, table_name, book_id, snapshot_rows):
        snapshot_rows = snapshot_rows or []
        snapshot_ids = {row["id"] for row in snapshot_rows}
        self.cursor.execute(f"SELECT id FROM {table_name} WHERE book_id = ?", (book_id,))
        current_ids = [row[0] for row in self.cursor.fetchall()]
        to_delete = [row_id for row_id in current_ids if row_id not in snapshot_ids]
        if to_delete:
            placeholders = ",".join("?" for _ in to_delete)
            self.cursor.execute(f"DELETE FROM {table_name} WHERE id IN ({placeholders})", to_delete)

        for row in snapshot_rows:
            restored_row = dict(row)
            if "genesis_json" in restored_row and isinstance(restored_row["genesis_json"], dict):
                restored_row["genesis_json"] = self._json_dumps(restored_row["genesis_json"])
            if "skeleton_json" in restored_row and isinstance(restored_row["skeleton_json"], dict):
                restored_row["skeleton_json"] = self._json_dumps(restored_row["skeleton_json"])
            if "state_json" in restored_row and isinstance(restored_row["state_json"], dict):
                restored_row["state_json"] = self._json_dumps(restored_row["state_json"])
            columns = list(restored_row.keys())
            placeholders = ", ".join("?" for _ in columns)
            column_sql = ", ".join(columns)
            self.cursor.execute(
                f"INSERT OR REPLACE INTO {table_name} ({column_sql}) VALUES ({placeholders})",
                [restored_row[column] for column in columns],
            )

    def snapshot_book_state(self, book_id):
        book = self.get_book(book_id)
        return {
            "book": book,
            "chapters": self._select_rows_for_book("chapters", book_id),
            "character_states": self._select_rows_for_book("character_states", book_id),
            "foreshadow_rows": self._select_rows_for_book("foreshadow_registry", book_id),
            "draft_ids": self._select_id_list("chapter_drafts", book_id),
            "review_ids": self._select_id_list("chapter_reviews", book_id),
            "final_ids": self._select_id_list("chapter_finals", book_id),
            "score_ids": self._select_id_list("chapter_scores", book_id),
            "pair_ids": self._select_id_list("learning_pairs", book_id),
            "usage_ids": self._select_id_list("usage_logs", book_id),
        }

    def rollback_book_to_snapshot(self, book_id, snapshot):
        snapshot = snapshot or {}
        existing_book = snapshot.get("book")
        keep_ids_map = {
            "chapter_drafts": set(snapshot.get("draft_ids", [])),
            "chapter_reviews": set(snapshot.get("review_ids", [])),
            "chapter_finals": set(snapshot.get("final_ids", [])),
            "chapter_scores": set(snapshot.get("score_ids", [])),
            "learning_pairs": set(snapshot.get("pair_ids", [])),
            "usage_logs": set(snapshot.get("usage_ids", [])),
        }

        for table_name, keep_ids in keep_ids_map.items():
            self.cursor.execute(f"SELECT id FROM {table_name} WHERE book_id = ?", (book_id,))
            current_ids = [row[0] for row in self.cursor.fetchall()]
            to_delete = [row_id for row_id in current_ids if row_id not in keep_ids]
            if to_delete:
                placeholders = ",".join("?" for _ in to_delete)
                self.cursor.execute(f"DELETE FROM {table_name} WHERE id IN ({placeholders})", to_delete)

        self._restore_rows_by_id("chapters", book_id, snapshot.get("chapters", []))
        self._restore_rows_by_id("character_states", book_id, snapshot.get("character_states", []))
        self._restore_rows_by_id("foreshadow_registry", book_id, snapshot.get("foreshadow_rows", []))

        if existing_book:
            self.cursor.execute(
                """
                INSERT OR REPLACE INTO books (
                    id, title, audience_type, narrative_kernel, master_style,
                    world_setting, initial_conflict, genesis_json, skeleton_json,
                    status, latest_chapter_index, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT created_at FROM books WHERE id = ?), CURRENT_TIMESTAMP), CURRENT_TIMESTAMP)
                """,
                (
                    book_id,
                    existing_book["title"],
                    existing_book["audience_type"],
                    existing_book["narrative_kernel"],
                    existing_book["master_style"],
                    existing_book["world_setting"],
                    existing_book["initial_conflict"],
                    self._json_dumps(existing_book.get("genesis_json")),
                    self._json_dumps(existing_book.get("skeleton_json")),
                    existing_book["status"],
                    existing_book["latest_chapter_index"],
                    book_id,
                ),
            )
        else:
            self.cursor.execute("DELETE FROM books WHERE id = ?", (book_id,))
        self.conn.commit()

    def find_books_by_title_like(self, title, limit=10):
        like_value = f"%{title}%"
        self.cursor.execute(
            """
            SELECT id, title, audience_type, latest_chapter_index, status
            FROM books
            WHERE title LIKE ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (like_value, limit),
        )
        return self._fetchall_as_dicts()

    def list_chapters_for_book(self, book_id):
        self.cursor.execute(
            "SELECT * FROM chapters WHERE book_id = ? ORDER BY chapter_index ASC",
            (book_id,),
        )
        rows = self._fetchall_as_dicts()
        for row in rows:
            row["skeleton_json"] = self._json_loads(row.get("skeleton_json"), {})
        return rows

    def get_pipeline_overview(self):
        overview = {}
        self.cursor.execute("SELECT COUNT(*) FROM books")
        overview["book_count"] = self.cursor.fetchone()[0]
        self.cursor.execute("SELECT COUNT(*) FROM chapters")
        overview["chapter_count"] = self.cursor.fetchone()[0]
        self.cursor.execute("SELECT COUNT(*) FROM chapter_finals WHERE editor_type = 'machine'")
        overview["machine_final_count"] = self.cursor.fetchone()[0]
        self.cursor.execute("SELECT COUNT(*) FROM chapter_finals WHERE editor_type = 'human'")
        overview["human_final_count"] = self.cursor.fetchone()[0]
        self.cursor.execute("SELECT COUNT(*) FROM learning_pairs WHERE status = 'pending'")
        overview["pending_learning_pairs"] = self.cursor.fetchone()[0]
        self.cursor.execute(
            """
            SELECT COUNT(*) FROM learning_pairs
            WHERE COALESCE(rule_status, 'pending') = 'pending'
               OR COALESCE(skill_status, 'pending') = 'pending'
            """
        )
        overview["pending_learning_pairs"] = self.cursor.fetchone()[0]
        self.cursor.execute("SELECT COUNT(*) FROM generation_tasks WHERE status = 'pending'")
        overview["pending_tasks"] = self.cursor.fetchone()[0]
        self.cursor.execute("SELECT COUNT(*) FROM generation_tasks WHERE status = 'retrying'")
        overview["retrying_tasks"] = self.cursor.fetchone()[0]
        self.cursor.execute("SELECT COUNT(*) FROM generation_tasks WHERE status = 'running'")
        overview["running_tasks"] = self.cursor.fetchone()[0]
        self.cursor.execute("SELECT COUNT(*) FROM generation_tasks WHERE status = 'failed'")
        overview["failed_tasks"] = self.cursor.fetchone()[0]
        return overview

    def get_learning_stats(self):
        """获取目前学习到的规则统计"""
        self.cursor.execute("SELECT category, COUNT(*) FROM rules_ledger WHERE is_active = 1 GROUP BY category")
        raw_stats = dict(self.cursor.fetchall())

        plot_rule_count = 0
        style_rule_count = 0
        for category, count in raw_stats.items():
            if "plot_logic" in category:
                plot_rule_count += count
            if any(
                marker in category
                for marker in ("learned_style", "style_dna", "extracted_style_rule", "paired_revision_style")
            ):
                style_rule_count += count

        raw_stats["plot_rule_total"] = plot_rule_count
        raw_stats["style_rule_total"] = style_rule_count
        return raw_stats

    def get_latest_rules(self, limit=5):
        """获取最近学到的规则"""
        self.cursor.execute("SELECT category, rule_text FROM rules_ledger ORDER BY id DESC LIMIT ?", (limit,))
        return self.cursor.fetchall()


class ForeshadowingLedger:
    def __init__(self, db_manager):
        self.db = db_manager

    def add_clue(self, clue):
        self.db.add_foreshadowing(clue)

    def get_clues(self):
        return self.db.get_unresolved_foreshadows()
