import os
import json
import re
from datetime import datetime
from autonomous_learning_job import AutonomousLearningEngine
from auditors import DisguiseLogicAuditor, DynamicArcAuditor, PlagiarismGuard
from db import DatabaseManager
from evolution_api import MasterEvolutionEngine
from genesis_api import GenesisDirector
from sequence_planner import SequencePlanner


class ChapterDirector:
    def __init__(
        self,
        novel_id,
        novel_name,
        setting=None,
        skeleton=None,
        total_chapters=10,
        db_manager=None,
        run_autonomous_learning=False,
        candidate_count=2,
        blacklist=None,
        workspace_dir=None,
        isolated_task_mode=False,
        verbose=True  # 新增：控制详细日志输出
    ):
        self.novel_id = novel_id
        self.novel_name = novel_name
        self.total_chapters = total_chapters
        self.run_autonomous_learning = run_autonomous_learning
        self.candidate_count = max(1, int(candidate_count or 1))
        self.isolated_task_mode = isolated_task_mode
        self.blacklist = blacklist or []
        self.verbose = verbose
        self.db_manager = db_manager or DatabaseManager()

        existing_book = self.db_manager.get_book(self.novel_id) or {}
        stored_setting = existing_book.get("genesis_json") or {}
        stored_skeleton = existing_book.get("skeleton_json") or {}
        self.setting = setting or stored_setting or {}
        self.skeleton = skeleton or stored_skeleton or {}

        # 批处理/兜底场景允许只给标题种子，内部自动补全设定与大纲。
        if not self.setting:
            genesis = GenesisDirector()
            self.setting = genesis.generate_genesis_setting(self.novel_name)
        if not self.skeleton:
            planner = SequencePlanner()
            self.skeleton = planner.plan_novel_arc(self.setting)
        
        # 工业化工作空间初始化
        self.workspace_dir = workspace_dir or os.path.join(os.getcwd(), datetime.now().strftime("%Y-%m-%d"), self.novel_name)
        self._init_workspace()

        self.db_manager.create_or_update_book(
            book_id=self.novel_id,
            title=self.novel_name,
            genesis=self.setting,
            skeleton=self.skeleton,
            status=existing_book.get("status") or "planning",
        )

        self.engine = MasterEvolutionEngine(
            db_manager=self.db_manager,
            audience_type=self.setting.get("audience_type", "female_oriented"),
            logic_layer=DisguiseLogicAuditor,
            record_rule_feedback=not self.isolated_task_mode,
            record_sandbox_memory=not self.isolated_task_mode,
            verbose=self.verbose
        )
        self.engine.master_style = self.setting.get("master_style", "具有顶级商业张力的极速爽文")
        # 强化角色数据容错
        main_char_data = self.setting.get("main_character", {})
        if isinstance(main_char_data, list) and len(main_char_data) > 0:
            main_char_data = main_char_data[0]
        elif not isinstance(main_char_data, dict):
            main_char_data = {}

        self.engine.main_character_name = main_char_data.get("name", "主角")

        # 注入版权卫士
        if self.blacklist:
            print(f"🛡️ [法务挂载] 已加载 {len(self.blacklist)} 条原著禁语名单。")
            self.engine.add_auditor(PlagiarismGuard(self.blacklist))

        if "main_character" in self.setting:
            main_character = self.setting["main_character"]
            if isinstance(main_character, list) and len(main_character) > 0:
                main_character = main_character[0]
            
            if isinstance(main_character, dict):
                self._rehydrate_runtime_state(main_character)

        self.sliding_window_summary = []

    def _init_workspace(self):
        """初始化工业化目录矩阵"""
        subdirs = ["audit", "chapter", "prompt", "report", "state"]
        for sd in subdirs:
            path = os.path.join(self.workspace_dir, sd)
            if not os.path.exists(path):
                os.makedirs(path)
        print(f"🏗️ [工作空间初始化] 工业化产出矩阵已就绪: {self.workspace_dir}")

    def _build_initial_character_state(self, main_character):
        physical_state = {}
        cognitive_state = {}
        if main_character.get("initial_inventory"):
            physical_state["inventory"] = main_character.get("initial_inventory")
        if main_character.get("identity_mask"):
            physical_state["identity_mask"] = main_character.get("identity_mask")
        if main_character.get("base_personality"):
            cognitive_state["personality"] = main_character.get("base_personality")

        state_payload = {
            "physical_state": physical_state,
            "cognitive_state": cognitive_state,
        }
        if physical_state.get("identity_mask"):
            state_payload["identity_mask"] = physical_state["identity_mask"]
        return state_payload

    def _rehydrate_runtime_state(self, main_character):
        char_name = main_character.get("name", "主角")
        initial_state = self._build_initial_character_state(main_character)
        persisted_state = self.db_manager.get_character_state_snapshot(self.novel_id, char_name) or initial_state

        self.engine.neo4j.purge_novel(self.novel_id)
        self.engine.vector_db.remove_novel_plots(self.novel_id)

        if persisted_state:
            self.engine.neo4j.update_character_state(self.novel_id, char_name, persisted_state)
            self.db_manager.save_character_state_snapshot(self.novel_id, char_name, persisted_state)

        for chapter in self.db_manager.list_chapters_for_book(self.novel_id):
            if chapter.get("status") != "completed":
                continue
            summary = chapter.get("summary")
            if not summary:
                continue
            self.engine.neo4j.add_chapter_node(self.novel_id, chapter.get("chapter_index"), summary)
            self.engine.vector_db.add_plot(
                summary,
                metadata={
                    "source": "chapter_summary",
                    "novel_id": self.novel_id,
                    "chapter_index": chapter.get("chapter_index"),
                },
            )

        for foreshadow in self.db_manager.list_unresolved_foreshadow_records(self.novel_id):
            self.engine.neo4j.add_foreshadow(
                self.novel_id,
                foreshadow.get("description"),
                foreshadow.get("priority", "B"),
                foreshadow.get("target_chapter"),
                sql_id=foreshadow.get("id"),
                resolved=bool(foreshadow.get("resolved")),
            )

    def compile_history_context(self):
        """将前几章的摘要打成滑动窗口上下文"""
        if not self.sliding_window_summary:
            return "无前情提要（开局）。"

        recent = self.sliding_window_summary[-3:]
        context = "【前情提要】：\n"
        for offset, summary in enumerate(recent, start=max(1, len(self.sliding_window_summary) - len(recent) + 1)):
            context += f"- 剧情进度 {offset}：{summary}\n"
        return context

    def run_pipeline(self):
        print(f"\n🎬 [总导演挂载] 开始生成作品: {self.novel_name} (共{self.total_chapters}章)")
        try:
            if self.run_autonomous_learning:
                if self.verbose:
                    print(f">> [自主学习启动] 准备注入进化规则...")
                self.db_manager.update_book_status(self.novel_id, status="learning")
                learner = AutonomousLearningEngine()
                learner.run_learning_cycle()
                self.engine.start_perpetual_learning()

            self.db_manager.update_book_status(self.novel_id, status="generating")

            for chapter_idx in range(0, self.total_chapters + 1):
                if chapter_idx == 0:
                    title = "楔子"
                else:
                    title = f"第{chapter_idx}章"
                
                # 1. 断点续传逻辑
                existing_chapter = self.db_manager.get_chapter(self.novel_id, chapter_idx)
                if existing_chapter and existing_chapter.get("status") == "completed":
                    chapter_summary = existing_chapter.get("summary")
                    if chapter_summary:
                        print(f"   ⏩ [{self.novel_name}] 跳过已完成章节: {title}")
                        self.sliding_window_summary.append(chapter_summary)
                        continue

                print(f"   🎥 [{self.novel_name}] 正在调度: {title}")
                
                is_prologue = chapter_idx == 0
                is_epilogue = chapter_idx == self.total_chapters
                chapter_type = "prologue" if is_prologue else ("epilogue" if is_epilogue else "normal")

                # 2. 只有在此刻才拉取真理层状态，确保最实时
                absolute_state = self.engine.neo4j.get_character_state(self.novel_id, self.engine.main_character_name)
                history_context = self.compile_history_context()
                
                # 3. 大后期（8-10章）伏笔预警机制：全员强制清仓
                late_game_clues = []
                if chapter_idx >= 8:
                    late_game_clues = self.engine.neo4j.get_late_game_foreshadows(self.novel_id)
                    if late_game_clues and self.verbose:
                        print(f"   🚩 [大后期清仓] 发现 {len(late_game_clues)} 个未回收伏笔，将强制注入本章目标。")

                # 获取本章计划
                chapter_skeleton = {}
                if self.skeleton and "novel_arc" in self.skeleton:
                    for arc_item in self.skeleton["novel_arc"]:
                        if arc_item.get("chapter_idx") == chapter_idx:
                            chapter_skeleton = arc_item
                            break
                
                # 如果有大后期伏笔，强行并入大纲指令
                if late_game_clues:
                    clue_descs = "、".join([c['desc'] for c in late_game_clues])
                    chapter_skeleton["goal"] = chapter_skeleton.get("goal", "") + f" (必须顺带回收以下所有残余伏笔：{clue_descs})"

                base_seed = self._generate_chapter_seed(chapter_idx, chapter_type, history_context, chapter_skeleton)

                chapter_id = self.db_manager.upsert_chapter_record(
                    book_id=self.novel_id,
                    chapter_index=chapter_idx,
                    title=title,
                    chapter_type=chapter_type,
                    skeleton_data=chapter_skeleton,
                    history_context=history_context,
                    status="generating",
                )

                chapter_result = self.engine.generate_chapter(
                    novel_id=self.novel_id,
                    seed_prompt=base_seed,
                    title=title,
                    chapter_type=chapter_type,
                    chapter_index=chapter_idx,
                    skeleton_data=chapter_skeleton,
                    chapter_id=chapter_id,
                    history_context=history_context,
                    candidate_count=self.candidate_count,
                )

                self.engine.save_result(chapter_result["content"], f"{self.novel_name}_{title}")
                self.engine.save_industrial_artifacts(self.workspace_dir, chapter_idx, title, chapter_result)
                self.sliding_window_summary.append(chapter_result["summary"])

                # ==========================
                # 动态重铸检测 (剧变审计)
                # ==========================
                self._check_and_replan(chapter_idx, chapter_result, chapter_skeleton)

                self.db_manager.update_book_status(
                    self.novel_id,
                    latest_chapter_index=chapter_idx,
                    status="generating",
                )

                print(
                    f"   ✅ [{self.novel_name}:{title}] 调度完成 | 量化总分 {chapter_result['evaluation']['metrics']['overall']:.2f}"
                )

            self.db_manager.update_book_status(
                self.novel_id,
                status="completed",
                latest_chapter_index=self.total_chapters,
            )
            return self.novel_id
        except Exception as e:
            import traceback
            error_msg = f"❌ [严重故障] 作品 {self.novel_name} 在生成中崩溃：\n{str(e)}\n{traceback.format_exc()}"
            print(error_msg)
            # 工业化存档：将错误写入审计目录
            crash_path = os.path.join(self.workspace_dir, "audit", "crash_report.md")
            with open(crash_path, "w", encoding="utf-8") as f:
                f.write(f"# 灾难性故障报告\n\n时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n## 错误堆栈\n```\n{traceback.format_exc()}\n```\n")
            
            self.db_manager.update_book_status(self.novel_id, status="failed")
            raise

    def _generate_chapter_seed(self, chapter_idx, chapter_type, history_context, chapter_skeleton):
        if chapter_type == "prologue":
            return (
                f"小说名称：《{self.novel_name}》。\n"
                f"世界观背景：{self.setting.get('world_setting')}。\n"
                f"本章目标：{chapter_skeleton.get('goal', '开启故事')}。\n"
                f"请基于以下矛盾点【{self.setting.get('initial_conflict')}】编写第一章作为楔子。"
            )
        elif chapter_type == "epilogue":
             prologue_summary = self.sliding_window_summary[0] if self.sliding_window_summary else "无"
             global_res = self.skeleton.get("global_resolution", "圆满收官。")
             return (
                f"小说名称：《{self.novel_name}》。\n"
                f"【开局回顾】：{prologue_summary}\n"
                f"【终局设定】：{global_res}\n"
                f"{history_context}\n"
                "请爆发终极矛盾，形成完美闭环并绝杀收官！"
            )
        else:
            return (
                f"小说名称：《{self.novel_name}》。\n"
                f"{history_context}\n"
                f"本章大纲指引：{chapter_skeleton.get('content_plan', '继续推进剧情')}\n"
                "请基于大纲推进激烈冲突。"
            )

    def _check_and_replan(self, chapter_idx, chapter_result, chapter_skeleton):
        if chapter_idx >= self.total_chapters:
            return

        expected = chapter_skeleton.get("goal") or chapter_skeleton.get("content_plan")
        auditor = DynamicArcAuditor(chapter_idx, expected)
        res = auditor.audit(chapter_result["content"], chapter_result["summary"])

        needs_replan = "[需重铸]" in res
        
        # 兼容旧逻辑的蝴蝶效应检测
        new_clue = chapter_result.get("new_clue")
        state_delta = chapter_result.get("state_delta", {})
        if not needs_replan:
            if new_clue and new_clue[0] == "S": needs_replan = True
            elif state_delta and len(state_delta) >= 2: needs_replan = True

        if needs_replan:
            print(f"⚠️ [大纲重铸] 检测到剧情脱缰或剧变，正在针对未来 {self.total_chapters - chapter_idx} 章重绘蓝图...")
            planner = SequencePlanner()
            self.skeleton = planner.replan_novel_arc(
                genesis_setting=self.setting,
                current_arc=self.skeleton,
                current_idx=chapter_idx,
                new_state=state_delta,
                new_clue=new_clue
            )
            self.db_manager.create_or_update_book(
                book_id=self.novel_id,
                title=self.novel_name,
                genesis=self.setting,
                skeleton=self.skeleton,
                status="generating",
            )
