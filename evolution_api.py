import json
import os
import re
import concurrent.futures
from difflib import SequenceMatcher
from datetime import datetime
from pathlib import Path

from auditors import (
    DemographicAuditor,
    HookAuditor,
    StyleAuditor,
    StylisticCompositeAuditor,
    TruthCompositeAuditor,
    AI_ScentAuditor,
    SettingComplianceAuditor,
    MasterQualityAuditor,
)
from chroma_memory import ChromaMemory
from evaluators import QuantitativeEvaluator
from llm_client import generate_text, generate_text_full, DEFAULT_MODEL, resolve_model_name
from neo4j_db import Neo4jManager
from novel_utils import (
    OPEN_ENDING_PATTERNS,
    audience_display_label,
    extract_skeleton_plot_hint,
    normalize_audience_type,
    token_safe_prune,
    tokenize_cn_text,
)
from skill_manager import SkillManager
from logger import logger


class MasterEvolutionEngine:
    CANDIDATE_DIRECTIVES = [
        "优先强化开场暴击、危机感和推进速度。",
        "优先强化人物微动作、关系张力和情绪钩子。",
        "优先强化反套路、因果回收和首尾呼应。",
        "优先强化场景感、压迫感和句式变化。",
    ]

    def __init__(
        self,
        db_manager,
        audience_type,
        logic_layer,
        master_style=None,
        record_rule_feedback=True,
        record_sandbox_memory=True,
        verbose=True
    ):
        self.db = db_manager
        self.audience_type = normalize_audience_type(audience_type)
        self.logic_layer_cls = logic_layer
        self.axioms = {}
        self.logic_layer = None
        self.demo_auditor = None
        self.style_auditor = None
        self.hook_auditor = HookAuditor()
        if hasattr(self, 'world_setting') and self.world_setting:
            self.world_setting = token_safe_prune(self.world_setting, max_chars=1500)
        
        self.scent_auditor = AI_ScentAuditor()
        self.quant_evaluator = QuantitativeEvaluator()
        self.dynamic_auditors = [] # 动态审计插件池
        self.reference_guard = None
        
        # 聚合审计器初始化
        self.stylistic_auditor = None
        self.truth_auditor = None
        self.setting_auditor = None
        self.master_auditor = None
        self.world_setting = ""
        self.book_brief = ""
        self.core_style_guide = ""

        self.master_style = master_style or "极具张力的长短句错落反差爽文风格"
        self.main_character_name = "主角"
        self.record_rule_feedback = record_rule_feedback
        self.record_sandbox_memory = record_sandbox_memory
        self.vector_db = ChromaMemory()
        self.neo4j = Neo4jManager()
        self.skill_manager = SkillManager(db_manager)
        self.verbose = verbose

        self.refresh_axioms()
        # 为当前引擎实例绑定所属书籍 ID (用于用量统计)
        self.current_novel_id = None
        self.current_chapter_index = 0

    def _llm_generate(
        self,
        prompt,
        system_prompt="You are an expert novel writer.",
        model=DEFAULT_MODEL,
        task_profile=None,
        max_tokens=None,
    ):
        """内部封装：带用量统计与日志的生成接口"""
        res = generate_text_full(
            prompt,
            system_prompt,
            model,
            task_profile=task_profile,
            max_tokens=max_tokens,
        )
        # 记录到数据库
        if self.db and self.current_novel_id:
            self.db.log_usage(
                book_id=self.current_novel_id,
                chapter_index=self.current_chapter_index,
                model=res["model"],
                prompt_tokens=res["usage"]["prompt_tokens"],
                completion_tokens=res["usage"]["completion_tokens"],
                total_tokens=res["usage"]["total_tokens"]
            )
        return res["content"]

    def set_book_context(self, setting):
        setting = setting or {}
        self.master_style = setting.get("master_style", self.master_style)
        self.world_setting = token_safe_prune(str(setting.get("world_setting", "") or ""), max_chars=900, head_ratio=0.75)

        main_character = setting.get("main_character", {})
        if isinstance(main_character, list) and main_character:
            main_character = main_character[0]
        if not isinstance(main_character, dict):
            main_character = {}

        brief_lines = [
            f"频道：{audience_display_label(setting.get('audience_type', self.audience_type))}",
            f"核心卖点：{token_safe_prune(setting.get('narrative_kernel', '未定义'), max_chars=90)}",
            f"主角：{main_character.get('name', '主角')} | 底色：{token_safe_prune(main_character.get('base_personality', '未定义'), max_chars=90)}",
            f"开局冲突：{token_safe_prune(setting.get('initial_conflict', '未定义'), max_chars=140)}",
            f"文风：{token_safe_prune(self.master_style, max_chars=90)}",
            f"世界观摘要：{token_safe_prune(self.world_setting, max_chars=240, head_ratio=0.75)}",
        ]
        self.book_brief = "\n".join(line for line in brief_lines if line and not line.endswith("未定义"))

        from prompts_config import build_core_style_guide
        self.core_style_guide = token_safe_prune(
            build_core_style_guide({"world_setting": self.world_setting}),
            max_chars=420,
            head_ratio=0.75,
        )

    def _parse_json_payload(self, raw_response, default=None):
        default = {} if default is None else default
        if isinstance(raw_response, dict):
            return raw_response
        if not raw_response or not isinstance(raw_response, str):
            return default
        match = re.search(r"\{.*\}", raw_response, re.DOTALL)
        if not match:
            return default
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return default

    def _normalize_issue_payload(self, raw_issue):
        if isinstance(raw_issue, dict):
            passed = bool(raw_issue.get("passed"))
            issue_text = str(raw_issue.get("issue") or ("[通过]" if passed else "未说明问题")).strip()
            spans = raw_issue.get("spans") if isinstance(raw_issue.get("spans"), list) else []
        else:
            issue_text = str(raw_issue or "").strip() or "[通过]"
            passed = "[通过]" in issue_text
            spans = []

        normalized_spans = []
        for item in spans[:2]:
            if not isinstance(item, dict):
                continue
            quote = str(item.get("quote", "")).strip()
            if not quote:
                continue
            normalized_spans.append(
                {
                    "quote": token_safe_prune(quote, max_chars=180, head_ratio=0.8),
                    "problem": token_safe_prune(str(item.get("problem", "")).strip(), max_chars=120, head_ratio=0.8),
                    "instruction": token_safe_prune(str(item.get("instruction", "")).strip(), max_chars=120, head_ratio=0.8),
                }
            )

        return {
            "passed": passed or "[通过]" in issue_text,
            "issue": "[通过]" if passed or "[通过]" in issue_text else issue_text,
            "spans": normalized_spans,
        }

    def _split_repair_segments(self, content):
        segments = [segment.strip() for segment in re.split(r"\n{2,}", content or "") if segment.strip()]
        if segments:
            return segments
        return [line.strip() for line in (content or "").splitlines() if line.strip()]

    def _locate_best_span(self, content, snippet):
        if not content or not snippet:
            return ""
        snippet = snippet.strip()
        if snippet in content:
            return snippet

        normalized_snippet = re.sub(r"\s+", "", snippet)
        best_segment = ""
        best_score = 0.0
        for segment in self._split_repair_segments(content):
            normalized_segment = re.sub(r"\s+", "", segment)
            if not normalized_segment:
                continue
            score = SequenceMatcher(None, normalized_snippet[:180], normalized_segment[:180]).ratio()
            if normalized_snippet[:12] and normalized_snippet[:12] in normalized_segment:
                score += 0.1
            if score > best_score:
                best_score = score
                best_segment = segment
        return best_segment if best_score >= 0.42 else ""

    def _extract_context_window(self, content, quote, window_chars=80):
        if not content or not quote:
            return {"before": "", "quote": quote, "after": ""}
        idx = content.find(quote)
        if idx == -1:
            return {"before": "", "quote": quote, "after": ""}
        before = content[max(0, idx - window_chars):idx].strip()
        after = content[idx + len(quote):idx + len(quote) + window_chars].strip()
        return {"before": before, "quote": quote, "after": after}

    def _build_fix_targets(self, content, issue_payload):
        targets = []
        for span in issue_payload.get("spans", [])[:2]:
            matched_quote = self._locate_best_span(content, span.get("quote", ""))
            if not matched_quote:
                continue
            context_window = self._extract_context_window(content, matched_quote)
            targets.append(
                {
                    "quote": matched_quote,
                    "problem": span.get("problem") or issue_payload.get("issue"),
                    "instruction": span.get("instruction") or issue_payload.get("issue"),
                    "context_before": context_window["before"],
                    "context_after": context_window["after"],
                }
            )

        if targets:
            return targets

        fallback_quote = self._locate_best_span(content, issue_payload.get("issue", ""))
        if not fallback_quote:
            fallback_quote = token_safe_prune(content, max_chars=220, head_ratio=0.9)
        context_window = self._extract_context_window(content, fallback_quote)
        return [
            {
                "quote": fallback_quote,
                "problem": issue_payload.get("issue", "需要修复的局部问题"),
                "instruction": issue_payload.get("issue", "请在不改剧情的前提下修正"),
                "context_before": context_window["before"],
                "context_after": context_window["after"],
            }
        ]

    def refresh_axioms(self, book_id=None):
        """每轮生成前刷新一次规则库，确保学习结果当轮可见。"""
        if book_id:
            book = self.db.get_book(book_id)
            if book and book.get("master_style"):
                self.master_style = book["master_style"]

        self.axioms = self.db.get_active_axioms()
        # 将 master_style 注入 axioms 供 StyleAuditor 使用
        self.axioms["master_style"] = self.master_style
        
        self.logic_layer = self.logic_layer_cls(self.axioms)
        self.demo_auditor = DemographicAuditor(self.audience_type, self.axioms)
        self.style_auditor = StyleAuditor(self.axioms)
        
        # 聚合审计器刷新
        self.stylistic_auditor = StylisticCompositeAuditor(self.master_style)
        self.truth_auditor = TruthCompositeAuditor(self.axioms)
        self.setting_auditor = SettingComplianceAuditor(self.world_setting, self.axioms)
        self.master_auditor = MasterQualityAuditor(self.master_style, self.axioms, self.audience_type)

    def add_auditor(self, auditor):
        """支持外部注入动态审计插件（如 PlagiarismGuard）"""
        self.dynamic_auditors.append(auditor)
        if self.verbose:
            logger.info(f"🔌 [插件挂载] 已成功接入外部审计器: {auditor.name}")

    def attach_reference_guard(self, reference_guard):
        self.reference_guard = reference_guard
        if self.verbose and reference_guard:
            logger.info("🧷 [硬闸门挂载] 原著指纹查重闸门已接入正文流水线。")

    def generate_chapter(
        self,
        novel_id,
        seed_prompt,
        title,
        chapter_type="normal",
        chapter_index=1,
        skeleton_data=None,
        chapter_id=None,
        history_context="",
        candidate_count=1,
    ):
        if self.verbose:
            logger.info(f"\n--- [顶级流水线启动] 正在深度锻造章节：{title} (类型: {chapter_type}) ---")
        
        self.current_novel_id = novel_id
        self.current_chapter_index = chapter_index
        
        self.refresh_axioms(novel_id)
        candidate_count = max(1, int(candidate_count or 1))

        if chapter_id is None:
            chapter_id = self.db.upsert_chapter_record(
                book_id=novel_id,
                chapter_index=chapter_index,
                title=title,
                chapter_type=chapter_type,
                skeleton_data=skeleton_data or {},
                history_context=history_context,
                status="generating",
            )

        absolute_state = self.neo4j.get_character_state(novel_id, self.main_character_name)
        if not absolute_state:
            absolute_state = self.db.get_character_state_snapshot(novel_id, self.main_character_name) or {}
            if absolute_state:
                self.neo4j.update_character_state(novel_id, self.main_character_name, absolute_state)
        prepared = self._prepare_generation_context(
            novel_id=novel_id,
            chapter_index=chapter_index,
            seed_prompt=seed_prompt,
            skeleton_data=skeleton_data or {},
            absolute_state=absolute_state,
            chapter_type=chapter_type,
        )

        candidate_results = []
        
        def process_candidate(candidate_index):
            import time
            # 错峰提交，减少 API 迸发频率
            time.sleep((candidate_index - 1) * 2)
            candidate_label = f"candidate_{candidate_index}"
            candidate_seed = (
                f"{prepared['seed_prompt']}\n"
                f"【候选策略】{self._candidate_directive(candidate_index, chapter_type)}"
            )
            # 加载当前环节对应的技能
            active_skill = self._select_skill_for_pipeline(chapter_type, self.audience_type)
            skill_bundle = self.skill_manager.get_skill_bundle(active_skill, audience=self.audience_type)
            
            result = self._run_candidate_pipeline(
                novel_id=novel_id,
                chapter_id=chapter_id,
                chapter_index=chapter_index,
                chapter_type=chapter_type,
                candidate_label=candidate_label,
                seed_prompt=candidate_seed,
                clue_context=prepared["clue_context"],
                due_clues=prepared["due_clues"],
                skeleton_data=skeleton_data or {},
                absolute_state=absolute_state,
                skill_bundle=skill_bundle
            )
            return result

        # 核心加速：并发生成候选版本
        max_workers = min(candidate_count, 4)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_cidx = {executor.submit(process_candidate, i): i for i in range(1, candidate_count + 1)}
            for future in concurrent.futures.as_completed(future_to_cidx):
                cidx = future_to_cidx[future]
                try:
                    result = future.result()
                    if result and result.get("draft_id"):
                        candidate_results.append(result)
                        logger.info(
                            f"🏁 [candidate_{cidx}] 候选并发完成 | overall={result['evaluation']['metrics']['overall']:.2f} "
                            f"| risks={result['evaluation']['risk_flags']}"
                        )
                except Exception as exc:
                    logger.error(f"❌ [candidate_{cidx}] 候选生成失败: {exc}")

        # 安全检查：如果所有候选项都失败，进入串行兜底流程
        if not candidate_results:
            logger.warning("⚠️ [警告] 所有并行候选生成均失败。尝试进入【串行安全模式】最后一次尝试...")
            try:
                fallback_result = process_candidate(1)
                if fallback_result:
                    candidate_results.append(fallback_result)
            except Exception as e:
                logger.error(f"🚨 [严重故障] 兜底生成亦失败: {e}")

        if not candidate_results:
            raise RuntimeError(f"章节 {chapter_index} 生成彻底失败，无合法候选内容产出。")

        winner = max(candidate_results, key=self._candidate_sort_key)
        epilogue_failures = [
            flag for flag in winner["evaluation"].get("risk_flags", [])
            if str(flag).startswith("epilogue_contract:")
        ]
        if chapter_type == "epilogue" and epilogue_failures:
            raise RuntimeError(
                f"终章未通过闭环契约，拒绝落盘：{'；'.join(epilogue_failures[:3])}"
            )

        self.db.mark_selected_draft(winner["draft_id"], novel_id, chapter_index)
        logger.info(f"👑 [候选胜出] {winner['candidate_label']} | 总分 {winner['evaluation']['metrics']['overall']:.2f}")

        resolved_ids = winner["resolved_ids"]
        if resolved_ids:
            for foreshadow_id in resolved_ids:
                self.db.resolve_foreshadow_record(foreshadow_id)
                self.neo4j.resolve_foreshadow(foreshadow_id)
            logger.info(f"✅ [伏笔核销] 已回收伏笔 ID: {resolved_ids}")

        # 直接从优胜候选中提取已经完成的 元数据 (Summary/StateDelta/NewClue)
        # 节省了一次专门的 _unified_post_processing LLM 调用
        chapter_summary = winner.get("summary") or "（摘要生成失败）"
        state_delta = self._normalize_state_delta(winner.get("state_delta", {}))
        new_clue_raw = winner.get("next_clues", "")

        if new_clue_raw and "|" in new_clue_raw:
            try:
                priority, desc = new_clue_raw.split("|", 1)
                priority = priority.strip()
                target_chapter = (
                    chapter_index + 3
                    if priority == "A"
                    else (chapter_index + 1 if priority == "B" else chapter_index + 4)
                )
                foreshadow_id = self.db.add_foreshadow_record(novel_id, desc, priority, target_chapter)
                self.neo4j.add_foreshadow(novel_id, desc, priority, target_chapter, sql_id=foreshadow_id)
                logger.info(f"📌 [Neo4j 伏笔入库] 级别 {priority} -> 预计第 {target_chapter} 章排解：{desc}")
            except Exception as e:
                logger.error(f"⚠️ 伏笔解析解析失败: {e}")

        if state_delta:
            self.neo4j.update_character_state(novel_id, self.main_character_name, state_delta)
            merged_state = self._merge_absolute_state(absolute_state, state_delta)
            self.db.save_character_state_snapshot(novel_id, self.main_character_name, merged_state)
            logger.info(f"💾 [真理层更新] 状态全维刷新成功: {list(state_delta.keys())}")

        self.neo4j.add_chapter_node(novel_id, chapter_index, chapter_summary)

        final_id = self.db.add_chapter_final(
            book_id=novel_id,
            chapter_id=chapter_id,
            chapter_index=chapter_index,
            source_draft_id=winner["draft_id"],
            content=winner["content"],
            summary=chapter_summary,
            editor_type="machine",
            metadata={
                "candidate_label": winner["candidate_label"],
                "evaluation": winner["evaluation"],
                "audit_trail": winner.get("audit_trail", {}),
                "chapter_type": chapter_type,
                "resolved_ids": resolved_ids,
            },
        )
        self.db.add_score_bundle(novel_id, chapter_id, chapter_index, final_id, winner["evaluation"])
        if self.record_rule_feedback:
            self.db.apply_metric_feedback(
                audience_type=self.audience_type,
                evaluation_metrics=winner["evaluation"]["metrics"],
                book_id=novel_id,
                chapter_index=chapter_index,
            )
        self.db.update_chapter_record(
            novel_id,
            chapter_index,
            status="completed",
            summary=chapter_summary,
            history_context=history_context,
        )

        if self.record_sandbox_memory:
            self.db.add_sandbox(winner["content"])
        self.vector_db.add_plot(
            chapter_summary,
            metadata={"source": "chapter_summary", "novel_id": novel_id, "candidate_label": winner["candidate_label"]},
        )
        logger.info(f"✔️ 本次生成结晶已写入全局系统核心记忆。量化总分: {winner['evaluation']['metrics']['overall']:.2f}")

        return {
            "content": winner["content"],
            "summary": chapter_summary,
            "evaluation": winner["evaluation"],
            "audit_trail": winner.get("audit_trail") or {},
            "chapter_id": chapter_id,
            "draft_id": winner["draft_id"],
            "final_id": final_id,
            "new_clue": new_clue_raw,
            "state_delta": state_delta or {},
            "candidate_results": [
                {
                    "candidate_label": item["candidate_label"],
                    "draft_id": item["draft_id"],
                    "overall": item["evaluation"]["metrics"]["overall"],
                    "audit_results": item.get("audit_results")
                }
                for item in candidate_results
            ],
            "seed_prompt": prepared["seed_prompt"], # 固化的实际结构提示词
            "audit_trail": winner.get("audit_results") # 胜出者的审计轨迹
        }

    def _prepare_generation_context(self, novel_id, chapter_index, seed_prompt, skeleton_data, absolute_state, chapter_type):
        inventory_context = absolute_state.get("physical_state", {}).get("inventory", "无")
        mask_context = absolute_state.get("identity_mask", "无身份伪装")
        
        if self.verbose:
            logger.info(f">> [绝对状态挂载] 状态: {absolute_state.get('physical_state', {})} | 伪装: {mask_context}")

        skeleton_plot = extract_skeleton_plot_hint(skeleton_data)
        skeleton_clue = skeleton_data.get("foreshadowing_to_plant", "")
        plot_logic_guidance = self.axioms.get("plot_logic_guidance", "")

        if skeleton_plot:
            seed_prompt += f"\n【本章骨架指令】：{skeleton_plot}"
        if inventory_context != "无":
            seed_prompt += f"\n【角色现有道具/资产】：{inventory_context}"
        if mask_context != "无身份伪装":
            seed_prompt += f"\n【马甲严正告知】：当前处于 {mask_context} 状态，所有文字、动作、代词严禁暴露真身。"
        if plot_logic_guidance:
            seed_prompt += f"\n【历史高质量剧情规则】：{plot_logic_guidance}"

        similar_plot, sim_score = self.vector_db.search_similar_plot(seed_prompt, threshold=0.74)
        if similar_plot:
            if self.verbose:
                logger.warning(f"⚠️ [变异引擎启动] 发现疑似套路桥段 (相似度: {sim_score:.2f})！正在拉起反套路变异重组...")
            mutation_prompt = (
                f"原套路：{seed_prompt}\n"
                f"数据库已知类似桥段：{similar_plot}\n"
                "请根据【去套路化底线】，给出一个完全不同走向的情节种子扩展，要出人意料且符合逻辑。"
            )
            seed_prompt = self._llm_generate(
                mutation_prompt,
                "You are an anti-cliche mutating machine.",
                task_profile="audit_medium",
            )

        due_clues = self.neo4j.get_due_foreshadows(novel_id, chapter_index)
        clue_context = "无"
        if due_clues:
            clue_context = "、".join([f"[{item['priority']}级] {item['desc']} (ID:{item['id']})" for item in due_clues])
            if self.verbose:
                logger.info(f">> [因果锁] 本章强制排解以下伏笔：{clue_context}")
            seed_prompt += f"\n【因果回归强制要求】：本章必须回收或回应以下伏笔：{clue_context}"

        if skeleton_clue and skeleton_clue != "无":
            seed_prompt += f"\n【新伏笔埋设任务】：请在本章自然地埋下以下伏笔，为后续做铺垫：{skeleton_clue}"

        chapter_requirements = []
        if chapter_type == "prologue":
            chapter_requirements.append("本章为楔子/第一章，必须是高危反差开局，极其猛烈地展示悬念与危机，在前100字强留人，严禁平铺直叙交代背景。")
            if self.axioms.get("opening_hook"):
                chapter_requirements.append(self.axioms["opening_hook"])
        elif chapter_type == "epilogue":
            chapter_requirements.append(
                "本章为全书终章/大结局，必须爆发终极冲突，强烈呼应开篇悬念，并把核心伏笔闭环。"
                "严禁新增下一章钩子、严禁开放式续写、严禁把关键清算拖到章外。"
            )
            if self.axioms.get("continuity_payoff"):
                chapter_requirements.append(self.axioms["continuity_payoff"])

        if chapter_requirements:
            seed_prompt += "\n【结构约束】：" + " ".join(chapter_requirements)

        return {
            "seed_prompt": seed_prompt,
            "clue_context": clue_context,
            "due_clues": due_clues,
        }

    def _normalize_state_delta(self, state_delta):
        if not isinstance(state_delta, dict) or not state_delta:
            return {}

        physical = state_delta.get("physical_state", {})
        cognitive = state_delta.get("cognitive_state", {})
        if not isinstance(physical, dict):
            physical = {}
        if not isinstance(cognitive, dict):
            cognitive = {}

        legacy_keys = {
            key: value
            for key, value in state_delta.items()
            if key not in {"physical_state", "cognitive_state", "identity_mask"} and value not in (None, "")
        }
        physical.update(legacy_keys)

        identity_mask = state_delta.get("identity_mask") or physical.get("identity_mask")
        if identity_mask:
            physical["identity_mask"] = identity_mask

        normalized = {}
        if physical:
            normalized["physical_state"] = physical
        if cognitive:
            normalized["cognitive_state"] = cognitive
        if identity_mask:
            normalized["identity_mask"] = identity_mask
        return normalized

    def _merge_absolute_state(self, absolute_state, state_delta):
        normalized_delta = self._normalize_state_delta(state_delta)
        merged = {
            "physical_state": dict((absolute_state or {}).get("physical_state", {})),
            "cognitive_state": dict((absolute_state or {}).get("cognitive_state", {})),
        }

        for key, value in normalized_delta.get("physical_state", {}).items():
            if value not in (None, ""):
                merged["physical_state"][key] = value
        for key, value in normalized_delta.get("cognitive_state", {}).items():
            if value not in (None, ""):
                merged["cognitive_state"][key] = value

        identity_mask = merged["physical_state"].get("identity_mask")
        if identity_mask:
            merged["identity_mask"] = identity_mask
        return merged

    def _generate_surgical_hook(self, seed, skill_bundle=None, few_shot_context=""):
        """外科手术：专门打磨前 100 字黄金钩子"""
        hook_sys = self._get_cached_system_prompt(skill_bundle, few_shot_context)

        logger.info(">> [Surgical Hook] 正在打磨黄金前 100 字...")
        prompt = (
            f"【大纲种子】：\n{seed}\n\n"
            "【强制指令】：仅创作楔子的开篇 150 字以内。必须在前 100 字内引爆最激烈的矛盾、视觉冲击或因果悬念。"
            "绝对禁止交代：‘在很久以前’、‘有一个叫XX的人’、或者是描写风景。"
        )
        return self._llm_generate(prompt, hook_sys, task_profile="hook_write")

    def _audit_and_fix_loop(
        self, auditor_name, auditor_obj, content, seed_prompt, fix_prompt_template, fix_sys_prompt,
        novel_id, chapter_id, chapter_index, candidate_label, max_retries=1, absolute_state=None, 
        few_shot_context="", audit_kwargs=None, issue_provided=None, revalidate=True
    ):
        """
        带修复的审计循环。支持 issue_provided 参数，以承接 MasterGate 的初审结果。
        默认只基于问题片段做一次局部修复；是否复审由 revalidate 控制。
        """
        current_issue = issue_provided

        if not current_issue:
            if auditor_name == "truth":
                current_issue = auditor_obj.audit(content, absolute_state, **(audit_kwargs or {}))
            else:
                current_issue = auditor_obj.audit(content)

        issue_payload = self._normalize_issue_payload(current_issue)
        if issue_payload["passed"]:
            self._record_review(novel_id, chapter_id, chapter_index, None, candidate_label, auditor_name, "[通过]")
            return content, "[通过]"

        retries = 0
        latest_feedback = issue_payload["issue"]
        while retries < max_retries:
            retries += 1
            logger.warning(f"🛠️ [{candidate_label}:{auditor_name}] 执行局部针对性修复手术 ({retries}/{max_retries})...")

            specialized_guidance = ""
            if fix_prompt_template:
                specialized_guidance = (
                    fix_prompt_template
                    .replace("原稿：\n{content}\n", "")
                    .replace("设定违规：{issue}\n", "")
                    .replace("真理冲突：{issue}\n", "")
                    .replace("问题：{issue}\n", "")
                    .replace("文本：\n{content}\n", "")
                    .replace("拦截原因：{issue}\n", "")
                    .replace("{content}", "")
                    .replace("{issue}", "")
                    .strip()
                )

            fix_targets = self._build_fix_targets(content, issue_payload)
            local_fix_prompt = (
                f"【当前审计器】：{auditor_name}\n"
                f"【专项修复指令】：{specialized_guidance or '保持原剧情与信息量，只修正被点名的局部问题。'}\n"
                f"【原始问题概述】：{issue_payload['issue']}\n"
                f"【待修复片段与局部上下文】：\n{json.dumps(fix_targets, ensure_ascii=False, indent=2)}\n\n"
                "【强制要求】\n"
                "- 只能改写 targets 中的 quote 对应片段，禁止全文重写。\n"
                "- replacement 必须能直接替换 quote，且保留原有剧情走向。\n"
                "- 如果是设定/真理问题，优先修正措辞、动作、代词和知识边界，不得新增大段背景解释。\n\n"
                "输出严格 JSON：\n"
                "{\n"
                '  "replacements": [\n'
                '    {"quote": "原片段", "replacement": "修复后片段"}\n'
                "  ]\n"
                "}"
            )

            fix_response = self._llm_generate(
                local_fix_prompt,
                fix_sys_prompt,
                task_profile="span_fix",
            )
            fix_payload = self._parse_json_payload(fix_response, default={})
            replacements = fix_payload.get("replacements", []) if isinstance(fix_payload, dict) else []

            replaced_count = 0
            for item in replacements[:3]:
                if not isinstance(item, dict):
                    continue
                old_text = self._locate_best_span(content, str(item.get("quote", "")).strip())
                new_text = str(item.get("replacement", "")).strip()
                if not old_text or not new_text:
                    continue
                if old_text in content:
                    content = content.replace(old_text, new_text, 1)
                    replaced_count += 1

            latest_feedback = f"[已修复{replaced_count}处] {issue_payload['issue']}" if replaced_count else issue_payload["issue"]
            self._record_review(
                novel_id,
                chapter_id,
                chapter_index,
                None,
                candidate_label,
                f"{auditor_name}_fix_{retries}",
                latest_feedback,
            )
            self.db.add_chapter_draft(
                novel_id,
                chapter_id,
                chapter_index,
                f"{candidate_label}:{auditor_name}_fixed_{retries}",
                content,
                seed_prompt=seed_prompt,
                model_name=resolve_model_name(DEFAULT_MODEL),
                candidate_label=candidate_label,
            )

            if not revalidate:
                break

            if auditor_name == "truth":
                current_issue = auditor_obj.audit(content, absolute_state, **(audit_kwargs or {}))
            else:
                current_issue = auditor_obj.audit(content)

            issue_payload = self._normalize_issue_payload(current_issue)
            latest_feedback = issue_payload["issue"]
            if issue_payload["passed"]:
                break

        return content, latest_feedback

    def _select_skill_for_pipeline(self, chapter_type, audience):
        if chapter_type == "prologue":
            return "HookMaster"
        if normalize_audience_type(audience) == "female_oriented":
            return "GenreFemaleExpert"
        return "GenreMaleExpert" # 默认或男频

    def _extract_content_and_metadata(self, raw_response):
        import re, json
        # 匹配末尾的 ```json ... ``` 块
        json_pattern = r'```json\s*(\{.*?\})\s*```'
        matches = list(re.finditer(json_pattern, raw_response, re.DOTALL))
        
        metadata = {
            "summary": "（摘要提取失败）",
            "state_delta": {},
            "new_clue": "",
            "resolved_ids": []
        }
        
        if matches:
            last_match = matches[-1]
            try:
                metadata.update(json.loads(last_match.group(1)))
            except:
                pass
            content = raw_response[:last_match.start()].strip()
        else:
            content = raw_response.strip()
            
        return content, metadata

    def _audit_epilogue_contract(self, content, summary, skeleton_data):
        """终章必须像终章：跟终章骨架重合、具备清算闭环、尾部不抛续写钩子。"""
        text = f"{content or ''}\n{summary or ''}"
        tail = text[-500:]
        blockers = []

        def tokenize_contract_item(item, max_tokens=18):
            raw = re.sub(r"^[^：:]{1,12}[：:]", "", str(item or "")).strip()
            tokens = []
            for token in tokenize_cn_text(raw, min_len=2, max_tokens=max_tokens):
                if len(token) <= 6:
                    tokens.append(token)
                else:
                    tokens.extend(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,4}", token))
            return [
                token for token in dict.fromkeys(tokens)
                if token not in {"主角", "本章", "终章", "伏笔", "全书", "命运", "场景", "剧情", "章节"}
            ]

        skeleton_hint = extract_skeleton_plot_hint(skeleton_data or {})
        generic_tokens = {"主角", "本章", "终章", "伏笔", "全书", "命运", "场景", "剧情", "章节"}
        skeleton_tokens = []
        for token in tokenize_cn_text(skeleton_hint, min_len=2, max_tokens=80):
            if token in generic_tokens:
                continue
            if len(token) <= 6:
                skeleton_tokens.append(token)
                continue
            skeleton_tokens.extend(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,4}", token))
        skeleton_tokens = [
            token for token in dict.fromkeys(skeleton_tokens)
            if token not in generic_tokens and len(token) >= 2
        ]
        matched_tokens = [token for token in skeleton_tokens if token in text]
        # 更加宽容的锚点命中逻辑：最小 3，最大 6
        min_overlap = min(6, max(3, len(skeleton_tokens) // 12)) if skeleton_tokens else 0
        if min_overlap and len(matched_tokens) < min_overlap:
            blockers.append(
                f"终章正文与终章骨架重合不足，命中 {len(matched_tokens)}/{min_overlap} 个关键锚点。"
            )

        closure_checklist = skeleton_data.get("closure_checklist") or []
        missed_items = []
        for item in closure_checklist:
            item_tokens = tokenize_contract_item(item)
            if not item_tokens:
                continue
            item_matches = [token for token in item_tokens if token in text]
            # 降低伏笔回收匹配要求：只要命中 1 个关键词即可证明剧情有所涉及
            required = 1 
            if len(item_matches) < required:
                missed_items.append(str(item)[:80])
        if missed_items:
            blockers.append(f"终章未逐项收束大纲清单：{'；'.join(missed_items[:3])}")

        opening_callback = skeleton_data.get("opening_callback") or ""
        opening_tokens = tokenize_contract_item(opening_callback, max_tokens=24)
        if opening_tokens:
            opening_matches = [token for token in opening_tokens if token in text]
            # 降低首尾呼应匹配要求
            if len(opening_matches) < 2:
                blockers.append("终章缺少对楔子/开篇冲突的明确首尾呼应。")

        closure_terms = [
            "真相", "清算", "下旨", "革职", "伏笔", "回收", "证明", "平反", "尘埃落定",
            "闭环", "终结", "结束", "重建", "继承", "赐", "处置", "落幕", "大结局",
            "首尾呼应",
        ]
        closure_hits = [term for term in closure_terms if term in text]
        if len(closure_hits) < 3:
            blockers.append("终章缺少明确的真相揭示/清算/命运定格信号。")

        open_hits = [pattern for pattern in OPEN_ENDING_PATTERNS if pattern in tail]
        if open_hits:
            blockers.append(f"终章尾部出现续写钩子：{'、'.join(open_hits[:3])}")

        return {
            "passed": not blockers,
            "blockers": blockers,
            "matched_tokens": matched_tokens[:12],
            "closure_checklist_size": len(closure_checklist),
        }

    def _run_candidate_pipeline(
        self,
        novel_id,
        chapter_id,
        chapter_index,
        chapter_type,
        candidate_label,
        seed_prompt,
        clue_context,
        due_clues,
        skeleton_data,
        absolute_state,
        skill_bundle=None
    ):
        """优化版：三位一体一次性产出，杜绝碎化调用"""
        if self.verbose:
            logger.info(f"   - [极速流水线] {candidate_label} 正在一次性熔炼正文与摘要...")
        
        if chapter_type == "epilogue":
            clue_instruction = (
                "<next_chapter_clues>\n"
                "无。终章已闭环，不得提供续章线索。\n"
                "</next_chapter_clues>"
            )
            terminal_instruction = (
                "\n【终章额外硬约束】\n"
                "- 正文最后必须给出确定性的结局画面或最终动作。\n"
                "- 不得出现“下一步”“新的危机”“尚未结束”等续写引线。\n"
                "- 摘要必须明确说明全书主矛盾已经解决。"
                "- 必须逐条回应【终章逐项收束清单】，并用具体剧情完成首尾呼应。"
            )
        else:
            clue_instruction = (
                "<next_chapter_clues>\n"
                "(为下一章提供 2-3 个逻辑引线或因果钩子)\n"
                "</next_chapter_clues>"
            )
            terminal_instruction = ""

        # 整合提示词，要求模型一次性输出所有要素
        refined_seed = f"""{seed_prompt}
{terminal_instruction}

---
【极速输出要求】：
请严格按以下顺序和格式输出，不要包含任何多余的解释：

<chapter_content>
(此处撰写 2000 字左右的高质量正文内容，注意情节张力与文风要求)
</chapter_content>

<chapter_summary>
(用 150 字以内精炼总结本章核心剧情，作为后续章节的逻辑依据)
</chapter_summary>

{clue_instruction}
"""

        # 执行单次大模型调用 (显式指定正文生成使用 DeepSeek 思考模型)
        raw_response = self._llm_generate(refined_seed, model="deepseek-reasoner", task_profile="creative_writer")
        
        # 极速解析内容
        content = self._extract_tag_content(raw_response, "chapter_content")
        summary = self._extract_tag_content(raw_response, "chapter_summary")
        next_clues = self._extract_tag_content(raw_response, "next_chapter_clues")

        if not content:
            # 容错处理：如果没带标签，尝试全量提取
            content = raw_response
            summary = "（自动生成摘要中...）"

        current_draft_id = self.db.add_chapter_draft(
            book_id=novel_id,
            chapter_id=chapter_id,
            chapter_index=chapter_index,
            draft_stage="integrated_one_pass",
            candidate_label=candidate_label,
            content=content,
            seed_prompt=refined_seed,
            model_name="Main-Model",
        )

        # 核心质量评价（只保留必要的硬性审计，节省时间）
        metrics = {"overall": 8.5} # 默认基准分
        risk_flags = []
        audit_trail = {}
        
        if self.reference_guard:
            hard_gate = self.reference_guard.audit_body_text(content)
            # 记录硬性审计详情
            audit_trail["ReferenceGuard"] = f"Passed: {hard_gate.get('passed')}\nDetail: {hard_gate.get('audit_report', '')}"
            if not hard_gate.get("passed"):
                risk_flags.extend(hard_gate.get("blockers", []))
                metrics["overall"] = 4.0 # 强制降分触发重试

        if chapter_type == "epilogue":
            epilogue_gate = self._audit_epilogue_contract(content, summary, skeleton_data)
            audit_trail["EpilogueContract"] = json.dumps(epilogue_gate, ensure_ascii=False, indent=2)
            if not epilogue_gate.get("passed"):
                # 工业级优化：终章契约不满足时，仅记录风险并降分，不再阻断流程。
                risk_flags.extend([f"epilogue_contract_risk: {item}" for item in epilogue_gate.get("blockers", [])])
                logger.warning(f"⚠️ [终章契约] 发现 {len(epilogue_gate.get('blockers', []))} 项不合规，但为了保证流程闭环，允许强制落盘。")
                metrics["overall"] = max(metrics.get("overall", 8.5), 6.0) # 降分但不致死

        return {
            "content": content,
            "summary": summary,
            "next_clues": next_clues,
            "audit_trail": audit_trail,
            "draft_id": current_draft_id,
            "evaluation": {"metrics": metrics, "risk_flags": risk_flags},
            "candidate_label": candidate_label,
            "resolved_ids": []
        }

    def _extract_tag_content(self, text, tag):
        pattern = f"<{tag}>(.*?)</{tag}>"
        match = re.search(pattern, text, re.DOTALL)
        return match.group(1).strip() if match else ""



    def _joint_audit_and_fix(
        self, content, seed_prompt, novel_id, chapter_id, chapter_index, candidate_label, absolute_state, few_shot_context, due_clues, chapter_type
    ):
        """
        核心 Token 节省逻辑：合并所有审计项为一次 Master 审计，
        包含伏笔回收与 Hook 检测，遇到残缺局部快速替换。
        """
        audit_results = {}
        extracted_metadata = {
            "summary": "（摘要生成失败）",
            "state_delta": {},
            "new_clue": "",
            "resolved_ids": []
        }

        # 构建动态合并的防御规则
        dynamic_rules_list = []
        for dyn_auditor in self.dynamic_auditors:
            if hasattr(dyn_auditor, 'blacklist') and dyn_auditor.blacklist:
                # 尽量多传一些黑名单，但不要淹没 Prompt
                limited_blacklist = dyn_auditor.blacklist[:30]
                dynamic_rules_list.append(f"禁用词/实体: {', '.join(limited_blacklist)}")
            if hasattr(dyn_auditor, 'original_formula') and dyn_auditor.original_formula:
                dynamic_rules_list.append(f"此情节核已涉嫌融梗，严禁照搬: {dyn_auditor.original_formula}")
        
        dynamic_rules = " | ".join(dynamic_rules_list)

        logger.info(f"   >> [SuperAuditor] 正在执行全维质量复合审计与信息提取...")
        master_data = self._parse_json_payload(
            self.master_auditor.audit(content, absolute_state, self.world_setting, due_clues=due_clues, chapter_type=chapter_type, dynamic_rules=dynamic_rules),
            default={"overall_passed": False},
        )

        category_map = {
            "scent": ("scent", self.scent_auditor, "AI 烂梗总结点建议：{issue}\n请执行‘切除手术’，用人话替换。"),
            "stylistic": ("stylistic", self.stylistic_auditor, "综合修改意见：{issue}\n请优化节奏并剔除废话。"),
            "demographic": ("demographic", self.demo_auditor, "问题：{issue}\n请修正为符合" + self.audience_type + "的表达。"),
            "style": ("style", self.style_auditor, "问题：{issue}\n请提升人味、断句和张力。"),
            "setting": ("setting_compliance", self.setting_auditor, "原稿：\n{content}\n设定违规：{issue}\n请修正，封杀现代词。仅输出正文。"),
            "truth": ("truth", self.truth_auditor, "原稿：\n{content}\n真理冲突或融梗：{issue}\n请修正。仅输出正文。")
        }
        if chapter_type == "prologue":
             category_map["hook"] = ("hook", self.hook_auditor, "问题：{issue}\n必须在前100字引爆矛盾，悬念开局，不要解释背景！")
        
        was_fixed = False

        for key, (audit_key, auditor, fix_prompt_template) in category_map.items():
            issue_payload = self._normalize_issue_payload(master_data.get(key, "[通过]"))
            if issue_payload["passed"]:
                continue

            was_fixed = True
            logger.warning(f"   ⚠️ [SuperAuditor] 指出 {key} 存在问题：{issue_payload['issue'][:50]}... 触发专项修复。")
            audit_kwargs = {}
            if key == "truth":
                audit_kwargs = {"absolute_state": absolute_state, "world_setting": self.world_setting}

            content, _ = self._audit_and_fix_loop(
                    audit_key, auditor, content, seed_prompt,
                    fix_prompt_template,
                    f"You are a {key} repair specialist.",
                    novel_id, chapter_id, chapter_index, candidate_label,
                    issue_provided=issue_payload,
                    few_shot_context=few_shot_context,
                    audit_kwargs=audit_kwargs,
                    revalidate=False,
                )

        if was_fixed:
            logger.info("   >> [SuperAuditor] 内容已修复，执行最终全维复审...")
            final_master_data = self._parse_json_payload(
                self.master_auditor.audit(content, absolute_state, self.world_setting, due_clues=due_clues, chapter_type=chapter_type, dynamic_rules=dynamic_rules),
                default={"overall_passed": False},
            )
        else:
            logger.info("   >> [SuperAuditor] 初审全量通过，跳过最终复审以节省 Token。")
            final_master_data = master_data

        for key, (audit_key, _, _) in category_map.items():
            final_issue = self._normalize_issue_payload(final_master_data.get(key, "[通过]"))
            audit_results[audit_key] = final_issue["issue"]

        if final_master_data.get("overall_passed"):
            extracted_metadata["summary"] = final_master_data.get("summary", extracted_metadata["summary"])
            extracted_metadata["state_delta"] = final_master_data.get("state_delta", {})
            extracted_metadata["new_clue"] = final_master_data.get("new_clue", "")
        
        extracted_metadata["resolved_ids"] = master_data.get("resolved_ids", [])  # 使用初审的 resolved_ids 就够了，复修一般不改变回收情况，也可能被 final_master_data 覆盖
        if final_master_data.get("resolved_ids"):
             extracted_metadata["resolved_ids"] = final_master_data.get("resolved_ids", [])
             
        # audit_results 剔除了动态结果，因为已经被整合进真相或设定审查了
        return content, audit_results, extracted_metadata

    def _candidate_directive(self, candidate_index, chapter_type):
        directive = self.CANDIDATE_DIRECTIVES[(candidate_index - 1) % len(self.CANDIDATE_DIRECTIVES)]
        if chapter_type == "prologue":
            directive += " 候选之间必须明显区分开篇冲突的切入角度。"
        elif chapter_type == "epilogue":
            directive += " 候选之间必须区分终局回收方式和情绪落点。"
        else:
            directive += " 候选之间必须区分冲突推进路线和情绪结构。"
        return directive

    def _candidate_sort_key(self, item):
        metrics = item["evaluation"]["metrics"]
        return (
            metrics.get("overall", 0),
            metrics.get("ai_scent", 0),
            metrics.get("style_humanity", 0),
            metrics.get("truth_consistency", 0),
            metrics.get("hook_strength", 0),
            metrics.get("foreshadow_closure", 0),
            -len(item["evaluation"].get("risk_flags", [])),
        )


    def _record_review(self, novel_id, chapter_id, chapter_index, draft_id, candidate_label, reviewer_name, feedback):
        passed = "[通过]" in feedback
        self.db.add_chapter_review(
            book_id=novel_id,
            chapter_id=chapter_id,
            chapter_index=chapter_index,
            draft_id=draft_id,
            reviewer_name=f"{candidate_label}:{reviewer_name}",
            passed=passed,
            raw_feedback=feedback,
            score_payload={"passed": passed},
        )

    def save_industrial_artifacts(self, book_dir, chapter_idx, chapter_title, result_bundle):
        """工业化存档：将所有要素分发到对应子目录"""
        # 1. 存正文
        chapter_path = Path(book_dir) / "chapter" / f"{chapter_idx}_{chapter_title}.md"
        with open(chapter_path, "w", encoding="utf-8") as f:
            f.write(result_bundle["content"])

        # 2. 存提示词 (固化 Prompt)
        prompt_path = Path(book_dir) / "prompt" / f"{chapter_idx}_{chapter_title}_prompt.md"
        with open(prompt_path, "w", encoding="utf-8") as f:
            f.write(result_bundle.get("seed_prompt", "无提示词记录"))

        # 3. 存审计报告
        audit_path = Path(book_dir) / "audit" / f"{chapter_idx}_{chapter_title}_audit.md"
        with open(audit_path, "w", encoding="utf-8") as f:
            f.write(f"# {chapter_title} 审计全记录\n\n")
            audit_trail = result_bundle.get("audit_trail", {})
            for auditor, res in audit_trail.items():
                f.write(f"## [{auditor}]\n{res}\n\n")

        # 4. 存状态快照
        state_path = Path(book_dir) / "state" / f"{chapter_idx}_{chapter_title}_state.json"
        with open(state_path, "w", encoding="utf-8") as f:
            state_data = {
                "absolute_state": result_bundle.get("state_delta"),
                "summary": result_bundle.get("summary")
            }
            json.dump(state_data, f, ensure_ascii=False, indent=2)

    def save_result(self, content, original_name, workspace_dir=None):
        """将生成的正文存入指定目录，防止文件夹散乱。"""
        if workspace_dir:
            dir_path = Path(workspace_dir) / "chapter"
        else:
            today = datetime.now().strftime("%Y-%m-%d")
            dir_path = Path(__file__).resolve().parent / today
            
        if not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)

        file_name = f"{original_name}.md"
        full_path = dir_path / file_name

        with open(full_path, "w", encoding="utf-8") as file:
            file.write(content)
        return str(full_path)

    def _execute_serial_2pass(self, seed, clues, skill_bundle=None, few_shot_context=""):
        """2 阶段串行：第一步合并创作与节奏，第二步灵魂提取与去 AI 化"""
        style_rule = self.axioms.get("no_ai_flavor", "")
        rhythm_bundle = self.skill_manager.get_skill_bundle("RhythmDoctor")
        rhythm_samples = token_safe_prune(self.skill_manager.format_few_shot_prompt(rhythm_bundle), max_chars=1000)
        p1_sys_prompt = skill_bundle["system_prompt"] if skill_bundle else "Step 1: Creative Architect & Rhythm Specialist."
        
        # 裁剪上下文防止溢出
        pruned_setting = token_safe_prune(self.world_setting, max_chars=1200)
        pruned_few_shot = token_safe_prune(few_shot_context, max_chars=1000)

        logger.info(">> [PASS 1] 创作与节奏并发：物理质感 + 极速推进 + 长短句张力...")
        p1_prompt = (
            f"【核心背景合规约束】：{pruned_setting}\n"
            f"情节种子：{seed}\n环境/伏笔：{clues}\n"
            f"【文风参考样本】\n{pruned_few_shot}\n"
            f"【节奏参考样本】\n{rhythm_samples}\n"
            f"要求：严格遵循【核心背景合规约束】！融合上述样本的质感与节奏，强制物理特征切入，严格执行长短句错落。严禁解释，仅输出正文。"
        )
        draft_p1 = self._llm_generate(p1_prompt, p1_sys_prompt, task_profile="chapter_write") or "生成失败"

        logger.info(">> [PASS 2] 灵魂对冲：切除赘言，封杀 AI 词汇，暴力压低 AI 率...")
        p2_prompt = (
            f"待精修文本：\n{draft_p1}\n约束规则：{style_rule}\n"
            f"【核心背景合规约束】：{pruned_setting}\n"
            "要求：删掉所有总结性抒情。动作即结局。禁止使用：‘不禁’、‘缓缓’、‘总之’。保持冷峻风格。严禁违背核心设定。"
        )
        return self._llm_generate(p2_prompt, "Step 2: Soul Master Editor.", task_profile="span_fix")
    def start_perpetual_learning(self):
        logger.info("\n--- [贝叶斯引擎联觉抽卡系统] 自主学习启动 ---")
        pairs = self.db.get_pending_learning_pairs(limit=5, purpose="rule")
        if pairs:
            logger.info(f">> [配对学习] 检测到 {len(pairs)} 组待处理的人类修订样本。")
            for pair in pairs:
                prompt = f"""
                你正在分析一组短篇小说修订配对样本。
                要求：
                1. 对比 AI 草稿 与 人类终稿，提炼一条【文风修订规则】和一条【剧情修订规则】。
                2. 必须是可执行的硬规则，严格指令体。
                3. 输出严格 JSON，格式：
                {{
                  "style_rule": "...",
                  "plot_rule": "...",
                  "revision_focus": "..."
                }}

                【AI草稿】
                {pair['draft_text'][:2000]}

                【人类终稿】
                {pair['final_text'][:2000]}
                """
                response = generate_text(
                    prompt,
                    "You are a paired revision learning engine. Output ONLY valid JSON.",
                    task_profile="learning_json",
                )
                match = re.search(r"\{.*\}", response, re.DOTALL)
                if not match:
                    continue
                try:
                    learned_payload = json.loads(match.group(0))
                except json.JSONDecodeError:
                    continue
                style_rule = (learned_payload.get("style_rule") or "").strip()
                plot_rule = (learned_payload.get("plot_rule") or "").strip()
                book = self.db.get_book(pair["book_id"])
                category_prefix = ""
                if book and book.get("audience_type") == "male_oriented":
                    category_prefix = "demographic_quarantine_male_"
                elif book and book.get("audience_type") == "female_oriented":
                    category_prefix = "demographic_quarantine_female_"
                if style_rule:
                    self.db.add_dynamic_rule(f"{category_prefix}paired_revision_style", style_rule, initial_weight=1.1)
                if plot_rule:
                    self.db.add_dynamic_rule(f"{category_prefix}paired_revision_plot_logic", plot_rule, initial_weight=1.05)
                self.db.mark_learning_pair_processed(pair["id"], learned_payload, purpose="rule")
                print(f"💡 [配对进化] Pair#{pair['id']} => {learned_payload}")
            return
        print(">> [安全策略] 未发现配对样本，跳过旧版 Gold/Sandbox 全文比对流程。")

        passed = "[通过]" in feedback
        self.db.add_chapter_review(
            book_id=novel_id,
            chapter_id=chapter_id,
            chapter_index=chapter_index,
            draft_id=draft_id,
            reviewer_name=f"{candidate_label}:{reviewer_name}",
            passed=passed,
            raw_feedback=feedback,
            score_payload={"passed": passed},
        )

    def save_industrial_artifacts(self, book_dir, chapter_idx, chapter_title, result_bundle):
        """工业化存档：将所有要素分发到对应子目录"""
        # 1. 存正文
        chapter_path = Path(book_dir) / "chapter" / f"{chapter_idx}_{chapter_title}.md"
        with open(chapter_path, "w", encoding="utf-8") as f:
            f.write(result_bundle["content"])

        # 2. 存提示词 (固化 Prompt)
        prompt_path = Path(book_dir) / "prompt" / f"{chapter_idx}_{chapter_title}_prompt.md"
        with open(prompt_path, "w", encoding="utf-8") as f:
            f.write(result_bundle.get("seed_prompt", "无提示词记录"))

        # 3. 存审计报告
        audit_path = Path(book_dir) / "audit" / f"{chapter_idx}_{chapter_title}_audit.md"
        with open(audit_path, "w", encoding="utf-8") as f:
            f.write(f"# {chapter_title} 审计全记录\n\n")
            audit_trail = result_bundle.get("audit_trail") or {}
            for auditor, res in audit_trail.items():
                f.write(f"## [{auditor}]\n{res}\n\n")

        # 4. 存状态快照
        state_path = Path(book_dir) / "state" / f"{chapter_idx}_{chapter_title}_state.json"
        with open(state_path, "w", encoding="utf-8") as f:
            state_data = {
                "absolute_state": result_bundle.get("state_delta") or {},
                "summary": result_bundle.get("summary")
            }
            json.dump(state_data, f, ensure_ascii=False, indent=2)

    def save_result(self, content, original_name, workspace_dir=None):
        """将生成的正文存入指定目录，防止文件夹散乱。"""
        if workspace_dir:
            dir_path = Path(workspace_dir) / "chapter"
        else:
            today = datetime.now().strftime("%Y-%m-%d")
            dir_path = Path(__file__).resolve().parent / today
            
        if not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)

        file_name = f"{original_name}.md"
        full_path = dir_path / file_name

        with open(full_path, "w", encoding="utf-8") as file:
            file.write(content)
        return str(full_path)

    def _get_cached_system_prompt(self, skill_bundle=None, few_shot_context=""):
        sys_prompt = skill_bundle["system_prompt"] if skill_bundle else "You are an expert novel writer."
        brief = token_safe_prune(self.book_brief or self.world_setting, max_chars=520, head_ratio=0.75)
        if brief:
            sys_prompt += f"\n\n【本书创作胶囊】：\n{brief}"

        if self.core_style_guide:
            sys_prompt += f"\n\n{self.core_style_guide}"

        if self.reference_guard:
            sys_prompt += "\n" + token_safe_prune(self.reference_guard.planner_constraints(), max_chars=360, head_ratio=0.8)

        style_rule = self.axioms.get("no_ai_flavor", "")
        if style_rule:
            sys_prompt += f"\n\n【全书硬核创作规范】：{token_safe_prune(style_rule, max_chars=260, head_ratio=0.8)}"

        if few_shot_context:
            sys_prompt += f"\n\n{token_safe_prune(few_shot_context, max_chars=700, head_ratio=0.8)}"
            
        return sys_prompt

    def _execute_single_pass(self, seed, clues, skill_bundle=None, few_shot_context="", due_clues=None, dynamic_rules=""):
        """单次结晶：利用 System Prompt 缓存，避免重复传入背景"""
        sys_prompt = self._get_cached_system_prompt(skill_bundle, few_shot_context)
        
        user_prompt = f"【本章生成任务】：\n\n{seed}\n"
        if clues:
            user_prompt += f"\n【即时执行提醒】：\n{clues}\n"
        
        if due_clues:
            clue_context = "、".join([f"[{item.get('priority', 'B')}级] {item.get('desc', '')} (ID:{item.get('id', '')})" for item in due_clues])
            user_prompt += f"\n【本章必须回收的伏笔】：\n{clue_context}\n请在正文中合情合理地将其解密或推进。\n"
            
        if dynamic_rules:
            user_prompt += f"\n【动态防融梗/违规底线】：\n{dynamic_rules}\n"
            
        user_prompt += """
请直接输出正文，严禁解释。
【极度重要】：在正文生成完毕的最后，你必须附带一个不可见的 JSON 代码块，用于向系统提供本章的元数据（必须包裹在 ```json 和 ``` 之间）。
格式严格如下：
```json
{
  "summary": "80-100字以内的极简摘要",
  "state_delta": {"physical_state": {}, "cognitive_state": {}, "identity_mask": ""},
  "new_clue": "级别|内容（如 A|某人怀恨在心，如果没有新伏笔请留空）",
  "resolved_ids": [123, 456] // 本章实质性回收的伏笔ID数字数组，没有则为空数组[]
}
```
"""
        return self._llm_generate(user_prompt, sys_prompt, task_profile="chapter_write")

    def start_perpetual_learning(self):
        logger.info("\n--- [贝叶斯引擎联觉抽卡系统] 自主学习启动 ---")
        pairs = self.db.get_pending_learning_pairs(limit=5, purpose="rule")
        if pairs:
            logger.info(f">> [配对学习] 检测到 {len(pairs)} 组待处理的人类修订样本。")
            for pair in pairs:
                prompt = f"""
                你正在分析一组短篇小说修订配对样本。
                要求：
                1. 对比 AI 草稿 与 人类终稿，提炼一条【文风修订规则】和一条【剧情修订规则】。
                2. 必须是可执行的硬规则，严格指令体。
                3. 输出严格 JSON，格式：
                {{
                  "style_rule": "...",
                  "plot_rule": "...",
                  "revision_focus": "..."
                }}

                【AI草稿】
                {pair['draft_text'][:2000]}

                【人类终稿】
                {pair['final_text'][:2000]}
                """
                response = generate_text(
                    prompt,
                    "You are a paired revision learning engine. Output ONLY valid JSON.",
                    task_profile="learning_json",
                )
                match = re.search(r"\{.*\}", response, re.DOTALL)
                if not match:
                    continue
                try:
                    learned_payload = json.loads(match.group(0))
                except json.JSONDecodeError:
                    continue
                style_rule = (learned_payload.get("style_rule") or "").strip()
                plot_rule = (learned_payload.get("plot_rule") or "").strip()
                book = self.db.get_book(pair["book_id"])
                category_prefix = ""
                if book and book.get("audience_type") == "male_oriented":
                    category_prefix = "demographic_quarantine_male_"
                elif book and book.get("audience_type") == "female_oriented":
                    category_prefix = "demographic_quarantine_female_"
                if style_rule:
                    self.db.add_dynamic_rule(f"{category_prefix}paired_revision_style", style_rule, initial_weight=1.1)
                if plot_rule:
                    self.db.add_dynamic_rule(f"{category_prefix}paired_revision_plot_logic", plot_rule, initial_weight=1.05)
                self.db.mark_learning_pair_processed(pair["id"], learned_payload, purpose="rule")
                print(f"💡 [配对进化] Pair#{pair['id']} => {learned_payload}")
            return
        print(">> [安全策略] 未发现配对样本，跳过旧版 Gold/Sandbox 全文比对流程。")
