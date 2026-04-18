from neo4j import GraphDatabase
import logging
import os

class Neo4jManager:
    def __init__(self, uri=None, user=None, password=None):
        """初始化 Neo4j 驱动"""
        uri = uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
        user = user or os.getenv("NEO4J_USER", "neo4j")
        password = password or os.getenv("NEO4J_PASSWORD")
        try:
            if not password:
                raise RuntimeError("NEO4J_PASSWORD 未设置")
            self.driver = GraphDatabase.driver(uri, auth=(user, password))
            self.verify_connectivity()
        except Exception as e:
            logging.error(f"⚠️ [Neo4j] 初始化失败, 请确保本地服务已启动: {e}")
            self.driver = None

    def verify_connectivity(self):
        if self.driver:
            with self.driver.session() as session:
                session.run("RETURN 1")
            self._ensure_indexes()

    def _ensure_indexes(self):
        """为千万级节点查询加装防刷爆索引"""
        if not self.driver: return
        with self.driver.session() as session:
            try:
                session.run("CREATE INDEX char_lookup IF NOT EXISTS FOR (c:Character) ON (c.novel_id, c.name)")
                session.run("CREATE INDEX novel_lookup IF NOT EXISTS FOR (n:Novel) ON (n.id)")
                session.run("CREATE INDEX foreshadow_lookup IF NOT EXISTS FOR (f:Foreshadow) ON (f.novel_id, f.sql_id)")
                logging.info("✔️ [Neo4j] 图谱索引初始化完成")
            except Exception as e:
                logging.error(f"⚠️ [Neo4j] 索引创建失败: {e}")

    def close(self):
        if self.driver:
            self.driver.close()

    # ====== 1. 绝对状态机 (Character State) ======
    def update_character_state(self, novel_id, char_name, props_dict):
        """UPSERT 角色绝对物理状态与认知状态 (解决信息差盲区)"""
        if not self.driver: return
        if not props_dict: return
        
        # 拆分物理属性与认知属性
        physical = props_dict.get("physical_state", {})
        cognitive = props_dict.get("cognitive_state", {})
        
        # 如果老代码传的是扁平字典，默认全部作为物理状态
        if "physical_state" not in props_dict and "cognitive_state" not in props_dict:
            physical = props_dict
        
        set_statements = []
        for k in physical.keys():
            if k != 'novel_id': set_statements.append(f"c.`{k}` = $phys_{k}")
        for k in cognitive.keys():
            if k != 'novel_id': set_statements.append(f"c.`cog_{k}` = $cog_{k}")
            
        if not set_statements:
            set_statements = ["c.last_updated = datetime()"]
        else:
            set_statements.append("c.last_updated = datetime()")
            
        set_statements_str = ", ".join(set_statements)
        
        query = f"""
        MERGE (c:Character {{name: $char_name, novel_id: $novel_id}})
        SET {set_statements_str}
        """
        params = {"char_name": char_name, "novel_id": novel_id}
        for k, v in physical.items():
            if k != 'novel_id': params[f"phys_{k}"] = v
        for k, v in cognitive.items():
            if k != 'novel_id': params[f"cog_{k}"] = v
        
        with self.driver.session() as session:
            session.run(query, **params)

    def get_character_state(self, novel_id, char_name):
        """获取角色的状态 snapshot（分离出 cognitive_state 和 physical_state）"""
        if not self.driver:
            return {}
        query = "MATCH (c:Character {name: $char_name, novel_id: $novel_id}) RETURN properties(c) AS props"
        with self.driver.session() as session:
            result = session.run(query, char_name=char_name, novel_id=novel_id).single()
            if result:
                props = result["props"]
                physical = {}
                cognitive = {}
                for k, v in props.items():
                    if k in ["name", "novel_id", "last_updated"]: continue
                    if k.startswith("cog_"):
                        cognitive[k[4:]] = v
                    else:
                        physical[k] = v
                identity_mask = physical.get("identity_mask")
                return {
                    "physical_state": physical,
                    "cognitive_state": cognitive,
                    "identity_mask": identity_mask or "无身份伪装",
                }
            return {}

    # ====== 2. 动态伏笔池 (Causal DAG & TTR) ======
    def add_foreshadow(self, novel_id, item_desc, priority="B", target_chapter=None, sql_id=None, resolved=False):
        """
        录入伏笔。
        :param priority: S (大悬念), A (中型), B (细节回调)
        :param target_chapter: 预期在第几章引爆排解（TTR机制）
        """
        if not self.driver: return
        if sql_id is not None:
            query = """
            MERGE (f:Foreshadow {novel_id: $novel_id, sql_id: $sql_id})
            ON CREATE SET f.created_at = datetime()
            SET f.description = $item_desc,
                f.priority = $priority,
                f.target_chapter = $target_chapter,
                f.resolved = $resolved,
                f.last_updated = datetime()
            """
            params = {
                "novel_id": novel_id,
                "sql_id": int(sql_id),
                "item_desc": item_desc,
                "priority": priority,
                "target_chapter": target_chapter,
                "resolved": bool(resolved),
            }
        else:
            query = """
            CREATE (f:Foreshadow {
                novel_id: $novel_id,
                description: $item_desc,
                priority: $priority,
                target_chapter: $target_chapter,
                resolved: $resolved,
                created_at: datetime()
            })
            """
            params = {
                "novel_id": novel_id,
                "item_desc": item_desc,
                "priority": priority,
                "target_chapter": target_chapter,
                "resolved": bool(resolved),
            }
        with self.driver.session() as session:
            session.run(query, **params)

    def get_due_foreshadows(self, novel_id, current_chapter_index):
        """提取【到期应当处理】的伏笔，而不是盲目全拉"""
        if not self.driver: return []
        query = """
        MATCH (f:Foreshadow {novel_id: $novel_id, resolved: false})
        WHERE f.target_chapter <= $current_chapter_index OR f.priority = 'S'
        RETURN coalesce(f.sql_id, id(f)) AS f_id, f.sql_id AS sql_id, f.description AS desc, f.priority AS priority, f.target_chapter AS target
        ORDER BY f.priority, f.target_chapter ASC
        """
        with self.driver.session() as session:
            results = session.run(query, novel_id=novel_id, current_chapter_index=current_chapter_index)
            return [{"id": record["f_id"], "sql_id": record["sql_id"], "desc": record["desc"], "priority": record["priority"]} for record in results]

    def resolve_foreshadow(self, f_id):
        """在章节中填坑后，核销图谱中的伏笔"""
        if not self.driver: return
        query = """
        MATCH (f:Foreshadow)
        WHERE id(f) = $f_id OR f.sql_id = $f_id
        SET f.resolved = true,
            f.resolved_at = COALESCE(f.resolved_at, datetime()),
            f.last_updated = datetime()
        """
        with self.driver.session() as session:
            session.run(query, f_id=f_id)

    def get_late_game_foreshadows(self, novel_id):
        """专门给 8-10 章使用的‘全域清仓’逻辑，强制列出所有未回收伏笔"""
        if not self.driver: return []
        query = """
        MATCH (f:Foreshadow {novel_id: $novel_id, resolved: false})
        RETURN coalesce(f.sql_id, id(f)) AS f_id, f.sql_id AS sql_id, f.description AS desc, f.priority AS priority
        ORDER BY f.priority DESC
        """
        with self.driver.session() as session:
            results = session.run(query, novel_id=novel_id)
            return [{"id": record["f_id"], "sql_id": record["sql_id"], "desc": record["desc"], "priority": record["priority"]} for record in results]

    # ====== 3. 章节流长线链路 (Chapter Causal Links) ======
    def add_chapter_node(self, novel_id, chapter_index, summary):
        if not self.driver: return
        query = """
        MERGE (cy:Novel {id: $novel_id})
        MERGE (ch:Chapter {index: $chapter_index, novel_id: $novel_id})
        SET ch.summary = $summary,
            ch.last_updated = datetime()
        MERGE (ch)-[:BELONGS_TO]->(cy)
        """
        with self.driver.session() as session:
            session.run(query, novel_id=novel_id, chapter_index=chapter_index, summary=summary)
            
        # 如果不是第一章，连接上一章形成链条
        if chapter_index > 1:
            link_query = """
            MATCH (prev:Chapter {index: $prev_idx}), (curr:Chapter {index: $curr_idx})
            WHERE (prev)-[:BELONGS_TO]->(:Novel {id: $novel_id}) AND (curr)-[:BELONGS_TO]->(:Novel {id: $novel_id})
            MERGE (prev)-[:LEADS_TO]->(curr)
            """
            with self.driver.session() as session:
                session.run(link_query, prev_idx=chapter_index-1, curr_idx=chapter_index, novel_id=novel_id)

    def purge_novel(self, novel_id):
        """按 novel_id 清理失败任务写入的图谱副作用。"""
        if not self.driver:
            return
        cleanup_queries = [
            ("MATCH (f:Foreshadow {novel_id: $novel_id}) DETACH DELETE f", {"novel_id": novel_id}),
            ("MATCH (c:Character {novel_id: $novel_id}) DETACH DELETE c", {"novel_id": novel_id}),
            ("MATCH (ch:Chapter {novel_id: $novel_id}) DETACH DELETE ch", {"novel_id": novel_id}),
            ("MATCH (n:Novel {id: $novel_id}) DETACH DELETE n", {"novel_id": novel_id}),
        ]
        with self.driver.session() as session:
            for query, params in cleanup_queries:
                session.run(query, **params)
