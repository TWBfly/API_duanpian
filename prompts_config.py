# ==========================================
# 工业级硬核创作规范 (Hardcore Style Guide)
# ==========================================

from novel_utils import infer_setting_mode


CORE_STYLE_HARDCORE_TEMPLATE = """
【题材/时代约束】
{era_rules}
- 禁止：现代词汇滑移（特别是古代/玄幻题材禁止工业/科学词）。

【创作核心】
- 张力：采用 3-5 字短句与长句交错，制造突兀节奏感。
- 去AI总结：章末严禁任何感慨、评价或画外音，必须戛然而止在具体动作或画面上。
- 展示而非叙述：用嗅觉、触觉等细节取代抽象词（如“绝望”、“极其”），但严禁细节堆砌（限制在 10% 以内）。
- 前100字：必须开幕雷击，直接切入核心冲突或悬念。

【负面约束】
- 禁用词：不仅如此、总之、随着时间推移、说时迟那时快、已经是、这才是。
- 字数：本章必须 2000 字以上，通过剧情波折而非水字数达成。
"""


def build_core_style_guide(setting=None):
    setting = setting or {}
    world_setting = str(setting.get("world_setting", ""))
    setting_mode = infer_setting_mode(world_setting, default="ancient_fantasy")
    if setting_mode == "modern_realistic":
        era_rules = """- 当前背景判定：都市现实/职场校园/现代生活。必须遵守现实社会逻辑，严禁超自然、修仙词、科幻词；可以使用真实世界常见地名与机构名，但禁止论文腔、产品说明腔、系统公告腔。
- 起名约束：现代现实题材必须像真实世界会出现的自然命名，禁止硬套玄幻地名。"""
    else:
        era_rules = """- 当前背景判定：古代/玄幻/修仙/灵异/穿越古代线。严禁出现任何赛博朋克、科幻、星际或现代高科技词汇（如：AI、程序、数据流、维度、位面、奇点、降维打击、锚点、逻辑武器、虚拟现实、基因锁、纳米、量化、优化、模块）。
- 当前背景判定：古代/玄幻/修仙/灵异/穿越古代线。严禁使用现代科学/物理解释口吻（如：重力加速度、实验、样本、观测、反馈机制）。
- 起名约束：古代/玄幻背景遵循中式叙事美学，优先使用“斋、阁、坊、塔、洞、泉、庐、坞、亭”等。"""
    return CORE_STYLE_HARDCORE_TEMPLATE.format(era_rules=era_rules)


CORE_STYLE_HARDCORE = build_core_style_guide({})

PROLOGUE_PROMPT_TEMPLATE = """【prompt：【
- 作为一名职业网文大师，你的任务是创作一篇引人入胜的[楔子]。

{guide}
- 楔子必须：抛出终极悬念，钩住读者，严禁平淡。

{background_info}
"""

CHAPTER_PROMPT_TEMPLATE = """【prompt：【
- 作为一名职业网文大师，你的任务是创作引人入胜的第{chapter_num}章。

{summary_prefix}
{guide}
- 必须：承载上下文逻辑，开头自然承接，尾部平滑过渡。

{background_info}
"""

EPILOGUE_PROMPT_TEMPLATE = """【prompt：【
- 作为一名职业网文大师，你的任务是创作全书终章：第{chapter_num}章大结局。

{summary_prefix}
{guide}
- 必须：爆发终极冲突，揭开核心真相，清算主要反派，回收核心伏笔，完成主角命运定格。
- 严禁：留下下一章钩子、引出新主线、使用“新的风暴刚刚开始”等续写口吻。

{background_info}
"""

CONTINUITY_BLOCK_TEMPLATE = """
【连续性档案】
- 背景：{background_label} | 主频道：{channel}
- 已登场：{appeared_characters}
- 最近剧情：{recent_plots}

【风险审计】
- 逻辑断层：{logic_breaks}
- 天降嫌疑：{sudden_appearances}

【执行指令】
{rewrite_instructions}
"""

NEXT_CHAPTER_TRANSITION_TEMPLATE = """
- 必须：结尾只负责把人物、线索或风险自然推送到下一章，不得提前展开下一章的完整事件链。
- 下章仅作转场锚点：{next_chapter_outline}
"""

TERMINAL_CHAPTER_CLOSURE_TEMPLATE = """
【终章闭环硬约束】
- 本章是全书最后一章，不存在下一章。
- 必须在正文内完成：终极冲突、真相揭示、伏笔回收、反派清算、主角命运定格。
- 结尾必须落在确定性的最终画面或最终动作上，严禁新伏笔、续集钩子、未决主线。
"""

FINAL_EXECUTION_TEMPLATE = """】】

【本章大纲】
{chapter_outline}

{transition_block}

---
请开始创作{chapter_name}正文（要求字数 2000+，{title_instr}，笔触遵循“{style_requirement}”）：
"""
