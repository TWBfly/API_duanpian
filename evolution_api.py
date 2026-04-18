import json
import os
import re
import concurrent.futures
from datetime import datetime
from pathlib import Path

from auditors import (
    DemographicAuditor,
    HookAuditor,
    StyleAuditor,
    StylisticCompositeAuditor,
    TruthCompositeAuditor,
    AI_ScentAuditor,
)
from chroma_memory import ChromaMemory
from evaluators import QuantitativeEvaluator
from llm_client import generate_text, generate_text_full, DEFAULT_MODEL, resolve_model_name
from neo4j_db import Neo4jManager
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
        self.audience_type = audience_type
        self.logic_layer_cls = logic_layer
        self.axioms = {}
        self.logic_layer = None
        self.demo_auditor = None
        self.style_auditor = None
        self.hook_auditor = HookAuditor()
        self.scent_auditor = AI_ScentAuditor()
        self.quant_evaluator = QuantitativeEvaluator()
        self.dynamic_auditors = [] # 动态审计插件池
        
        # 聚合审计器初始化
        self.stylistic_auditor = None
        self.truth_auditor = None

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

    def _llm_generate(self, prompt, system_prompt="You are an expert novel writer.", model=DEFAULT_MODEL):
        """内部封装：带用量统计与日志的生成接口"""
        res = generate_text_full(prompt, system_prompt, model)
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

    def add_auditor(self, auditor):
        """支持外部注入动态审计插件（如 PlagiarismGuard）"""
        self.dynamic_auditors.append(auditor)
        if self.verbose:
            logger.info(f"🔌 [插件挂载] 已成功接入外部审计器: {auditor.name}")

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
        candidate_count=2,
    ):
        if self.verbose:
            logger.info(f"\n--- [顶级流水线启动] 正在深度锻造章节：{title} (类型: {chapter_type}) ---")
        
        self.current_novel_id = novel_id
        self.current_chapter_index = chapter_index
        
        self.refresh_axioms()
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
        self.db.mark_selected_draft(winner["draft_id"], novel_id, chapter_index)
        logger.info(f"👑 [候选胜出] {winner['candidate_label']} | 总分 {winner['evaluation']['metrics']['overall']:.2f}")

        resolved_ids = winner["resolved_ids"]
        if resolved_ids:
            for foreshadow_id in resolved_ids:
                self.db.resolve_foreshadow_record(foreshadow_id)
                self.neo4j.resolve_foreshadow(foreshadow_id)
            logger.info(f"✅ [伏笔核销] 已回收伏笔 ID: {resolved_ids}")

        new_clue = self._extract_new_clue(winner["content"])
        if new_clue:
            priority, desc = new_clue
            target_chapter = (
                chapter_index + 3
                if priority == "A"
                else (chapter_index + 1 if priority == "B" else chapter_index + 4)
            )
            foreshadow_id = self.db.add_foreshadow_record(novel_id, desc, priority, target_chapter)
            self.neo4j.add_foreshadow(novel_id, desc, priority, target_chapter, sql_id=foreshadow_id)
            logger.info(f"📌 [Neo4j 伏笔入库] 级别 {priority} -> 预计第 {target_chapter} 章排解：{desc}")

        state_delta = self._extract_state_delta(winner["content"])
        if state_delta:
            self.neo4j.update_character_state(novel_id, self.main_character_name, state_delta)
            merged_state = self._merge_absolute_state(absolute_state, state_delta)
            self.db.save_character_state_snapshot(novel_id, self.main_character_name, merged_state)
            logger.info(f"💾 [真理层更新] 状态全维刷新成功: {list(state_delta.keys())}")

        chapter_summary = self._llm_generate(f"为以下章节写一句50字内的超短摘要：\n{winner['content']}", "Summarizer")
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
            "chapter_id": chapter_id,
            "draft_id": winner["draft_id"],
            "final_id": final_id,
            "new_clue": new_clue,
            "state_delta": state_delta,
            "candidate_results": [
                {
                    "candidate_label": item["candidate_label"],
                    "draft_id": item["draft_id"],
                    "overall": item["evaluation"]["metrics"]["overall"],
                    "audit_results": item.get("audit_results")
                }
                for item in candidate_results
            ],
            "seed_prompt": seed_prompt, # 固化的提示词
            "audit_trail": winner.get("audit_results") # 胜出者的审计轨迹
        }

    def _prepare_generation_context(self, novel_id, chapter_index, seed_prompt, skeleton_data, absolute_state, chapter_type):
        inventory_context = absolute_state.get("physical_state", {}).get("inventory", "无")
        mask_context = absolute_state.get("identity_mask", "无身份伪装")
        
        if self.verbose:
            logger.info(f">> [绝对状态挂载] 状态: {absolute_state.get('physical_state', {})} | 伪装: {mask_context}")

        skeleton_plot = skeleton_data.get("plot_beat", "")
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
            seed_prompt = self._llm_generate(mutation_prompt, "You are an anti-cliche mutating machine.")

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
            chapter_requirements.append("本章为第10章大结局，必须爆发终极冲突，强烈呼应第一章开篇悬念，并把核心伏笔闭环。")
            if self.axioms.get("continuity_payoff"):
                chapter_requirements.append(self.axioms["continuity_payoff"])

        if chapter_requirements:
            seed_prompt += "\n【结构约束】：" + " ".join(chapter_requirements)

        return {
            "seed_prompt": seed_prompt,
            "clue_context": clue_context,
            "due_clues": due_clues,
        }

    def _merge_absolute_state(self, absolute_state, state_delta):
        merged = {
            "physical_state": dict((absolute_state or {}).get("physical_state", {})),
            "cognitive_state": dict((absolute_state or {}).get("cognitive_state", {})),
        }
        for key, value in (state_delta or {}).items():
            if value in (None, ""):
                continue
            merged["physical_state"][key] = value
        identity_mask = merged["physical_state"].get("identity_mask")
        if identity_mask:
            merged["identity_mask"] = identity_mask
        return merged

    def _generate_surgical_hook(self, seed, skill_bundle=None, few_shot_context=""):
        """外科手术：专门打磨前 100 字黄金钩子"""
        hook_sys = "You are a 'Shock Architect' specialized in 100-character novel openings."
        if skill_bundle: 
            hook_sys = skill_bundle["system_prompt"]
            
        logger.info(">> [Surgical Hook] 正在打磨黄金前 100 字...")
        prompt = (
            f"大纲种子：{seed}\n"
            f"{few_shot_context}\n"
            "【强制指令】：仅创作楔子的开篇 150 字以内。必须在前 100 字内引爆最激烈的矛盾、视觉冲击或因果悬念。"
            "绝对禁止交代：‘在很久以前’、‘有一个叫XX的人’、或者是描写风景。"
        )
        return self._llm_generate(prompt, hook_sys)

    def _audit_and_fix_loop(self, auditor_name, auditor_obj, content, seed_prompt, fix_prompt_template, fix_sys_prompt,
                            novel_id, chapter_id, chapter_index, candidate_label, max_retries=2, absolute_state=None, few_shot_context=""):
        retries = 0
        final_res = "[通过]"
        while retries < max_retries:
            if auditor_name == "truth":
                res = auditor_obj.audit(content, absolute_state)
            else:
                res = auditor_obj.audit(content)

            if res is None:
                res = "LLM 响应为空或超时 [拦截]"
                logger.error(f"   ❌ [{candidate_label}:{auditor_name}] 审计响应为空")

            if "[通过]" in res:
                final_res = "[通过]"
                break

            final_res = res
            retries += 1
            if retries >= max_retries:
                # 达到重试上限，保留当前但标记错误
                break

            # 若未通过，执行修复
            fix_prompt = fix_prompt_template.format(content=content, issue=res)
            if few_shot_context:
                fix_prompt = f"{few_shot_context}\n\n{fix_prompt}"
            
            if auditor_name == "logic":
                self.db.penalize_rule("strict_disguise_logic")

            content = self._llm_generate(fix_prompt, fix_sys_prompt)
            self.db.add_chapter_draft(
                novel_id, chapter_id, chapter_index, f"{candidate_label}:{auditor_name}_fixed_{retries}",
                content, seed_prompt=seed_prompt, model_name=resolve_model_name(DEFAULT_MODEL), candidate_label=candidate_label
            )

        return content, final_res

    def _select_skill_for_pipeline(self, chapter_type, audience):
        if chapter_type == "prologue":
            return "HookMaster"
        if audience and "female" in audience.lower():
            return "GenreFemaleExpert"
        return "GenreMaleExpert" # 默认或男频

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
        if self.verbose:
            logger.info(f"   - [阶段] {candidate_label} 手术中 (Skill: {skill_bundle['skill_name'] if skill_bundle else 'Default'})...")
        
        # 核心变动：将技能的 Few-Shot 样本注入前台
        few_shot_context = self.skill_manager.format_few_shot_prompt(skill_bundle)
        
        retries = 0
        hook_res = "[通过]"
        content = ""

        while retries < self.hook_auditor.max_retries:
            # 楔子特殊处理：先手术钩子，再补全正文
            if chapter_type == "prologue":
                hook_head = self._generate_surgical_hook(seed_prompt, skill_bundle, few_shot_context)
                content = self._execute_serial_3pass(
                    seed=f"请承接下文动作并补全至 2000 字：\n【楔子黄金钩子】：\n{hook_head}", 
                    clues=clue_context, 
                    skill_bundle=skill_bundle,
                    few_shot_context=few_shot_context
                )
                # 重新把钩子缝合回去
                content = f"{hook_head}\n{content}"
            else:
                content = self._execute_serial_3pass(
                    seed=seed_prompt, 
                    clues=clue_context, 
                    skill_bundle=skill_bundle,
                    few_shot_context=few_shot_context
                )
            
            if chapter_type == "prologue":
                hook_res = self.hook_auditor.audit(content)
                if "[通过]" not in hook_res:
                    retries += 1
                    logger.warning(f"❌ [{candidate_label}] Hook 审查被打回：{hook_res} ({retries}/{self.hook_auditor.max_retries})")
                    seed_prompt = f"{seed_prompt}\n【上一版失败原因】：{hook_res}\n请重新生成一个开幕雷击更猛的版本。"
                    continue
            break

        audit_results = {"hook": hook_res}
        
        # 增加 AI 烂梗哨兵审查
        content, scent_res = self._audit_and_fix_loop(
            "scent", self.scent_auditor, content, seed_prompt,
            "原稿：\n{content}\nAI 烂梗及逻辑总结点建议：{issue}\n请执行‘切除手术’，用人话和具体动作替换之。",
            "You are a linguistic surgeon.",
            novel_id, chapter_id, chapter_index, candidate_label
        )
        audit_results["scent"] = scent_res

        current_draft_id = self.db.add_chapter_draft(
            book_id=novel_id,
            chapter_id=chapter_id,
            chapter_index=chapter_index,
            draft_stage=f"{candidate_label}:three_pass_candidate",
            candidate_label=candidate_label,
            content=content,
            seed_prompt=seed_prompt,
            model_name=resolve_model_name(DEFAULT_MODEL),
        )
        if chapter_type == "prologue":
            self._record_review(novel_id, chapter_id, chapter_index, current_draft_id, candidate_label, "hook", hook_res)

        content, stylistic_res = self._audit_and_fix_loop(
            "stylistic", self.stylistic_auditor, content, seed_prompt,
            "原稿：\n{content}\n综合修改意见：{issue}\n请仅根据上述意见优化文字的节奏、多样性并剔除废话。禁止微调原有因果。",
            "You are a stylistic master.",
            novel_id, chapter_id, chapter_index, candidate_label,
            few_shot_context=few_shot_context
        )
        audit_results["stylistic"] = stylistic_res

        content, truth_res = self._audit_and_fix_loop(
            "truth", self.truth_auditor, content, seed_prompt,
            "原稿：\n{content}\n真理冲突：{issue}\n请修正该剧情，确保符合物理真理、认知边界及伪装逻辑。",
            "You are a truth consistency fixer.",
            novel_id, chapter_id, chapter_index, candidate_label, absolute_state=absolute_state,
            few_shot_context=few_shot_context
        )
        audit_results["truth"] = truth_res

        content, demo_res = self._audit_and_fix_loop(
            "demographic", self.demo_auditor, content, seed_prompt,
            "文本：\n{content}\n问题：{issue}\n请把文本修正为明确符合" + self.audience_type + "的表达与冲突组织。",
            "You are a demographic alignment fixer.",
            novel_id, chapter_id, chapter_index, candidate_label,
            few_shot_context=few_shot_context
        )
        audit_results["demographic"] = demo_res

        content, style_res = self._audit_and_fix_loop(
            "style", self.style_auditor, content, seed_prompt,
            "文本：\n{content}\n问题：{issue}\n请在不改变剧情因果的前提下，按要求提升人味、断句和张力。",
            "You are a final style alignment editor.",
            novel_id, chapter_id, chapter_index, candidate_label,
            few_shot_context=few_shot_context
        )
        audit_results["style"] = style_res

        # 动态插件审计（包含法务洗稿拦截）
        for dyn_auditor in self.dynamic_auditors:
            content, dyn_res = self._audit_and_fix_loop(
                f"dynamic_{dyn_auditor.name}", dyn_auditor, content, seed_prompt,
                "文本：\n{content}\n插件拦截原因：{issue}\n请立即执行针对性手术修正，消除以上违规风险。",
                f"You are a specialized {dyn_auditor.name} fixer.",
                novel_id, chapter_id, chapter_index, candidate_label
            )
            audit_results[dyn_auditor.name] = dyn_res

        resolved_ids = self._extract_resolved_ids(content, due_clues)
        evaluation = self.quant_evaluator.evaluate(
            text=content,
            audience_type=self.audience_type,
            chapter_type=chapter_type,
            audit_results=audit_results,
            skeleton_data=skeleton_data,
            due_clues=due_clues,
            resolved_ids=resolved_ids,
            absolute_state=absolute_state,
        )
        final_candidate_draft_id = self.db.add_chapter_draft(
            book_id=novel_id,
            chapter_id=chapter_id,
            chapter_index=chapter_index,
            draft_stage=f"{candidate_label}:final_candidate",
            candidate_label=candidate_label,
            content=content,
            seed_prompt=seed_prompt,
            model_name=resolve_model_name(DEFAULT_MODEL),
            evaluation=evaluation,
            is_selected=False,
        )

        return {
            "candidate_label": candidate_label,
            "content": content,
            "evaluation": evaluation,
            "draft_id": final_candidate_draft_id,
            "resolved_ids": resolved_ids,
            "audit_results": audit_results, # 捕获完整的审计结果
        }

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

    def _extract_resolved_ids(self, content, due_clues):
        if not due_clues:
            return []
        
        valid_ids = {item['id'] for item in due_clues}
        clue_context = "、".join([f"[{item['priority']}级] {item['desc']} (ID:{item['id']})" for item in due_clues])
        
        resolve_prompt = (
            "请极度严苛地判断以下伏笔是否已在正文中被【明确且实质性地】回应或回收。\n"
            "警告：不要自行脑补或宽泛理解！只有当正文明确写出了伏笔对应的直接情节或解密，才算回收。\n"
            "只回复已确凿回收伏笔的ID，多个用英文逗号分隔；若任何一个都没明确回收，坚决回复'无'。\n"
            f"待核对伏笔：{clue_context}\n"
            f"正文：\n{content}"
        )
        resolved_ids_raw = self._llm_generate(resolve_prompt, "You are a strict foreshadow payoff validator.")
        resolved_ids = []
        if resolved_ids_raw and "无" not in resolved_ids_raw:
            for item in resolved_ids_raw.replace("，", ",").split(","):
                item = item.strip()
                if item.isdigit():
                    item_id = int(item)
                    if item_id in valid_ids:
                        resolved_ids.append(item_id)
        return resolved_ids

    def _extract_new_clue(self, content):
        prompt = (
            "分析本章内容，是否产生了新的悬念或伏笔？如果是，请用一句话描述，并评估重要度"
            "(S:影响全局大坑；A:大章节坑；B:细小道具回调)。如果没有直接回复'无'。"
            f"格式例子：S|主角掉落悬崖后的神秘老头：\n{content}"
        )
        response = self._llm_generate(prompt, "You are a causal analyzer.")
        if not response or "无" in response or "|" not in response:
            return None
        priority, desc = response.split("|", 1)
        priority = priority.strip()
        if priority not in {"S", "A", "B"}:
            return None
        return priority, desc.strip()

    def _extract_state_delta(self, content):
        prompt = (
            f"阅读本章内容：\n{content}\n"
            "请提取主角最新的各维度状态变化（例如受限于功法、外貌伪装、新斩获的特殊装备道具、或者是地理位置等）。"
            "以JSON形式返回动态键值对，比如 {\"location\": \"京城\", \"poison_level\": \"深度\", \"artifact\": \"断魂刀\"}。"
            "不要包含未改变的信息，如果完全没变，直接返回空JSON {}。"
        )
        try:
            response = self._llm_generate(prompt, "You are a fast state extractor. Return ONLY valid JSON.")
            if not response:
                return {}
            match = re.search(r"\{.*\}", response, re.DOTALL)
            if match:
                parsed = json.loads(match.group(0))
                if isinstance(parsed, dict):
                    return parsed
        except Exception as exc:
            logger.error(f"⚠️ 状态抽提失败: {exc}")
        return {}

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

    def save_result(self, content, original_name):
        """保留原有的扁平化存储以作备份"""
        today = datetime.now().strftime("%Y-%m-%d")
        dir_path = Path(__file__).resolve().parent / today
        if not os.path.exists(dir_path):
            os.makedirs(dir_path)

        file_name = f"{original_name}-{today}.md"
        full_path = os.path.join(dir_path, file_name)

        with open(full_path, "w", encoding="utf-8") as file:
            file.write(content)
        return full_path

    def _execute_serial_3pass(self, seed, clues, skill_bundle=None, few_shot_context=""):
        """执行真正的 3 阶段串行手术，注入特定的动态技能与样本"""
        style_rule = self.axioms.get("no_ai_flavor", "")
        
        # 默认系统 Prompt，如果 Skill 库里有更精准的则替换
        p1_sys_prompt = "Stage 1: Sensory Architect."
        if skill_bundle:
            p1_sys_prompt = skill_bundle["system_prompt"]

        logger.info(">> [PASS 1] 技能注入：物理特征与五感切入 (结合 Few-Shot 样本)...")
        p1_prompt = (
            f"情节种子：{seed}\n环境/伏笔：{clues}\n"
            f"{few_shot_context}\n"
            f"要求：严格参考上述案例样本的文笔、断句与切入技巧进行创作。强制物理反应描写。"
        )
        draft_p1 = self._llm_generate(p1_prompt, p1_sys_prompt) or "生成失败"

        # 加载节奏医生技能进行 Pass 2
        rhythm_bundle = self.skill_manager.get_skill_bundle("RhythmDoctor")
        rhythm_sys_prompt = rhythm_bundle["system_prompt"] if rhythm_bundle else "Stage 2: Rhythm Specialist."
        rhythm_samples = self.skill_manager.format_few_shot_prompt(rhythm_bundle)

        logger.info(">> [PASS 2] 节奏粉碎：重塑长短句张力，仿写高阶节奏...")
        p2_prompt = (
            f"基础文本：\n{draft_p1}\n"
            f"{rhythm_samples}\n"
            f"【绝对要求】：无论如何修改节奏，必须保留以下伏笔：{clues}\n"
            f"【人类作家文笔法则】：{style_rule}\n"
            f"要求：模仿上述高阶样本的断句风格，严格遵守人类作家文笔法则，打破平庸节奏，降低AI感。"
        )
        draft_p2 = self._llm_generate(p2_prompt, rhythm_sys_prompt) or draft_p1

        logger.info(">> [PASS 3] 灵魂对冲：剔除赘言，封杀 AI 词汇...")
        p3_prompt = (
            f"待精修文本：\n{draft_p2}\n约束：{style_rule}\n"
            "要求：删掉所有总结性抒情。动作即结局。禁止使用：‘不禁’、‘缓缓’、‘总之’。"
        )
        return self._llm_generate(p3_prompt, "Stage 3: Soul Master Editor.")

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
                response = generate_text(prompt, "You are a paired revision learning engine. Output ONLY valid JSON.")
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

        sandbox_txt, gold_txt = self.db.get_latest_sandbox_and_gold()
        if not sandbox_txt or not gold_txt:
            print(">> 样本不足，跳过本次自主学习。")
            return

        print(">> [兜底提取] 正在比对 AI 原稿 与 Gold 稿的风格差值...")
        prompt = f"""
        请分析以下两段文本在“写作风格、行文张力、微动作或情绪把控”上的最核心的差异
        （只提取一条最关键的规则，不要任何废话和解释，使用指令式语气，不超过40字）：
        【AI废稿】：{sandbox_txt}
        【人工修改稿】：{gold_txt}
        """
        new_rule_text = generate_text(prompt, "You are an analytical Master Editor extracting concrete stylistic rules.")

        if new_rule_text:
            print(f"💡 [进化金科玉律] => {new_rule_text}")
            self.db.add_dynamic_rule("extracted_style_rule", new_rule_text, initial_weight=1.0)
            print("✔️ 新规则已加入全局 SQLite Rules_Ledger 进行持久化。引擎将在下一次全域生成时采用该法则。")
