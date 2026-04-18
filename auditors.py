import re
from llm_client import generate_text
from logger import logger

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
        pattern = "|".join(re.escape(word) for word in self.blacklist)
        matches = re.findall(pattern, text)
        
        if matches:
            unique_matches = list(set(matches))
            feedback = f"发现 AI 典型烂梗词汇：{', '.join(unique_matches)}。请通过具体的物理动作、神态描写来替换这些空洞的形容词或过渡词。让文字更有‘人味’。"
            return feedback

        # 深度逻辑审计
        prompt = f"""你是一名文字洁癖专家，专门剔除 AI 写作中的“翻译腔”和“八股气”。
        请审查以下文本是否包含：
        1. 毫无意义的抒情总结（如：总之...，这就是...）。
        2. 结构化的排比句式（如：不仅...而且...还...）。
        3. 解释性的心理白描。
        
        文本：{text}
        
        如果发现任何 AI 痕迹，请指出具体句子并要求执行“去 AI 手术”。如果文字干脆利落、充满真实感，回复：[通过]。"""
        return generate_text(prompt, "You are a linguistic surgeon targeting AI artifacts.")

class DemographicAuditor(AuditorBase):
    def __init__(self, audience_type, axioms):
        super().__init__("DemographicAuditor")
        self.audience_type = audience_type
        self.rule = axioms["demographic_quarantine"].get(audience_type, "")

    def audit(self, text):
        prompt = f"请使用严格的标准审核以下文本是否符合【{self.audience_type}】的受众定位规则：{self.rule}\n文本：{text}\n如果不符合，请提出修改建议。如果符合，请回复：[通过]。"
        return generate_text(prompt, "You are a strict narrative auditor.")

class DisguiseLogicAuditor(AuditorBase):
    def __init__(self, axioms):
        super().__init__("DisguiseLogicAuditor")
        self.rule = axioms["strict_disguise_logic"]

    def audit(self, text):
        prompt = f"请使用多重物理/伪装逻辑锁审查机制审查以下文本：{self.rule}\n文本：{text}\n请仔细检查伪装是否穿帮，代词及物理特征是否合理。仅回复：[通过] 或 给出修改建议。"
        return generate_text(prompt, "You are a strict disguise logic auditor.")
        
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
        return generate_text(prompt, "You are Master Editor V6, specializing in the sharp, high-tension style of Fenghuo Xi Zhuhou.")

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
        return generate_text(prompt, "You are a merciless hook-and-tension auditor.")

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
        return generate_text(prompt, "You are an absolute objective truth validator.")

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
        return generate_text(prompt, "You are a structural rhythm master.")

class StructuralVarianceAuditor(AuditorBase):
    def __init__(self):
        super().__init__("StructuralVarianceAuditor")

    def audit(self, text):
        prompt = f"""你是一名句法变异审计师。
        任务：检查以下文本段落开头。是否存在连续三个及其以上段落使用相同的主语或连词起手？
        是否存在“动作 -> 感受 -> 总结”的固定 AI 模板？
        
        文本：{text}
        
        如果发现结构僵化，指出具体点并要求变异。如果起手错落有致，回复：[通过]。"""
        return generate_text(prompt, "You are a syntax variance auditor.")

class DeExplanationAuditor(AuditorBase):
    def __init__(self):
        super().__init__("DeExplanationAuditor")

    def audit(self, text):
        prompt = f"""你是一名文字手术医生，专门切除段尾总结性陈述（画蛇添足）。
        （例如：“这就是他...的原因”、“这一刻，他明白了...”、“这就是命运对他的...”）。
        
        文本：{text}
        
        如果发现此类总结，请要求直接切除，让文字停在动作最高潮。如果干净利落，回复：[通过]。"""
        return generate_text(prompt, "You are a linguistic surgeon.")

class PlagiarismGuard(AuditorBase):
    def __init__(self, blacklist):
        super().__init__("PlagiarismGuard")
        self.blacklist = blacklist

    def audit(self, text):
        if not self.blacklist:
            return "[通过]"
        pattern = "|".join(re.escape(word) for word in self.blacklist)
        if not re.search(pattern, text, re.IGNORECASE):
            return "[通过]"

        blacklist_str = "、".join(self.blacklist)
        prompt = f"""你是一名法务版权审核员。
        禁止出现原著专有名词（及其变体、谐音）：{blacklist_str}。
        如果发现违规，回复：[拦截] 并指出词汇。如果安全，回复：[通过]。"""
        return generate_text(prompt, "You are a strict copyright auditor.")

class DynamicArcAuditor(AuditorBase):
    def __init__(self, current_chapter_idx, expected_outcome):
        super().__init__("DynamicArcAuditor")
        self.idx = current_chapter_idx
        self.expected = expected_outcome

    def audit(self, chapter_text, summary):
        prompt = f"""你是一个高级剧作分析官。
        【原定目标】：{self.expected}
        【实际摘要】：{summary}
        
        判断实际走向是否发生了不可逆的“大纲偏离”？
        如果影响后续逻辑，回复：[需重铸]；否则回复：[通过]。"""
        return generate_text(prompt, "You are a dramatic arc analyst.")

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
        return generate_text(prompt, "You are a master of stylistic rhythm.")

class TruthCompositeAuditor(AuditorBase):
    def __init__(self, axioms):
        super().__init__("TruthCompositeAuditor")
        self.disguise_rule = axioms.get("strict_disguise_logic", "")

    def audit(self, text, absolute_state):
        if not absolute_state:
            return "[通过]"
        phys_state = absolute_state.get("physical_state", {})
        cog_state = absolute_state.get("cognitive_state", {})
        mask_state = absolute_state.get("identity_mask", "无")
        
        phys_str = " | ".join(f"{k}: {v}" for k, v in phys_state.items()) if phys_state else "无"
        cog_str = " | ".join(f"{k}: {v}" for k, v in cog_state.items()) if cog_state else "无"

        prompt = f"""你是因果真理校验机。
        【物理状态】：{phys_str}
        【身份伪装】：{mask_state}
        【认知边界】：{cog_str}
        【伪装底线】：{self.disguise_rule}
        
        任务：检查穿帮、越权和代词逻辑。
        
        文本：{text}
        
        如果通过回复：[通过]；否则指出穿帮点。"""
        return generate_text(prompt, "You are a strict causal consistency validator.")
