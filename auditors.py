import re
from difflib import SequenceMatcher

from llm_client import generate_text
from logger import logger
from novel_utils import token_safe_prune, tokenize_cn_text

class AuditorBase:
    def __init__(self, name):
        self.name = name

    def audit(self, text, context=""):
        pass

class AI_ScentAuditor(AuditorBase):
    """
    去 AI 化哨兵：物理封杀 GPT 常用烂梗与逻辑尾注。
    """
    def __init__(self):
        super().__init__("AI_ScentAuditor")
        # 建立黑名单库
        self.blacklist = [
            "不禁", "缓缓", "总之", "原本以为", "随着时间的推演", "那一刻", 
            "仿佛在诉说", "勾勒出", "不可忽略", "在这个...的过程中", 
            "不得不说", "让人联想到", "深刻地", "正如...所说"
        ]

    def audit(self, text):
        # 1. 物理分离标题与正文（兼容多种空行情况）
        lines = text.strip().split('\n')
        title = ""
        narrative_body = ""
        found_title = False
        for line in lines:
            if not found_title and line.strip():
                title = line.strip()
                found_title = True
                continue
            narrative_body += line + "\n"

        # 2. 静态词网拦截（仅针对正文）
        meta_blacklist = ["楔子", "第[\d一二三四五六七八九十百]+章", "上一章", "下回", "本书", "故事", "剧情", "叙事"]
        meta_pattern = "|".join(meta_blacklist)
        meta_matches = re.findall(meta_pattern, narrative_body)
        
        if meta_matches:
            unique_meta = list(set(meta_matches))
            feedback = f"检测到【正文内】非法引用章节标记或元叙事词汇：{', '.join(unique_meta)}。严禁在叙事过程中提及章节名、结构术语或任何打破‘第四面墙’的词汇。请直接修改为具象的剧情描述。"
            return feedback

        # 3. 常见 AI 烂梗黑名单（针对全文）
        pattern = "|".join(re.escape(word) for word in self.blacklist)
        matches = re.findall(pattern, text)
        
        if matches:
            unique_matches = list(set(matches))
            feedback = f"发现 AI 典型烂梗词汇：{', '.join(unique_matches)}。请通过具体的物理动作、神态描写来替换这些词。让文字更有‘人味’。"
            return feedback

        # 4. 深度逻辑审计（元叙事模式匹配）
        prompt = f"""你是一名文字洁癖专家，专门剔除 AI 写作中的“翻译腔”和“元叙事穿帮”。
        请审查以下文本：
        
        【正文内容】：
        {narrative_body}
        
        重点审计：
        1. **元叙事 / 打破第四面墙**：是否存在暗示正在写书或引用前文的语句（如“像极了楔子里”、“正如前文提到”）。
        2. **毫无意义的总结**：段尾是否出现了总结性废话。
        3. **结构化套路**：是否有明显的“不仅...而且...”等结构。
        
        如果发现任何问题，请**直接指出具体句子并给出修改建议**，不要输出总结性评价或报告。如果文字干脆利落、充满真实感，回复：[通过]。"""
        return generate_text(
            prompt,
            "You are a linguistic surgeon targeting AI artifacts and meta-talk.",
            task_profile="audit_short",
        )

class DemographicAuditor(AuditorBase):
    def __init__(self, audience_type, axioms):
        super().__init__("DemographicAuditor")
        self.audience_type = audience_type
        self.rule = axioms["demographic_quarantine"].get(audience_type, "")

    def audit(self, text):
        prompt = f"请使用严格的标准审核以下文本是否符合【{self.audience_type}】的受众定位规则：{self.rule}\n文本：{text}\n如果不符合，请提出修改建议。如果符合，请回复：[通过]。"
        return generate_text(prompt, "You are a strict narrative auditor.", task_profile="audit_short")

class DisguiseLogicAuditor(AuditorBase):
    def __init__(self, axioms):
        super().__init__("DisguiseLogicAuditor")
        self.rule = axioms["strict_disguise_logic"]

    def audit(self, text):
        prompt = f"请使用多重物理/伪装逻辑锁审查机制审查以下文本：{self.rule}\n文本：{text}\n请仔细检查伪装是否穿帮，代词及物理特征是否合理。仅回复：[通过] 或 给出修改建议。"
        return generate_text(prompt, "You are a strict disguise logic auditor.", task_profile="audit_short")
        
class StyleAuditor(AuditorBase):
    def __init__(self, axioms):
         super().__init__("StyleAuditor")
         self.rule = axioms.get("no_ai_flavor", "")
         self.master_style = axioms.get("master_style", "极具张力的长短句错落反差爽文风格")
         
    def audit(self, text):
        prompt = f"""执行三阶段去AI化审查。
        核心参考风格：{self.master_style}
        核心宪法：{self.rule}
        
        待审核文本：{text}
        
        请评估是否达到：
        1. 感官降临（嗅觉/触觉切入）
        2. 节奏粉碎（长短句错落有致，具备爆发力）
        3. 灵魂对冲（无多余形容词，动作即灵魂）
        
        如果未达标，请提出具体的修改建议（模仿烽火风格）；如果达标，回复：[通过] 及张力得分。"""
        return generate_text(
            prompt,
            "You are Master Editor V6, specializing in the sharp, high-tension style of Fenghuo Xi Zhuhou.",
            task_profile="audit_medium",
        )

class HookAuditor(AuditorBase):
    def __init__(self):
        super().__init__("HookAuditor")
        self.max_retries = 3
        
    def audit(self, text):
        """专门针对【楔子/第一章】进行的开幕雷击核验机制"""
        # 第一步：物理提取前 100 字
        head_100 = text[:100]
        
        prompt = f"""你是一名极其挑剔的白金网文编辑。现在正在审核一个【开篇楔子】。
        
        【待审前 100 字】：
        {head_100}
        
        【待审全文】：
        {text}
        
        请进行最高规格的“开幕雷击”测试：
        1. **黄金 100 字**：这前 100 个字是否直接把读者拉入了一个由于信息差、生死危机或强烈情绪构成的“风暴中心”？是否有任何温吞的背景交代（如“在古代有这样一个...”）？
        2. **钩子强度**：是否产生了即便读者想放下书，脑子里也会不由自主想“接下来会发生什么”的强留人效果？
        3. **灵魂指数**：主角是否在该片段中展现了极致的人性切片？
        
        评分标准：
        如果前 100 字无法在前 3 秒抓住读者的呼吸，直接判为“未通过”。
        
        如果通过，请按以下格式回复：[通过] | 爆发分：(1-100)。
        如果未通过，请明确指出：“前100字过于平淡，建议从 XX 冲突点直接切入。”"""
        return generate_text(prompt, "You are a merciless hook-and-tension auditor.", task_profile="audit_medium")

class StateConsistencyAuditor(AuditorBase):
    def __init__(self):
        super().__init__("StateConsistencyAuditor")
        
    def audit(self, text, absolute_state):
        """对比实体真理层，严查物理与社会状态穿帮，并严打上帝上帝视角信息泄露 (POV 越权)"""
        if not absolute_state:
            return "[通过]"
            
        phys_state = absolute_state.get("physical_state", {})
        cog_state = absolute_state.get("cognitive_state", {})
        mask_state = absolute_state.get("identity_mask", "无")
        
        phys_str = " | ".join(f"{k}: {v}" for k, v in phys_state.items()) if phys_state else "无"
        cog_str = " | ".join(f"{k}: {v}" for k, v in cog_state.items()) if cog_state else "无"

        prompt = f"""你是绝对真理与 POV 越权校验机。
        【当前角色客观物理状态】：{phys_str}
        【角色当前伪装/马甲身份】：{mask_state}
        【基于伪装的认知限制】：{cog_str}
        
        【待审核剧情段落】：
        {text}
        
        请进行深度逻辑穿帮审计：
        1. **身份泄露（穿帮）**：如果角色正在执行“女扮男装”或其他伪装，文本中是否出现了不符合当前“皮囊”身份的描述？（例如：被称呼为“她”，或者流露出女性特有的生理本能）。
        2. **能力/资产越权**：角色是否在不该暴露时使用了真实身份才具备的高阶武技或隐藏财富？
        3. **认知上帝视角**：文本是否通过旁白或独白泄露了角色目前“不知道”的真相？
        
        如果发现任何穿帮点，请指出并要求“修正伪装逻辑”。如果严丝合缝，回复：[通过]。"""
        return generate_text(prompt, "You are an absolute objective truth validator.", task_profile="audit_medium")

class RhythmAuditor(AuditorBase):
    def __init__(self):
        super().__init__("RhythmAuditor")

    def audit(self, text):
        """人类作家断句与排版学习审查"""
        prompt = f"""你是一名专门研究网络文学“神级排版与断句张力”的结构大师。
        
        请审核以下文本是否犯了“AI式行文”大忌：
        1. 连绵不断的超长从句（例如含有太多“在...下”，“由于”，“从而”等逻辑连词）。
        2. 视觉上的“大段落文字块”（缺乏回车空行引发的呼吸感）。
        
        待审文本：
        {text}
        
        如果文本连绵不绝、逻辑连词过多，或者没有良好的物理分段断句，请回复详细修正意见。
        如果文本断句干脆利落，回复：[通过]。"""
        return generate_text(prompt, "You are a structural rhythm master.", task_profile="audit_short")

class StructuralVarianceAuditor(AuditorBase):
    def __init__(self):
        super().__init__("StructuralVarianceAuditor")

    def audit(self, text):
        prompt = f"""你是一名句法变异审计师。
        任务：检查以下文本段落开头。是否存在连续三个及其以上段落使用相同的主语或连词起手？
        是否存在“动作 -> 感受 -> 总结”的固定 AI 模板？
        
        文本：{text}
        
        如果发现结构僵化，指出具体点并要求变异。如果起手错落有致，回复：[通过]。"""
        return generate_text(prompt, "You are a syntax variance auditor.", task_profile="audit_short")

class DeExplanationAuditor(AuditorBase):
    def __init__(self):
        super().__init__("DeExplanationAuditor")

    def audit(self, text):
        prompt = f"""你是一名文字手术医生，专门切除段尾总结性陈述（画蛇添足）。
        （例如：“这就是他...的原因”、“这一刻，他明白了...”、“这就是命运对他的...”）。
        
        文本：{text}
        
        如果发现此类总结，请要求直接切除，让文字停在动作最高潮。如果干净利落，回复：[通过]。"""
        return generate_text(prompt, "You are a linguistic surgeon.", task_profile="audit_short")

class PlagiarismGuard(AuditorBase):
    def __init__(self, blacklist):
        super().__init__("PlagiarismGuard")
        self.blacklist = blacklist

    def audit(self, text):
        if not self.blacklist:
            return "[通过]"
            
        # 第一道防线：正则硬匹配（完全一致的实体直接拦截）
        pattern = "|".join(re.escape(word) for word in self.blacklist)
        direct_matches = list(set(re.findall(pattern, text, re.IGNORECASE)))
        
        if direct_matches:
            return f"[拦截] 直接触发实体黑名单词汇：{', '.join(direct_matches)}。请立即更换这些名称。"

        suspicious_variants = []
        candidate_tokens = tokenize_cn_text(text, min_len=2, max_tokens=80)
        for token in candidate_tokens:
            if token in self.blacklist or len(token) > 8:
                continue
            for banned in self.blacklist[:120]:
                if abs(len(token) - len(banned)) > 2:
                    continue
                if token[:1] != banned[:1] and token[-1:] != banned[-1:]:
                    continue
                ratio = SequenceMatcher(None, token.lower(), banned.lower()).ratio()
                if ratio >= 0.74:
                    suspicious_variants.append((token, banned, round(ratio, 2)))
                    break

        if not suspicious_variants:
            return "[通过]"

        sampled_blacklist = self.blacklist[:50]
        blacklist_str = "、".join(sampled_blacklist)
        suspicious_text = "；".join(f"{token}≈{banned}({ratio})" for token, banned, ratio in suspicious_variants[:8])
        excerpt = token_safe_prune(text, max_chars=1200)
        prompt = f"""你是一名法务版权审核员。
        我们的实体黑名单包含（部分）：{blacklist_str}。
        本地规则已标记以下疑似变体：{suspicious_text}。
        【当前待审文本】：
        {excerpt}
        
        请仔细核查文本中是否使用了上述黑名单词汇的【变体、谐音或高度相似的换皮词】（例如：将“异火”改为“异焰”，将“萧炎”改为“萧火”）。
        只要存在任何疑似融梗、洗稿的换皮专有名词，请回复：[拦截] 并明确指出涉嫌换皮的词汇及修改建议。
        如果没有上述问题，请回复：[通过]。"""
        return generate_text(prompt, "You are a strict copyright auditor.", task_profile="reference_semantic")

class PlotCollisionAuditor(AuditorBase):
    def __init__(self, original_emotional_formula):
        super().__init__("PlotCollisionAuditor")
        self.original_formula = original_emotional_formula

    def audit(self, text):
        """核心情节防碰撞审查（防止桥段换皮）"""
        if not self.original_formula:
            return "[通过]"

        formula_tokens = tokenize_cn_text(self.original_formula, min_len=2, max_tokens=18)
        text_tokens = set(tokenize_cn_text(text, min_len=2, max_tokens=60))
        shared_tokens = [token for token in formula_tokens if token in text_tokens]
        if len(shared_tokens) <= 2:
            return "[通过]"

        prompt = f"""你是一个高级剧作查重官，专门负责防止“情节洗稿”和“结构融梗”。
        
        【原著底层情绪公式与核心冲突】：{self.original_formula}
        【本地重叠关键词】：{'、'.join(shared_tokens[:8])}
        
        【当前生成的文本】：
        {token_safe_prune(text, max_chars=1200)}
        
        任务：检查这段文本是否在情节事件上对原著进行了“像素级换皮”（例如：原著是退婚撕毁婚书，生成的是解约撕毁合同；或者具体发生的物理事件、核心道具、人物登场顺序高度雷同）。
        你可以继承其情绪张力和反差感，但【具体事件的外壳】绝不能高度雷同。
        
        如果发现“换皮融梗”嫌疑，请回复：[严重融梗警告] 并说明哪些情节照搬了套路，要求立即重新设计事件外壳。
        如果情节已经是完全独立原创的（外壳不同，内核相似），请回复：[通过]。"""
        return generate_text(
            prompt,
            "You are a plot collision and anti-plagiarism auditor.",
            task_profile="reference_semantic",
        )

class DynamicArcAuditor(AuditorBase):
    def __init__(self, current_chapter_idx, expected_outcome):
        super().__init__("DynamicArcAuditor")
        self.idx = current_chapter_idx
        self.expected = expected_outcome

    def audit(self, chapter_text, summary):
        prompt = f"""你是一个高级剧作分析官。
        【原定目标】：{self.expected}
        【实际摘要】：{summary}

        请判断实际走向是否发生了影响大结局的“原子级剧情坍塌”？
        注意：只要核心逻辑没断、伏笔没丢、关键人物存活，哪怕主角加了把刀、换了身衣服或发生轻微剧情偏离，都绝不要惊动全书大纲，必须宽容放行！
        除非发生了影响大结局且不可挽回的剧情断裂，才回复：[需重铸]；否则回复：[通过]。"""
        return generate_text(prompt, "You are a dramatic arc analyst.", task_profile="audit_short")

class StylisticCompositeAuditor(AuditorBase):
    def __init__(self, master_style):
        super().__init__("StylisticCompositeAuditor")
        self.master_style = master_style

    def audit(self, text):
        prompt = f"""你是一名专门负责网文“语感与呼吸感”的文字大师。
        核心风格：{self.master_style}
        
        任务：评估以下文本：
        1. 【节奏】：是否有 AI 式的长从句？
        2. 【多样性】：开头是否重复？
        3. 【废话】：是否有段尾总结？
        
        文本：{text}
        
        如果通过回复：[通过]；否则列出修改意见。"""
        return generate_text(prompt, "You are a master of stylistic rhythm.", task_profile="audit_short")

class SettingComplianceAuditor(AuditorBase):
    def __init__(self, world_setting, axioms):
        super().__init__("SettingComplianceAuditor")
        self.world_setting = world_setting
        self.compliance_rule = axioms.get("setting_absolute_compliance", "")

    def audit(self, text):
        prompt = f"""你是一名极其严苛的【世界观合规性审计师】。
        
        【核心世界观设定】：
        {self.world_setting}
        
        【设定合规公理】：
        {self.compliance_rule}
        
        【待审计文本】：
        {text}
        
        任务：检查文本是否违反了上述世界观设定。
        重点审查：
        1. 时代错位：古代背景是否出现了现代词汇或工业逻辑？
        2. 能力越权：角色的表现是否超出了世界观设定的力量体系范围？
        3. 设定矛盾：是否出现了与核心背景、文化禁忌或物理规则相冲突的内容？
        
        如果发现违规，请务必指出具体语句并给出修正建议。如果严丝合缝，回复：[通过]。"""
        return generate_text(prompt, "You are a world-building consistency validator.", task_profile="audit_medium")

class TruthCompositeAuditor(AuditorBase):
    def __init__(self, axioms):
        super().__init__("TruthCompositeAuditor")
        self.disguise_rule = axioms.get("strict_disguise_logic", "")
        self.setting_rule = axioms.get("setting_absolute_compliance", "")

    def audit(self, text, absolute_state, world_setting=""):
        if not absolute_state:
            return "[通过]"
        phys_state = absolute_state.get("physical_state", {})
        cog_state = absolute_state.get("cognitive_state", {})
        mask_state = absolute_state.get("identity_mask", "无")
        
        phys_str = " | ".join(f"{k}: {v}" for k, v in phys_state.items()) if phys_state else "无"
        cog_str = " | ".join(f"{k}: {v}" for k, v in cog_state.items()) if cog_state else "无"

        prompt = f"""你是因果真理与设定对齐校验机。
        【物理状态】：{phys_str}
        【身份伪装】：{mask_state}
        【认知边界】：{cog_str}
        【伪装底线】：{self.disguise_rule}
        【世界观红线】：{self.setting_rule}
        【核心背景参考】：{world_setting}
        
        任务：在确保因果一致性的同时，严查文本是否触碰了世界观红线（如：封杀非法词汇、阻止时代滑移）。
        
        文本：{text}
        
        如果通过回复：[通过]；若有穿帮或违背设定，指出具体点。"""
        return generate_text(
            prompt,
            "You are a strict causal and setting consistency validator.",
            task_profile="audit_medium",
        )

class MasterQualityAuditor(AuditorBase):
    def __init__(self, master_style, axioms, audience_type):
        super().__init__("MasterQualityAuditor")
        self.master_style = master_style
        self.axioms = axioms
        self.audience_type = audience_type

    def audit(self, text, absolute_state=None, world_setting="", due_clues=None, chapter_type="normal", dynamic_rules=""):
        style_rule = self.axioms.get("no_ai_flavor", "")
        demo_rule = self.axioms.get("demographic_quarantine", {}).get(self.audience_type, "")
        disguise_rule = self.axioms.get("strict_disguise_logic", "")
        setting_rule = self.axioms.get("setting_absolute_compliance", "")

        # 准备物理状态与认知边界背景
        phys_str = "无"
        cog_str = "无"
        mask_state = "无"
        if absolute_state:
            phys_state = absolute_state.get("physical_state", {})
            cog_state = absolute_state.get("cognitive_state", {})
            mask_state = absolute_state.get("identity_mask", "无")
            phys_str = " | ".join(f"{k}: {v}" for k, v in phys_state.items()) if phys_state else "无"
            cog_str = " | ".join(f"{k}: {v}" for k, v in cog_state.items()) if cog_state else "无"

        clue_context = "无"
        if due_clues:
            clue_context = "、".join([f"[{item['priority']}级] {item['desc']} (ID:{item['id']})" for item in due_clues])

        prompt = f"""你是一名工业级的【全维正文质检与信息提取员】。
        
        【待检文本】：
        {text}
        
        【极度重要的放行原则（最高优先级）】：
        请极度宽容！只要核心剧情、基本逻辑走向、主要人物行为合理、关键道具存在、且必须回收的伏笔没有出现【重大断层或缺失】，其他所有文风问题（如轻微AI味、不够有张力、排版不够完美、没有达到开幕雷击）统统必须直接判为 [通过] (passed: true)！
        严禁为了追求“极致的张力”或“极致的去AI化”而不断挑刺！系统时间宝贵，绝不能把时间浪费在无休止的打磨上！
        只有在发生“逻辑彻底断层”、“必须回收的伏笔完全没写”、“核心道具莫名消失”、“世界观严重穿帮（如古代出现手机）”这种【不可挽回的重大硬伤】时，才允许判为不通过 (passed: false)！
        
        【审计基准】（仅用于重大硬伤拦截，轻微瑕疵直接忽略）：
        1. AI Scent: 忽略轻微AI味，除非通篇都是机器总结废话。
        2. Stylistic: 忽略不够错落的问题，只要能读懂即可。
        3. Audience: 符合【{self.audience_type}】定位（规则：{demo_rule}）。
        4. Style: 符合大致风格（{self.master_style}）。
        5. Setting: 核心世界观（{world_setting}）。规则：{setting_rule}。严查严重出戏的现代词（古代背景）。
        6. Truth: 物理状态（{phys_str}），认知边界（{cog_str}），伪装身份（{mask_state}）。规则：{disguise_rule}。严防重大穿帮。
        {f"7. Dynamic Guard: 本文必须避开以下抄袭/融梗红线：{dynamic_rules}" if dynamic_rules else ""}
        
        【特邀审查项】：
        - 伏笔核销名单：{clue_context}
        - 章节类型：{chapter_type}
        
        任务：
        1. 对文本进行全维审计。记住：能过则过，严禁无病呻吟！
        2. 对每个维度都要给出结构化结论；如果不通过，必须精准锁定原文问题段落。
        3. 如果是楔子(prologue)，在 `hook` 节点判断是否极其无聊，但只要有基本冲突就放行。
        4. 顺便提取本章摘要、状态变更、新伏笔，以及【确实实质性回收】的伏笔ID。
        
        输出格式：你必须且只能输出严格的 JSON。
        JSON 字段：
        - "scent", "stylistic", "demographic", "style", "setting", "truth"{', "hook"' if chapter_type == 'prologue' else ''} 都必须是对象
        - 每个对象格式：
          {{
            "passed": true/false,
            "issue": "[通过]" 或者一句话指出重大问题,
            "spans": [
              {{
                "quote": "必须原样摘录正文中的问题句或问题段，长度控制在 20-120 字",
                "problem": "该片段的重大逻辑/事实硬伤是什么",
                "instruction": "如何在不改剧情走向的前提下修正"
              }}
            ]
          }}
        - 如果某项 passed=true，则 issue 固定为 "[通过]"，spans 为空数组
        - 每项 spans 最多给 2 个，禁止泛泛而谈，quote 必须能在原文中直接定位
        - "overall_passed": true/false (全部通过为true)
        - "summary": (审计通过时提取) 80-100字以内的极简摘要
        - "state_delta": (审计通过时提取) JSON，包含 physical_state, cognitive_state, identity_mask 的增量变化
        - "new_clue": (审计通过时提取) 格式为 "级别|内容"，如 "A|由于某事导致某人怀恨在心"
        - "resolved_ids": (数组) 请极度严苛地判断！只有正文明确写出了伏笔对应的解密或实质剧情时，才算回收！返回成功回收的纯数字ID数组；若都没明确回收，返回空数组 []。
        """
        return generate_text(
            prompt,
            "You are a strict industrial novel auditor and extractor. Output ONLY valid JSON.",
            task_profile="master_audit",
        )
