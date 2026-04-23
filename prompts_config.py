import os
import re
from novel_utils import infer_setting_mode

# ==========================================
# 工业级提示词发动机 V3 (Template Driver)
# ==========================================

# 定位模板库路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROMPT_LIB_BASE = os.path.join(PROJECT_ROOT, ".agent/skills/novel_evolution_engine/scripts/dp_promet")

TEMPLATES_CATALOG = {
    "prologue": "00_楔子提示词模板.md",
    "first_chapter": "01_第一章提示词模板.md",
    "middle_chapter": "02_第二章-第九章提示词模板.md",
    "epilogue": "03_结局提示词模板.md"
}

def load_lib_template(category):
    """从中心化模板库加载 MD 内容"""
    filename = TEMPLATES_CATALOG.get(category)
    if not filename:
        return ""
    path = os.path.join(PROMPT_LIB_BASE, filename)
    if not os.path.exists(path):
        return f"⚠️ [Config Error] Template source not found at {path}"
    
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # 提取核心 MD 块
    match = re.search(r'```md.*?id=".*?"\n(.*?)\n```', content, re.DOTALL)
    if match:
        return match.group(1).strip()
    return content.strip()

def build_era_rules(setting=None):
    """保留原有的时代背景动态判定智性逻辑"""
    setting = setting or {}
    world_setting = str(setting.get("world_setting", ""))
    setting_mode = infer_setting_mode(world_setting, default="ancient_fantasy")
    
    if setting_mode == "modern_realistic":
        return """【题材：现代现实】
- 当前判定：都市/生活。必须遵守物理与现实逻辑，严禁玄幻修仙词。
- 严禁出现：灵力、位面、识海、仙帝、因果线（除非作为文学修辞）。"""
    else:
        return """【题材：古代/玄幻/修仙】
- 当前判定：非现代。严禁出现任何高科技或现代科学解释词。
- 严禁出现：逻辑武器、降维打击、优化、数据流、纳米、量子、反应机制、基因。"""

def get_v3_prompt_bundle(idx, total_chapters, title, body, setting=None, prev_data=None, next_data=None):
    """
    全系统唯一提示词导出入口，融合 V3 模板与动态大纲
    """
    # 1. 判定章节类型
    from novel_utils import chapter_type_for_index
    category = chapter_type_for_index(idx, total_chapters)
    
    # 2. 加载基干模板
    template_raw = load_lib_template(category)
    if not template_raw:
        return f"Error: Template for {category} missing."

    # 3. 构建背景约束
    era_rules = build_era_rules(setting)
    
    # 4. 解析大纲详情 (对齐新模板占位符)
    details = {
        "scene": "未指定",
        "characters": "未指定",
        "act1": "起", "act2": "承", "act3": "转", "act4": "合"
    }
    # 尝试抽取
    for key, p in {"scene": r'\*\*场景[：:]\*\*\s*(.*)', "characters": r'\*\*人物[：:]\*\*\s*(.*)'}.items():
        m = re.search(p, body)
        if m: details[key] = m.group(1).strip()

    # 5. 执行变量替换
    res = template_raw
    replacements = {
        "{这里填你的楔子标题}": title,
        "{这里填第一章标题}": title,
        "{这里填本章标题}": title,
        "{这里填结局标题}": title,
        "{这里填场景}": details["scene"],
        "{这里填人物}": details["characters"],
        "{这里填核心剧情}": body,
        "{这里填第一幕}": "展开冲突",
        "{这里填第二幕}": "交锋升级",
        "{这里填第三幕}": "结果落地",
        "{这里填结局场景}": details["scene"],
        "{这里填结局人物}": details["characters"],
        "{这里填结局核心剧情}": body,
        "{这里填结局第一幕}": "全面爆发",
        "{这里填结局第二幕}": "最终决战",
        "{这里填结局第三幕}": "尘埃落定",
        "{背景：按本书背景执行}": era_rules,
        "{这里填全书最核心的矛盾，例如：主角必须在彻底失控前杀死真凶并夺回被篡改的命格}": "主角必须在迷雾中找回真相并完成命运的反杀。"
    }

    # 上下章承接
    if prev_data:
        replacements.update({
            "{这里填上一章标题}": prev_data.get('title', '前一章'),
            "{这里填上一章核心剧情}": prev_data.get('body', '')[:200] + "...",
        })
    if next_data:
        replacements.update({
            "{这里填下一章标题}": next_data.get('title', '下一章'),
            "{这里填下一章核心剧情}": next_data.get('body', '')[:200] + "...",
        })

    for k, v in replacements.items():
        res = res.replace(k, str(v))

    # 6. 追加提示词末尾的指令，确保风格统一
    res += f"\n\n---\n请开始创作{title}正文（要求字数 2000+，采用长短句张力风，绝对禁止 AI 味总结）："
    
    return res

# 保留旧变量占位以防其他遗留脚本崩溃，但功能已指向新引擎
CORE_STYLE_HARDCORE = "Deprecated: Use get_v3_prompt_bundle instead."
PROLOGUE_PROMPT_TEMPLATE = "{bundle}"
CHAPTER_PROMPT_TEMPLATE = "{bundle}"
EPILOGUE_PROMPT_TEMPLATE = "{bundle}"
FINAL_EXECUTION_TEMPLATE = "{bundle}"
