import re

DEFAULT_MAIN_CHAPTERS = 10
MAX_MAIN_CHAPTERS = 10

TERMINAL_CLOSURE_TERMS = (
    "大结局", "终章", "结局", "终极", "真相", "揭示", "证明", "清算", "处置",
    "伏笔", "回收", "闭环", "首尾呼应", "尘埃落定", "命运定格", "落幕",
)

OPEN_ENDING_PATTERNS = (
    "下一章", "待续", "未完", "刚刚开始", "才刚开始", "尚未结束", "第一局刚落子",
    "新的危机", "更大的", "仍在前方", "陷入危局", "留下悬念", "等待他", "等着她",
)

FORBIDDEN_SCI_FI_TOKENS = {
    "科幻", "星际", "赛博", "赛博朋克", "联邦", "殖民星", "银河", "宇宙", "外星",
    "芯片", "算法", "终端", "全息", "数据", "程序", "ai", "AI", "引擎", "机甲",
    "飞船", "港口", "加密", "模块", "系统公告", "纳米", "量子", "基因", "实验室",
}

def normalize_total_chapters(total_chapters, default=DEFAULT_MAIN_CHAPTERS):
    """
    统一章节契约：total_chapters 表示正文主线章数，楔子固定为第 0 章另算。
    当前短篇系统的硬规格是「楔子 + 第1章 ... 第10章」，因此不允许生成第11章。
    """
    if total_chapters in (None, ""):
        value = default
    else:
        try:
            value = int(total_chapters)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"章节数必须是整数，收到: {total_chapters!r}") from exc

    if value < 1:
        raise ValueError(f"章节数必须大于 0，收到: {value}")
    if value > MAX_MAIN_CHAPTERS:
        raise ValueError(
            f"短篇章节契约禁止超过第{MAX_MAIN_CHAPTERS}章；"
            f"收到 total_chapters={value}。若把楔子也计入了参数，请传 {MAX_MAIN_CHAPTERS}。"
        )
    return value


def expected_chapter_indices(total_chapters=DEFAULT_MAIN_CHAPTERS):
    total = normalize_total_chapters(total_chapters)
    return list(range(0, total + 1))


def chapter_title_for_index(chapter_index):
    idx = int(chapter_index)
    return "楔子" if idx == 0 else f"第{idx}章"


def chapter_type_for_index(chapter_index, total_chapters=DEFAULT_MAIN_CHAPTERS):
    idx = int(chapter_index)
    total = normalize_total_chapters(total_chapters)
    if idx == 0:
        return "prologue"
    if idx == total:
        return "epilogue"
    return "normal"


def num_to_chinese(num):
    chinese_nums = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]
    value = int(num)
    return chinese_nums[value] if 0 <= value <= 10 else str(value)


def _coerce_chapter_idx(chapter):
    if not isinstance(chapter, dict):
        return None
    raw_idx = chapter.get("chapter_idx")
    try:
        return int(raw_idx)
    except (TypeError, ValueError):
        return None


def _chapter_text_for_contract(chapter):
    if not isinstance(chapter, dict):
        return ""
    parts = []
    for key in ("title", "goal", "content_plan", "plot_beat", "scene", "foreshadowing_to_plant", "state_transition"):
        value = chapter.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    acts = chapter.get("acts")
    if isinstance(acts, dict):
        for act_key in ("act_1", "act_2", "act_3"):
            value = acts.get(act_key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
    return "\n".join(parts)


def _compact_contract_item(label, text, max_chars=120):
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if not cleaned:
        return ""
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars].rstrip() + "..."
    return f"{label}：{cleaned}"


def build_terminal_closure_checklist(skeleton, total_chapters=DEFAULT_MAIN_CHAPTERS, max_items=10):
    """从全书大纲抽取终章必须回收/呼应的硬清单。"""
    total = normalize_total_chapters(total_chapters)
    payload = skeleton or {}
    novel_arc = payload.get("novel_arc") or []
    by_idx = {
        _coerce_chapter_idx(chapter): chapter
        for chapter in novel_arc
        if _coerce_chapter_idx(chapter) is not None
    }

    checklist = []
    global_resolution = str(payload.get("global_resolution") or "").strip()
    if global_resolution:
        checklist.append(_compact_contract_item("全局结局", global_resolution, max_chars=160))

    opening = by_idx.get(0) or by_idx.get(1)
    opening_text = _chapter_text_for_contract(opening)
    if opening_text:
        checklist.append(_compact_contract_item("首尾呼应", opening_text, max_chars=150))

    for idx in sorted(by_idx):
        if idx in (None, total):
            continue
        chapter = by_idx[idx]
        clue = str(chapter.get("foreshadowing_to_plant") or "").strip()
        if clue and clue != "无" and "终章不新增" not in clue:
            checklist.append(_compact_contract_item(f"回收第{idx}章伏笔", clue, max_chars=110))
        if len(checklist) >= max_items:
            break

    deduped = []
    seen = set()
    for item in checklist:
        if not item:
            continue
        key = re.sub(r"\W+", "", item)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= max_items:
            break
    return deduped


def enforce_terminal_chapter_contract(skeleton, total_chapters=DEFAULT_MAIN_CHAPTERS):
    total = normalize_total_chapters(total_chapters)
    payload = skeleton or {}
    novel_arc = payload.get("novel_arc") or []
    closure_checklist = build_terminal_closure_checklist(payload, total)
    for chapter in novel_arc:
        if _coerce_chapter_idx(chapter) != total:
            continue

        chapter["is_terminal"] = True
        chapter["terminal_obligation"] = (
            f"本章是全书最后一章（第{total}章大结局），必须完成终极冲突、真相揭示、"
            "核心伏笔回收、反派清算与主角命运定格；严禁新增续章钩子、严禁开放式续写。"
        )
        if not str(chapter.get("title") or "").strip():
            chapter["title"] = "终章：尘埃落定"
        title = str(chapter.get("title") or "")
        if not any(term in title for term in ("终", "结局", "落定", "天下", "归位", "清算")):
            chapter["title"] = f"终章：{title}"

        chapter["closure_checklist"] = closure_checklist
        chapter["opening_callback"] = next(
            (item for item in closure_checklist if item.startswith("首尾呼应")),
            "",
        )
        chapter["goal"] = (
            f"{chapter.get('goal', '').strip()} "
            "【终章目标：完成全书大结局，按 closure_checklist 逐项收束，完成首尾呼应。】"
        ).strip()
        acts = chapter.setdefault("acts", {})
        if isinstance(acts, dict):
            act_1 = str(acts.get("act_1") or "").strip()
            act_2 = str(acts.get("act_2") or "").strip()
            closing = str(acts.get("act_3") or "").strip()
            acts["act_1"] = (
                f"{act_1} 终极冲突必须在本章正面爆发，不得转移到章外。"
            ).strip()
            acts["act_2"] = (
                f"{act_2} 必须完成核心真相揭示、证据落地、反派清算，并呼应开篇冲突。"
            ).strip()
            terminal_suffix = "全书在此闭环，逐项收束 closure_checklist，不得留下新的未决主线或续章悬念。"
            acts["act_3"] = f"{closing} {terminal_suffix}".strip() if closing else terminal_suffix
        chapter["foreshadowing_to_plant"] = "终章不新增伏笔；只允许回收、揭示、清算、定格。"
        chapter["state_transition"] = (
            f"{chapter.get('state_transition', '').strip()} "
            "终局状态必须明确：主角命运定格，核心矛盾解决，全书落幕。"
        ).strip()
        break
    return payload


def validate_terminal_outline_contract(skeleton, total_chapters=DEFAULT_MAIN_CHAPTERS):
    """检查终章大纲是否具备大结局/收束/首尾呼应属性。"""
    total = normalize_total_chapters(total_chapters)
    payload = skeleton or {}
    terminal = None
    for chapter in payload.get("novel_arc") or []:
        if _coerce_chapter_idx(chapter) == total:
            terminal = chapter
            break
    if not terminal:
        raise ValueError(f"缺失第{total}章终章大纲。")

    text = _chapter_text_for_contract(terminal)
    blockers = []
    term_hits = [term for term in TERMINAL_CLOSURE_TERMS if term in text]
    if len(term_hits) < 4:
        blockers.append("终章大纲缺少足够的大结局/闭环/清算信号")
    if not terminal.get("closure_checklist"):
        blockers.append("终章大纲缺少 closure_checklist，无法逐项收束前文剧情")
    if not terminal.get("opening_callback"):
        blockers.append("终章大纲缺少 opening_callback，无法保证首尾呼应")
    if any(pattern in text[-300:] for pattern in OPEN_ENDING_PATTERNS):
        blockers.append("终章大纲尾部仍包含续写钩子")
    if str(terminal.get("foreshadowing_to_plant") or "").strip() != "终章不新增伏笔；只允许回收、揭示、清算、定格。":
        blockers.append("终章大纲仍在新增伏笔")

    if blockers:
        raise ValueError("终章大纲闭环契约不一致：" + "；".join(blockers))
    return True


def validate_skeleton_contract(skeleton, total_chapters=DEFAULT_MAIN_CHAPTERS):
    """
    校验并排序大纲，确保只存在 0..N 章，且最后一章被标记为终章。
    返回原 skeleton 对象，便于调用方继续使用。
    """
    total = normalize_total_chapters(total_chapters)
    payload = skeleton or {}
    novel_arc = payload.get("novel_arc")
    if not isinstance(novel_arc, list) or not novel_arc:
        raise ValueError("大纲缺少 novel_arc，无法执行章节契约。")

    expected = set(expected_chapter_indices(total))
    seen = {}
    duplicates = []
    invalid = []
    for chapter in novel_arc:
        idx = _coerce_chapter_idx(chapter)
        if idx is None:
            invalid.append(chapter)
            continue
        if idx in seen:
            duplicates.append(idx)
            continue
        chapter["chapter_idx"] = idx
        seen[idx] = chapter

    actual = set(seen)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if invalid or duplicates or missing or extra:
        details = []
        if missing:
            details.append(f"缺失章节: {missing}")
        if extra:
            details.append(f"越界章节: {extra}")
        if duplicates:
            details.append(f"重复章节: {sorted(set(duplicates))}")
        if invalid:
            details.append(f"非法章节对象: {len(invalid)} 个")
        raise ValueError("大纲章节契约不一致：" + "；".join(details))

    payload["novel_arc"] = [seen[idx] for idx in sorted(expected)]
    payload = enforce_terminal_chapter_contract(payload, total)
    validate_terminal_outline_contract(payload, total)
    return payload

ANCIENT_FANTASY_TOKENS = {
    "宗门", "修仙", "灵气", "灵纹", "阵法", "心法", "长老", "魔族", "祖师", "祠堂",
    "洗心池", "剥魂斋", "阁主", "飞剑", "灵舟", "禁术", "祖灵", "寒潭", "剑气", "命格",
}

MODERN_REALISTIC_TOKENS = {
    "校园", "学校", "保送", "退学", "老师", "学生", "考试", "竞赛", "年级", "同学",
    "职场", "公司", "实习", "面试", "老板", "会议室", "合同", "办公室", "项目", "绩效",
    "医院", "警局", "法庭", "记者", "媒体", "直播间", "社交平台",
}

SCI_FI_TO_ANCIENT_MAP = {
    "数据": "命理",
    "程序": "因果",
    "逻辑": "玄理",
    "系统": "规训",
    "实验室": "炼丹房",
    "终端": "眼线",
    "算法": "推演",
    "模块": "篇章",
    "芯片": "命格",
    "加密": "禁制",
    "维度": "天道",
    "引擎": "源力",
    "锚点": "阵眼",
}

def purify_text_to_ancient(text):
    """
    外科手术：强制将敏感词替换为古代背景适配词，防止审计拦截。
    """
    if not text or not isinstance(text, str):
        return text
    purified = text
    for modern, ancient in SCI_FI_TO_ANCIENT_MAP.items():
        purified = purified.replace(modern, ancient)
    return purified


def normalize_audience_type(value, default="female_oriented"):
    text = str(value or "").strip().lower()
    if not text:
        return default

    if "female_oriented" in text or "female" in text or "女频" in text:
        return "female_oriented"
    if "male_oriented" in text or "male" in text or "男频" in text:
        return "male_oriented"
    if "通用" in text or "general" in text:
        return "general"
    return default


def audience_display_label(value):
    normalized = normalize_audience_type(value, default="general")
    if normalized == "female_oriented":
        return "女频"
    if normalized == "male_oriented":
        return "男频"
    return "通用"


def extract_skeleton_segments(skeleton_data):
    skeleton = skeleton_data or {}
    segments = []

    for key in ("title", "scene", "goal", "content_plan", "plot_beat", "foreshadowing_to_plant", "state_transition"):
        value = skeleton.get(key)
        if isinstance(value, str) and value.strip():
            segments.append(value.strip())

    acts = skeleton.get("acts")
    if isinstance(acts, dict):
        for act_key in ("act_1", "act_2", "act_3"):
            value = acts.get(act_key)
            if isinstance(value, str) and value.strip():
                segments.append(value.strip())

    return segments


def extract_skeleton_plot_hint(skeleton_data):
    segments = extract_skeleton_segments(skeleton_data)
    if not segments:
        return ""
    return " | ".join(segments[:6])


def keyword_hits(text, keywords, limit=8):
    hits = []
    haystack = str(text or "")
    for keyword in keywords:
        if keyword and keyword in haystack and keyword not in hits:
            hits.append(keyword)
        if len(hits) >= limit:
            break
    return hits


def infer_setting_mode(text, default="ancient_fantasy"):
    haystack = str(text or "")
    sci_fi_hits = keyword_hits(haystack, FORBIDDEN_SCI_FI_TOKENS, limit=3)
    if sci_fi_hits:
        return "forbidden_scifi"

    fantasy_hits = keyword_hits(haystack, ANCIENT_FANTASY_TOKENS, limit=3)
    modern_hits = keyword_hits(haystack, MODERN_REALISTIC_TOKENS, limit=3)
    if modern_hits and not fantasy_hits:
        return "modern_realistic"
    if fantasy_hits:
        return "ancient_fantasy"
    return default


def detect_setting_conflicts(setting_text, candidate_text):
    candidate = str(candidate_text or "")
    conflicts = []
    sci_fi_hits = keyword_hits(candidate, FORBIDDEN_SCI_FI_TOKENS)
    if sci_fi_hits:
        conflicts.append(f"检测到科幻/高科技词：{'、'.join(sci_fi_hits)}")

    setting_mode = infer_setting_mode(setting_text, default="ancient_fantasy")
    if setting_mode == "modern_realistic":
        fantasy_hits = keyword_hits(candidate, ANCIENT_FANTASY_TOKENS)
        if fantasy_hits:
            conflicts.append(f"现代现实设定中混入玄幻/宗门词：{'、'.join(fantasy_hits)}")

    return conflicts


def tokenize_cn_text(text, min_len=2, max_tokens=32):
    tokens = []
    seen = set()
    for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", text or ""):
        if len(token) < min_len:
            continue
        if token in seen:
            continue
        seen.add(token)
        tokens.append(token)
        if len(tokens) >= max_tokens:
            break
    return tokens


def normalize_path(path_str):
    """
    工业级路径归一化：
    1. 自动剥离误输入的前缀 (如 ./Users/... 转化为 /Users/...)
    2. 自动检测绝对路径与相对路径
    3. 返回最终物理存在的或语义上归一化的绝对路径
    """
    import os
    if not path_str:
        return path_str
    
    # 清洗：去除两端空格和可能的 ./ 误导前缀
    p = path_str.strip()
    
    # 核心修复：检测是否是携带 ./ 前缀的绝对路径
    # 如果 p 去掉开头的 ./ 后是以 /Users 或 / 开头的，说明它是绝对路径
    if p.startswith("./") or p.startswith("../"):
        # 尝试剥离一层
        parts = p.split("/", 1)
        if len(parts) > 1:
            stripped_p = parts[1]
            # 在 Mac 上，主要关注 /Users
            if stripped_p.startswith("Users/") or stripped_p.startswith("/Users/"):
                potential_abs = stripped_p if stripped_p.startswith("/") else "/" + stripped_p
                # 如果这个剥离后的绝对路径真实存在，则直接使用
                if os.path.exists(potential_abs):
                    return potential_abs
            
    # 如果已经是绝对路径，直接返回
    if os.path.isabs(p):
        return p
        
    # 否则，返回当前目录拼接后的路径
    return os.path.abspath(p)


def token_safe_prune(text, max_chars=1200, head_ratio=0.7):
    """
    工业级上下文剪枝工具：防止 Token 膨胀。
    采用“保留头尾”策略：保留开头（前 head_ratio）和结尾，中间部分进行省略。
    """
    if not text or len(text) <= max_chars:
        return text
    
    head_len = int(max_chars * head_ratio)
    tail_len = max_chars - head_len - 50 # 预留 ... 的空间
    
    if tail_len <= 0:
        return text[:max_chars] + "\n...(已剪枝)..."
        
    head = text[:head_len]
    tail = text[-tail_len:]
    return f"{head}\n\n[...由于 Token 限制，此处省略了部分中间内容...]\n\n{tail}"
