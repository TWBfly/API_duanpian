import json
import re
import concurrent.futures
import os
import shutil
from datetime import datetime
from autonomous_learning_job import AutonomousLearningEngine
from auditors import DisguiseLogicAuditor, DynamicArcAuditor, PlagiarismGuard, PlotCollisionAuditor
from db import DatabaseManager
from evolution_api import MasterEvolutionEngine
from genesis_api import GenesisDirector
from logger import logger
from novel_utils import (
    audience_display_label,
    chapter_title_for_index,
    chapter_type_for_index,
    detect_setting_conflicts,
    expected_chapter_indices,
    extract_skeleton_plot_hint,
    extract_skeleton_segments,
    normalize_total_chapters,
    normalize_audience_type,
    num_to_chinese,
    token_safe_prune,
    validate_skeleton_contract,
)
from reference_guard import HardReferenceGuard
from sequence_planner import SequencePlanner

from prompts_config import (
    get_v3_prompt_bundle
)

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
        candidate_count=1,
        blacklist=None,
        reference_bundle=None,
        workspace_dir=None,
        enable_promotional_tasks=False,
        isolated_task_mode=False,
        verbose=True
    ):
        self.novel_id = novel_id
        self.novel_name = novel_name
        self.total_chapters = normalize_total_chapters(total_chapters)
        self.run_autonomous_learning = run_autonomous_learning
        self.candidate_count = max(1, int(candidate_count or 1))
        self.isolated_task_mode = isolated_task_mode
        self.blacklist = blacklist or []
        self.reference_bundle = reference_bundle
        self.verbose = verbose
        self.enable_promotional_tasks = enable_promotional_tasks
        self.db_manager = db_manager or DatabaseManager()

        existing_book = self.db_manager.get_book(self.novel_id) or {}
        stored_setting = existing_book.get("genesis_json") or {}
        stored_skeleton = existing_book.get("skeleton_json") or {}
        self.setting = setting or stored_setting or {}
        self.skeleton = skeleton or stored_skeleton or {}

        if not self.setting:
            genesis = GenesisDirector()
            self.setting = genesis.generate_genesis_setting(self.novel_name)
        if not self.skeleton:
            planner = SequencePlanner()
            self.skeleton = planner.plan_novel_arc(self.setting, total_chapters=self.total_chapters)
        self._enforce_skeleton_contract()
        self.setting["audience_type"] = normalize_audience_type(self.setting.get("audience_type", "female_oriented"))
        
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
            audience_type=normalize_audience_type(self.setting.get("audience_type", "female_oriented")),
            logic_layer=DisguiseLogicAuditor,
            record_rule_feedback=not self.isolated_task_mode,
            record_sandbox_memory=not self.isolated_task_mode,
            verbose=self.verbose
        )
        self.engine.set_book_context(self.setting)
        self.engine.refresh_axioms(self.novel_id)
        main_char_data = self.setting.get("main_character", {})
        if isinstance(main_char_data, list) and len(main_char_data) > 0:
            main_char_data = main_char_data[0]
        elif not isinstance(main_char_data, dict):
            main_char_data = {}

        self.engine.main_character_name = main_char_data.get("name", "主角")

        if self.blacklist:
            print(f"🛡️ [法务挂载] 已加载 {len(self.blacklist)} 条原著禁语名单。")
            self.engine.add_auditor(PlagiarismGuard(self.blacklist))

        if self.setting.get("emotional_formula") and self.setting.get("emotional_formula") != "未知情节拉扯公式":
            print(f"🛡️ [融梗拦截挂载] 已加载原著情节防碰撞审计器。")
            self.engine.add_auditor(PlotCollisionAuditor(self.setting["emotional_formula"]))

        if "main_character" in self.setting:
            main_character = self.setting["main_character"]
            if isinstance(main_character, list) and len(main_character) > 0:
                main_character = main_character[0]
            if isinstance(main_character, dict):
                self._rehydrate_runtime_state(main_character)

        self.reference_bundle = self.reference_bundle or self.db_manager.get_reference_fingerprint_bundle(self.novel_id)
        self.reference_guard = None
        if self.reference_bundle:
            self.reference_guard = HardReferenceGuard(self.novel_id, self.reference_bundle, self.engine.vector_db)
            self.engine.attach_reference_guard(self.reference_guard)

        self.sliding_window_summary = []

    def _init_workspace(self):
        """初始化工业化目录矩阵"""
        subdirs = ["audit", "chapter", "prompt", "report", "state"]
        for sd in subdirs:
            path = os.path.join(self.workspace_dir, sd)
            if not os.path.exists(path):
                os.makedirs(path, exist_ok=True)
        print(f"🏗️ [工作空间初始化] 工业化产出矩阵已就绪: {self.workspace_dir}")

    def _enforce_skeleton_contract(self):
        """保证大纲、数据库续写状态与固定章节契约一致。"""
        expected = set(expected_chapter_indices(self.total_chapters))
        existing_chapters = self.db_manager.list_chapters_for_book(self.novel_id)
        overflow = [
            chapter.get("chapter_index")
            for chapter in existing_chapters
            if chapter.get("chapter_index") not in expected
        ]
        if overflow:
            raise RuntimeError(
                f"检测到作品 {self.novel_id} 已存在越界章节 {sorted(overflow)}；"
                f"当前短篇契约只允许 0..{self.total_chapters}。请清理旧任务或更换 book_id 后重跑。"
            )

        try:
            self.skeleton = validate_skeleton_contract(self.skeleton, self.total_chapters)
        except ValueError as exc:
            if existing_chapters or self.reference_bundle:
                raise RuntimeError(
                    f"作品 {self.novel_id} 的大纲与章节契约不一致，拒绝继续生成：{exc}"
                ) from exc

            print(f"⚠️ [章节契约] {exc}，无既有章节，正在按 0..{self.total_chapters} 重绘大纲。")
            planner = SequencePlanner()
            self.skeleton = planner.plan_novel_arc(self.setting, total_chapters=self.total_chapters)
            self.skeleton = validate_skeleton_contract(self.skeleton, self.total_chapters)

        self.novel_arc_by_index = {
            int(chapter["chapter_idx"]): chapter
            for chapter in self.skeleton.get("novel_arc", [])
        }

    def _quarantine_out_of_contract_artifacts(self):
        """把旧运行留下的 11_*.md 等越界资产移走，避免工作区继续误导人工检查。"""
        expected = set(expected_chapter_indices(self.total_chapters))
        quarantine_root = os.path.join(
            self.workspace_dir,
            "out_of_contract",
            datetime.now().strftime("%Y%m%d_%H%M%S"),
        )
        moved = []

        for folder in ("audit", "chapter", "prompt", "state"):
            folder_path = os.path.join(self.workspace_dir, folder)
            if not os.path.isdir(folder_path):
                continue
            for name in os.listdir(folder_path):
                match = re.match(r"^(\d+)_", name)
                if not match:
                    continue
                chapter_idx = int(match.group(1))
                if chapter_idx in expected:
                    continue
                src = os.path.join(folder_path, name)
                if not os.path.isfile(src):
                    continue
                dst_dir = os.path.join(quarantine_root, folder)
                os.makedirs(dst_dir, exist_ok=True)
                shutil.move(src, os.path.join(dst_dir, name))
                moved.append(os.path.join(folder, name))

        if moved:
            logger.warning(
                f"⚠️ [章节契约] 已隔离 {len(moved)} 个越界资产到 {quarantine_root}: "
                + "、".join(moved[:6])
            )

    def _write_prompt_snapshot(self, chapter_idx, title, prompt_text):
        folder = "prompt"
        prompt_path = os.path.join(self.workspace_dir, folder, f"{chapter_idx}_{title}_prompt.md")
        with open(prompt_path, "w", encoding="utf-8") as handle:
            handle.write(prompt_text)

    def _refresh_outline_report(self):
        report_path = os.path.join(self.workspace_dir, "report", "2大纲.md")
        with open(report_path, "w", encoding="utf-8") as handle:
            handle.write(f"# 创作蓝图: {self.novel_name}\n\n")
            handle.write(json.dumps(self.skeleton, ensure_ascii=False, indent=2))

    def _collect_skeleton_text(self, skeleton):
        pieces = []
        for chapter in (skeleton or {}).get("novel_arc", []):
            pieces.extend(extract_skeleton_segments(chapter))
        global_resolution = (skeleton or {}).get("global_resolution")
        if isinstance(global_resolution, str) and global_resolution.strip():
            pieces.append(global_resolution.strip())
        return "\n".join(pieces)

    def _assert_skeleton_setting_consistency(self, skeleton, stage_label):
        conflicts = detect_setting_conflicts(
            self.setting.get("world_setting", ""),
            self._collect_skeleton_text(skeleton),
        )
        if conflicts:
            raise RuntimeError(f"{stage_label} 触发题材/世界观硬闸门：{'；'.join(conflicts[:4])}")

    def _format_history_context(self, summaries, preview_mode=False):
        cleaned = [
            token_safe_prune(item.strip(), max_chars=90, head_ratio=0.85)
            for item in (summaries or [])
            if isinstance(item, str) and item.strip()
        ]
        if not cleaned:
            if preview_mode:
                return "【蓝图预演说明】：正文尚未生成，当前仅保留计划链，不把未来剧情当作既成事实。"
            return "无前情提要（开局）。"

        header = "【蓝图预演说明】：以下为计划链，仅供结构校准，不代表已发生的正文剧情。\n" if preview_mode else "【前情提要】：\n"
        label = "计划锚点" if preview_mode else "剧情进度"
        cleaned = cleaned[-2:]
        start_idx = 1
        context = header
        for offset, summary in enumerate(cleaned, start=start_idx):
            context += f"- {label} {offset}：{summary}\n"
        return context

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
        return self._format_history_context(self.sliding_window_summary[-2:], preview_mode=False)

    def run_pipeline(self):
        print(f"\n🎬 [极速流水线开启] 正在创作作品: {self.novel_name} (楔子 + 第1章至第{self.total_chapters}章)")
        try:
            self._quarantine_out_of_contract_artifacts()
            # 1. 极速生成大纲与 Prompt（已由 Phase 1 完成，此处仅确保目录存在）
            # 2. 章节创作主循环
            for chapter_idx in expected_chapter_indices(self.total_chapters):
                title = chapter_title_for_index(chapter_idx)
                chapter_type = chapter_type_for_index(chapter_idx, self.total_chapters)
                current_skeleton = self.novel_arc_by_index.get(chapter_idx) or {}
                next_skeleton = None if chapter_type == "epilogue" else self.novel_arc_by_index.get(chapter_idx + 1)
                
                # 核心资产完整性补全与检查
                prompt_path = os.path.join(self.workspace_dir, "prompt", f"{chapter_idx}_{title}_prompt.md")
                if not os.path.exists(prompt_path):
                    logger.info(f"   🩹 [资产发现] {title} 缺少 Prompt，正在触发核心自愈补全...")
                    base_seed = self._generate_chapter_seed(
                        chapter_idx=chapter_idx, 
                        chapter_type=chapter_type,
                        history_context=self.compile_history_context(),
                        chapter_skeleton=current_skeleton,
                        next_chapter_skeleton=next_skeleton
                    )
                    self._write_prompt_snapshot(chapter_idx, title, base_seed)
                else:
                    with open(prompt_path, "r", encoding="utf-8") as f:
                        base_seed = f.read()

                # 检查断点续传 (推后检查，先保证 Prompt 存在)
                existing = self.db_manager.get_chapter(self.novel_id, chapter_idx)
                if existing and existing.get("status") == "completed":
                    existing_type = existing.get("chapter_type") or ""
                    if existing_type and existing_type != chapter_type:
                        raise RuntimeError(
                            f"{title} 已完成但章节类型为 {existing_type}，当前契约要求 {chapter_type}；"
                            "拒绝跳过可能错误的章节。请清理该书旧记录后重跑。"
                        )
                    logger.info(f"   ⏩ 跳过已完成: {title}")
                    self.sliding_window_summary.append(existing.get("summary", ""))
                    continue

                logger.info(f"   🎥 正在创作: {title}...")

                # 执行三位一体一次性生成
                chapter_result = self.engine.generate_chapter(
                    novel_id=self.novel_id,
                    seed_prompt=base_seed,
                    title=title,
                    chapter_type=chapter_type,
                    chapter_index=chapter_idx,
                    skeleton_data=current_skeleton,
                    history_context=self.compile_history_context(),
                    candidate_count=self.candidate_count,
                )

                # 保存产物 (升级为工业化全矩阵存档)
                self.engine.save_industrial_artifacts(
                    book_dir=self.workspace_dir,
                    chapter_idx=chapter_idx,
                    chapter_title=title,
                    result_bundle=chapter_result
                )
                self.sliding_window_summary.append(chapter_result["summary"])
                
                # 存库
                self.db_manager.update_chapter_record(
                    book_id=self.novel_id,
                    chapter_index=chapter_idx,
                    summary=chapter_result["summary"],
                    status="completed"
                )
                self.db_manager.update_book_status(self.novel_id, status="generating", latest_chapter_index=chapter_idx)
                logger.info(f"   ✅ {title} 创作完毕。")

            self.db_manager.update_book_status(self.novel_id, status="completed", latest_chapter_index=self.total_chapters)
            
            # [全书收官] 触发工业化宣发报告
            self._run_promotional_tasks()
            
            return self.novel_id
        except Exception as e:
            print(f"❌ 流程崩溃: {str(e)}")
            raise

    def _generate_chapter_seed(
        self,
        chapter_idx,
        chapter_type,
        history_context,
        chapter_skeleton,
        next_chapter_skeleton=None,
        preview_mode=False,
        recent_plots_override=None,
    ):
        # 5. 合成最终执行 Prompt (使用 V3 统一引擎)
        actual_title = chapter_skeleton.get('title', chapter_title_for_index(chapter_idx))
        chapter_outline = str(chapter_skeleton)
        
        final_prompt = get_v3_prompt_bundle(
            idx=chapter_idx,
            total_chapters=self.total_chapters,
            title=actual_title,
            body=chapter_outline,
            setting=self.setting,
            prev_data={'title': '前一章', 'body': history_context} if history_context else None,
            next_data={'title': (next_chapter_skeleton or {}).get('title', '下一章'), 'body': str(next_chapter_skeleton or {})} if next_chapter_skeleton else None
        )
        return final_prompt



    def _register_planned_foreshadow(self, chapter_idx, chapter_skeleton):
        """把骨架里的计划伏笔提前注册，避免仅靠正文反向抽取导致漏记。"""
        if chapter_idx >= self.total_chapters:
            return

        description = str((chapter_skeleton or {}).get("foreshadowing_to_plant", "")).strip()
        if not description or description == "无":
            return

        normalized_desc = re.sub(r"\s+", "", description)
        for item in self.db_manager.list_unresolved_foreshadow_records(self.novel_id):
            existing_desc = re.sub(r"\s+", "", str(item.get("description", "")))
            if existing_desc == normalized_desc:
                return

        remaining = max(1, self.total_chapters - chapter_idx)
        target_gap = min(3, remaining)
        target_chapter = min(self.total_chapters, chapter_idx + target_gap)
        priority = "A" if target_gap >= 2 else "B"

        foreshadow_id = self.db_manager.add_foreshadow_record(
            self.novel_id,
            description,
            priority=priority,
            target_chapter=target_chapter,
        )
        self.engine.neo4j.add_foreshadow(
            self.novel_id,
            description,
            priority,
            target_chapter,
            sql_id=foreshadow_id,
        )

    def _check_and_replan(self, chapter_idx, chapter_result, chapter_skeleton):
        if chapter_idx >= self.total_chapters:
            return

        expected = chapter_skeleton.get("goal") or chapter_skeleton.get("content_plan")
        if not expected:
            acts = (chapter_skeleton or {}).get("acts", {}) or {}
            expected_parts = [
                chapter_skeleton.get("scene", ""),
                acts.get("act_1", ""),
                acts.get("act_2", ""),
                acts.get("act_3", ""),
                chapter_skeleton.get("state_transition", ""),
            ]
            expected = "；".join(part for part in expected_parts if part)
        auditor = DynamicArcAuditor(chapter_idx, expected)
        res = auditor.audit(chapter_result["content"], chapter_result["summary"])

        needs_replan = "[需重铸]" in res
        
        new_clue = chapter_result.get("new_clue")
        state_delta = chapter_result.get("state_delta", {})
        state_change_count = 0
        if isinstance(state_delta, dict):
            state_change_count += len(state_delta.get("physical_state", {}) or {})
            state_change_count += len(state_delta.get("cognitive_state", {}) or {})
            if state_delta.get("identity_mask"):
                state_change_count += 1
        
        # 移除低阈值的大纲重绘触发，仅在 auditor 判定为原子级坍塌时才重绘

        if needs_replan:
            print(f"⚠️ [大纲重铸] 检测到发生原子级剧情坍塌，正在针对未来 {self.total_chapters - chapter_idx} 章重绘蓝图...")
            planner = SequencePlanner()
            
            max_replan_retries = 3
            replan_success = False
            
            for attempt in range(max_replan_retries):
                new_skeleton = planner.replan_novel_arc(
                    genesis_setting=self.setting,
                    current_arc=self.skeleton,
                    current_idx=chapter_idx,
                    new_state=state_delta,
                    new_clue=new_clue,
                    anti_plagiarism_context=self.reference_guard.planner_constraints() if self.reference_guard else "",
                    total_chapters=self.total_chapters,
                )

                try:
                    new_skeleton = validate_skeleton_contract(new_skeleton, self.total_chapters)
                    self._assert_skeleton_setting_consistency(new_skeleton, "重铸大纲")
                except RuntimeError as exc:
                    print(f"⚠️ [题材拦截] {exc} (尝试 {attempt+1}/{max_replan_retries})，重新推演。")
                    continue
                except ValueError as exc:
                    print(f"⚠️ [章节契约拦截] {exc} (尝试 {attempt+1}/{max_replan_retries})，重新推演。")
                    continue
                
                if self.reference_guard:
                    replanned_audit = self.reference_guard.audit_outline_payload(new_skeleton)
                    if not replanned_audit.get("passed"):
                        print(f"⚠️ [法务拦截] 重铸后的大纲仍与原著过近 (尝试 {attempt+1}/{max_replan_retries})，重新推演。")
                        continue # try again
                
                # Success
                self.skeleton = new_skeleton
                self.novel_arc_by_index = {
                    int(chapter["chapter_idx"]): chapter
                    for chapter in self.skeleton.get("novel_arc", [])
                }
                self.db_manager.create_or_update_book(
                    book_id=self.novel_id,
                    title=self.novel_name,
                    genesis=self.setting,
                    skeleton=self.skeleton,
                    status="generating",
                )
                self._refresh_outline_report()
                replan_success = True
                break
                
            if not replan_success:
                print(f"❌ [重铸崩溃] 连续 {max_replan_retries} 次重铸大纲均未通过审计闸门！被迫保留旧大纲...")

    def _run_promotional_tasks(self):
        """执行宣发任务 1 & 2：生成微头条推广及吸睛标题"""
        print(f"🚀 [双重宣发引擎] 正在为《{self.novel_name}》打造独家宣发报告与吸睛标题...")
        
        # 1. 定位指令文件
        task_file_path = os.path.join(os.path.dirname(__file__), "任务 1and2")
        if not os.path.exists(task_file_path):
             task_file_path = "/Users/tang/PycharmProjects/pythonProject/API_duanpian/任务 1and2"
             
        if not os.path.exists(task_file_path):
            print(f"⚠️ [宣发异常] 未找到指令文件 '{task_file_path}'，跳过生成。")
            return

        try:
            with open(task_file_path, "r", encoding="utf-8") as f:
                task_instruction = f.read()
        except Exception as e:
            print(f"⚠️ [宣发异常] 读取指令文件失败: {e}")
            return

        # 2. 汇总全书摘要链（使用摘要以确保逻辑链完整且不超 Token）
        chapters = self.db_manager.list_chapters_for_book(self.novel_id)
        if not chapters:
            print("⚠️ [宣发异常] 未检测到任何已生成的章节资产，无法汇总内容。")
            return
            
        summary_chain = ""
        for chap in sorted(chapters, key=lambda x: x['chapter_index']):
            c_title = chap.get("title", f"第{chap['chapter_index']}章")
            c_summary = chap.get("summary", "（摘要缺失）")
            summary_chain += f"### {c_title}\n剧情梗概：{c_summary}\n\n"

        # 3. 构造工业级宣发 Prompt
        promo_prompt = f"""你是一名拥有 10 年经验的网文宣发专家，擅长捕捉爆款情绪与“开幕雷击”。
以下是刚刚完结的作品《{self.novel_name}》的全书剧情逻辑汇总：

{summary_chain}

---
请严格执行以下【宣发任务指令】：

{task_instruction}

---
【输出规范】：
- 直接输出任务 1 和任务 2 的结果。
- 严禁出现任何解释性文字或确认收到指令的废话。
"""
        # 4. 调用进化引擎的 LLM 接口
        try:
            promo_result = self.engine._llm_generate(promo_prompt, "You are a professional high-conversion web novel promoter.")
        except Exception as e:
            print(f"❌ [生成失败] 调用 LLM 失败: {e}")
            return

        # 5. 固化存档至 report 目录
        report_filename = f"宣发方案-{self.novel_name}.md"
        report_path = os.path.join(self.workspace_dir, "report", report_filename)
        
        try:
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(f"# 《{self.novel_name}》工业级全域宣发报告\n\n")
                f.write(f"> **生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"> **所属作品**：{self.novel_name}\n\n")
                f.write(promo_result)
            print(f"✨ [宣发结晶已就绪] 方案已存放于工业矩阵报告区: {report_path}")
        except Exception as e:
            print(f"❌ [存档失败] 无法写入报告文件: {e}")
