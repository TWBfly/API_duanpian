from llm_client import generate_text, DEFAULT_MODEL
import json
import re
import os
import hashlib
from logger import logger

from novel_utils import (
    ANCIENT_FANTASY_TOKENS,
    FORBIDDEN_SCI_FI_TOKENS,
    MODERN_REALISTIC_TOKENS,
    detect_setting_conflicts,
    infer_setting_mode,
    keyword_hits,
    normalize_audience_type,
    normalize_path,
    purify_text_to_ancient,
)

class GenesisDirector:
    """创世大脑：推演设定并生成男/女频以及核心世界观"""
    def __init__(self):
        self.genesis_prompt = """你是一个“世界观创世引擎”（Genesis API）。
给定一个极简的灵感火花或书名，你必须完全自主推演出以下这本小说的核心设定。

【背景设定丰富度（Richer Setting）】：
- 必须要进行“自洽扩容”：在原著或灵感基础上，深度模拟推演出该世界的衣食住行、建筑风格、礼仪规范及社会阶层（确保泥土感，严禁苍白虚浮）。
- 严禁：赛博朋克、科幻、星际、AI感很重的内容。
- 黑名单词汇（严禁出现）：科幻、星际、AI、程序、物理宇宙、数据流、锚点、外星人、银河系、宇宙、时间旅行、平行世界、维度、位面、逻辑武器、科幻修仙、缸中之脑、直播、天道、奇点、赛博、赛博朋克、赛博维京、熵增、降维打击。
- 推演方向（必须）：都市现实、职场校园、现代生活、实用主义、古代玄幻、古代修仙、古代灵异（中式恐怖/悬疑）、都市现代高武、都市修仙、民国灵异（中式恐怖/悬疑）、穿越（古穿今/今穿古）。

【起名美学要求（Mandatory）】：
- 必须：遵循中式叙事美学，使用“斋、阁、坊、塔、洞、泉、庐、坞、亭”等后缀。
- 示例：将“记忆提取中心”转化为“洗心池”或“剥魂斋”；将“监控中心”转化为“观风阁”。

必须要以强格式 JSON 输出！不要有解释性文本！

灵感/书名：{title_seed}

必须要推演的关键字段：
1. "audience_type": "男频" 或 "女频"。如果是混合风格，请注明比例，如 "女频占比70%，男频占比30%"。
2. "narrative_kernel": 根据分类选择核心爽点/虐点逻辑（例如：男频为“无敌流/智斗/逆袭”，女频为“追妻火葬场/马甲流/独宠”）。
3. "master_style": 推荐的最匹配的主力文风门派。
4. "world_setting": 详细的背景世界观与力量体系描述（遵循【背景硬约束】，确保泥土感与古朴张力）。
5. "main_character": {{"name": "...", "base_personality": "...", "initial_inventory": "..."}}。
6. "initial_conflict": 剧情即将爆发的【楔子矛盾点】。

请立刻返回JSON:
"""

    def generate_genesis_setting(self, title_seed):
        """Path 2: 根据背景设定扩展生成世界观"""
        print(f"\n🌍 [Genesis 创世引擎] 正在为《{title_seed}》推演宏大世界观与受众模型...")
        prompt = self.genesis_prompt.format(title_seed=title_seed)
        
        max_retries = 3
        last_exception = None
        for attempt in range(max_retries):
            response = generate_text(
                prompt,
                "You are the Genesis God Engine. Output purely valid JSON.",
                task_profile="genesis_json",
                model=DEFAULT_MODEL,
            )
            try:
                return self._parse_json(response, fallback_kind="setting", seed_hint=title_seed, raise_exc=True)
            except Exception as e:
                last_exception = e
                print(f"⚠️ [Genesis] 尝试 {attempt + 1}/{max_retries} 失败: {e}")
                
        print(f"⚠️ [Genesis] JSON 推演彻底失败 ({last_exception})，将下发默认保险兜底层。")
        return self._build_fallback_payload("setting", title_seed, response)

    def analyze_reference_essence(self, file_paths):
        """Path 1: 深度分析原著精髓并列出实体黑名单"""
        import jieba.analyse
        if isinstance(file_paths, str):
            file_paths = [file_paths]
            
        combined_content = ""
        full_content = ""
        for path in file_paths:
            path = normalize_path(path)
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                    full_content += content
                    combined_content += content[:5000] # 采样前5000字供文风分析
            else:
                print(f"⚠️ [Genesis] 无法读取文件：{path}")
        
        print(f"\n🧬 [Essence 分析] 正在从 {len(file_paths)} 本原著中提取核心 DNA (包含全局实体抽取)...")
        
        # 提取全局高频专有名词（实体黑名单候选），解决 5000 字采样限制
        top_entities = jieba.analyse.extract_tags(full_content, topK=100, allowPOS=('nr', 'ns', 'nt', 'nz', 'n'))
        top_entities_str = "、".join(top_entities)
        
        essence_prompt = f"""你是一个文学DNA分析专家。请阅读以下文本（截取），提取其灵魂精髓。

【原著文本(前5000字)】：
{combined_content}

【原著全局高频实体(NLP辅助提取)】：
{top_entities_str}

你必须提交一份高度精炼的“DNA报告”，并以 JSON 格式输出：
1. "audience_type": 原著的受众定位（必须识别为“女频”或“男频”）。如果原著是女频，仿写就是女频；如果是男频，仿写就是男频。若极难识别，请注明为“女频占比70%，男频占比30%”。
2. "emotional_formula": 原著最核心的底层冲突与情绪拉扯公式（例如：上位者失控/克苏鲁式绝望）。
3. "narrative_pacing": 叙事节奏特征（如：极简短句/华丽排比/慢节奏写实）。
4. "stylistic_markers": 3条最具代表性的文风特征指令。
5. "entity_blacklist": 结合上述【全局高频实体】和原著前5000字的内容，列出原著中出现的所有核心【真实姓名】、【具体地名】、【独特的道具/功法/系统名】（务必尽可能详尽，宁可错杀不可放过）。我们将严禁仿写中出现这些词。

请立刻返回JSON:
"""
        max_retries = 3
        last_exception = None
        for attempt in range(max_retries):
            response = generate_text(
                essence_prompt,
                "You are a master literary analyst. Output JSON.",
                task_profile="genesis_json",
                model=DEFAULT_MODEL,
            )
            try:
                return self._parse_json(response, fallback_kind="essence", seed_hint=combined_content, raise_exc=True)
            except Exception as e:
                last_exception = e
                print(f"⚠️ [Genesis] 尝试 {attempt + 1}/{max_retries} 失败: {e}")
                
        print(f"⚠️ [Genesis] JSON 推演彻底失败 ({last_exception})，将下发默认保险兜底层。")
        return self._build_fallback_payload("essence", combined_content, response)

    def generate_evolved_setting(self, essence_report, source_title="", target_audience=None, target_background=None):
        """Path 1: 基于 DNA 报告生成完全原创的【载体映射】设定"""
        print(f"✨ [DNA 重构] 正在基于原著精髓构建全新的题材载体...")
        
        # 转换受众标签
        forced_audience = ""
        if target_audience:
            audience_label = "女频" if target_audience == "female" else "男频"
            forced_audience = f"\n- **受众强制要求**：本书必须设定为 **{audience_label}** 风格。"

        background_req = "**古代书院（如翰林院、国子监、私人顶级书院等）**"
        if target_background:
            background_req = f"**{target_background}**"

        evolve_prompt = f"""你是一个高级文学架构引擎。
你的任务是根据这份“DNA报告”，创造一个全新的、【神似而形不似】的小说设定。

【原始书名/主题锚点】：
{source_title or "未知原题"}

【DNA报告】：
{json.dumps(essence_report, ensure_ascii=False)}

【核心载体强制要求】：
- 本次仿写的背景必须设定为：{background_req}。{forced_audience}
- 核心冲突映射建议：基于原著的 "emotional_formula"，将其逻辑平移至上述新背景中（例如：若原著是高考，映射为书院试炼；若原著是职场，映射为门阀角力）。

要求：
1. 【零容忍抄袭】：严禁使用 "entity_blacklist" 中的任何名词！
2. 【深度扩容与细节填充】：不要做简单的背景替换。必须通过改变“时代背景、题材载体、核心职业或社会形态”来实现完全原创，并补充大量生活化、细节化的背景描写（如：茶肆的烟火气、世家的陈腐礼数等）。
3. 【严禁情节像素级复刻】：绝不能照搬原著的具体事件。必须在理解“打脸/拉扯”的情绪公式后，自行设计全新的核心事件。
4. 【绝缘科幻与AI感】：严禁出现任何科幻概念。严禁出现“数据、加密、系统、算法、逻辑、程序、芯片、维度、锚点”等词汇，严禁将原著设定解释为某种“程序”或“数据流”。
5. 【精髓继承】：必须无缝继承原著的 "emotional_formula" 和 "narrative_pacing"。
6. 必须包含：audience_type, master_style, world_setting, main_character, initial_conflict。
7. 写出一个全新的、具备顶级市场竞争力的开局设定。

请立刻返回JSON:
"""
        max_retries = 3
        last_exception = None
        seed_hint = f"{source_title}\n{json.dumps(essence_report, ensure_ascii=False)}"
        for attempt in range(max_retries):
            response = generate_text(
                evolve_prompt,
                "You are the Sovereign Creator Engine. Output JSON.",
                task_profile="genesis_json",
                model=DEFAULT_MODEL,
            )
            try:
                return self._parse_json(
                    response,
                    fallback_kind="setting",
                    seed_hint=seed_hint,
                    target_audience=target_audience,
                    target_background=target_background,
                    raise_exc=True
                )
            except Exception as e:
                last_exception = e
                print(f"⚠️ [Genesis] 尝试 {attempt + 1}/{max_retries} 失败: {e}")
                
        print(f"⚠️ [Genesis] JSON 推演彻底失败 ({last_exception})，将下发默认保险兜底层。")
        return self._build_fallback_payload(
            "setting",
            seed_hint,
            response,
            target_audience=target_audience,
            target_background=target_background
        )

    def _parse_json(self, response, fallback_kind="setting", seed_hint="", target_audience=None, target_background=None, raise_exc=False):
        try:
            if not response or not isinstance(response, str):
                raise ValueError(f"响应内容异常: {type(response)}")
                
            match = re.search(r'\{.*\}', response, re.DOTALL)
            if match:
                payload = json.loads(match.group(0))
                if not isinstance(payload, dict):
                    raise ValueError("JSON 根结构不是对象")
                
                # 外科手术性净化：强制抹除任何潜在的科幻/AI幻觉词汇
                def deep_purify(obj):
                    if isinstance(obj, dict):
                        return {k: deep_purify(v) for k, v in obj.items()}
                    elif isinstance(obj, list):
                        return [deep_purify(x) for x in obj]
                    elif isinstance(obj, str):
                        return purify_text_to_ancient(obj)
                    return obj
                
                payload = deep_purify(payload)
                return self._normalize_payload(payload, fallback_kind, seed_hint, response, target_audience=target_audience, target_background=target_background)
            else:
                raise ValueError("未匹配到JSON结构")
        except Exception as e:
            logger.warning(f"⚠️ [Genesis] JSON 推演失败: {str(e)}，将根据背景类别下发保险兜底层。")
            
            # 强化版背景感知的兜底逻辑
            is_ancient = target_background and ("古" in target_background or "院" in target_background)
            
            if is_ancient:
                # 返回高质量古代书院风设定
                return {
                    "title": f"{seed_hint.splitlines()[0]}-古风重构版",
                    "audience_type": target_audience or "female_oriented",
                    "master_style": "烽火戏诸侯式文笔，半文半白，辞藻考究且极具张力",
                    "world_setting": f"大胤王朝，{target_background or '青云书院'}。这是一个重视荐辟名额、文气定高下的世界。",
                    "main_character": {
                        "name": "主角",
                        "identity": "寒门学子",
                        "base_personality": "清冷、隐忍、布局深远",
                        "initial_inventory": "半卷残缺手记，一支断毫"
                    },
                    "initial_conflict": "本应属于主角的【春闱推荐名额】被豪门子弟顶替，且主角被诬陷剽窃古籍。"
                }
            else:
                # 原有的现代兜底逻辑
                return {
                    "title": f"{seed_hint.splitlines()[0]}-工业化版",
                    "audience_type": target_audience or "female_oriented",
                    "master_style": "现代职场/校园爽文风格，节奏极快",
                    "world_setting": "现代都市，顶尖学术研究机构。",
                    "initial_conflict": "核心算法成果被导师窃取并转赠他人。"
                }

    def _normalize_payload(self, payload, fallback_kind, seed_hint="", raw_response="", target_audience=None, target_background=None):
        if fallback_kind == "essence":
            return self._ensure_essence_fields(payload, seed_hint, raw_response)
        return self._ensure_setting_fields(payload, seed_hint, raw_response, target_audience=target_audience, target_background=target_background)

    def _infer_audience_type(self, seed_hint="", extra_text=""):
        combined = f"{seed_hint}\n{extra_text}"
        # 女频关键词：增加古代种田、宅斗及温情细节词
        female_terms = [
            "白月光", "回国", "婚", "夫人", "联姻", "千金", "总裁", "前夫", "太太", "未婚夫",
            "宴会", "离婚", "绿茶", "修罗场", "替身", "秘书", "影后", "豪门",
            "种田", "治愈", "生活", "刺绣", "嫡庶", "丫鬟", "小姐", "温情", "细腻", "青梅竹马",
            "衣食住行", "柴米油盐", "布鞋", "糖水", "针线"
        ]
        # 男频关键词：关键词精准化，避免单字命中 common characters
        male_terms = [
            "末世", "宗门", "修炼", "功法", "神魔", "修仙", "神帝", "战神", "诸天", "高武", 
            "荒古", "龙皇", "兵王", "赘婿", "无敌", "逆袭", "升级", "打脸", "杀伐", "果断",
            "飞剑", "刀意", "法术", "禁地", "秘境"
        ]
        
        female_hits = sum(1 for term in female_terms if term in combined)
        male_hits = sum(1 for term in male_terms if term in combined)
        
        # 权重微调：如果提到“种田”、“生活”、“温情”，极大增加女频概率
        if any(term in combined for term in ["种田", "治愈", "温情", "生活"]):
            female_hits += 2

        if female_hits >= male_hits:
            return "female_oriented"
        return "male_oriented"

    def _default_kernel_for_audience(self, audience, seed_hint=""):
        if normalize_audience_type(audience) == "female_oriented":
            if any(term in seed_hint for term in ("白月光", "回国", "前夫", "离婚")):
                return "白月光回国/追妻火葬场"
            if any(term in seed_hint for term in ("联姻", "豪门", "千金", "总裁")):
                return "豪门联姻/先婚后爱"
            return "马甲流/修罗场/情感博弈"
        if any(term in seed_hint for term in ("末世", "废土")):
            return "末世进化/资源争夺"
        if any(term in seed_hint for term in ("宗门", "仙", "帝", "皇")):
            return "废柴逆袭/宗门争霸"
        return "无敌流/升级反杀"

    def _infer_fallback_track(self, audience, seed_hint="", raw_response=""):
        combined = f"{seed_hint}\n{raw_response}"
        # 如果明确检测到现代术语，走现代轨道
        if keyword_hits(combined, MODERN_REALISTIC_TOKENS, limit=3):
            return "modern_realistic"
        # 如果有玄幻术语，走玄幻轨道
        if keyword_hits(combined, ANCIENT_FANTASY_TOKENS, limit=2):
            return "ancient_fantasy"
        # 默认：根据种子词初步判断。如果包含典型的古代背景词，优先走古代轨道
        ancient_clues = ["雪", "腊月", "宁娘", "镇", "官道", "铁匠", "院子", "竹林", "瓦片", "粥", "信物"]
        if any(clue in combined for clue in ancient_clues):
             return "ancient_fantasy"
             
        return "modern_realistic" if normalize_audience_type(audience) == "female_oriented" else "ancient_fantasy"

    def _build_setting_fallback(self, seed_hint="", raw_response="", target_audience=None, target_background=None):
        audience = target_audience or normalize_audience_type(self._infer_audience_type(seed_hint, raw_response))
        if audience == "female": audience = "female_oriented"
        if audience == "male": audience = "male_oriented"
        
        kernel = self._default_kernel_for_audience(audience, seed_hint)
        track = self._infer_fallback_track(audience, seed_hint, raw_response)
        
        # 如果强制指定了背景，优先遵循背景轨道
        if target_background:
            if "古代" in target_background or "玄幻" in target_background:
                track = "ancient_fantasy"
            else:
                track = "modern_realistic"

        if track == "modern_realistic":
            res = {
                "audience_type": audience,
                "narrative_kernel": kernel,
                "master_style": "现实压力下的快节奏对话推进，重压迫感、重反击、重情绪爆点。",
                "world_setting": target_background or "现代现实社会的校园与职场交界地带，资源分配失衡，制度与人情共同塑造不公。",
                "main_character": {
                    "name": "主角",
                    "base_personality": "冷静记账，受压时不失控，擅长在公开场合把问题逼回规则本身",
                    "initial_inventory": "一份能证明真相的原始资料与少量私人证据",
                },
                "initial_conflict": "主角的核心成果被上位者截走，甚至被反咬一口，她必须在声誉彻底崩盘前夺回主动权。",
            }
        elif audience == "female_oriented":
            res = {
                "audience_type": audience,
                "narrative_kernel": kernel,
                "master_style": "张力十足的情感博弈，强微表情、强拉扯、强反差。",
                "world_setting": target_background or "架空古代豪门棋局，家族利益与旧情相互绞杀，层层嵌套。",
                "main_character": {
                    "name": "主角",
                    "base_personality": "外冷内狠，极擅情绪伪装与局势拿捏",
                    "initial_inventory": "一份足以翻盘的家族秘辛",
                },
                "initial_conflict": "旧爱携白月光高调回归，主角在家族宴会上被逼至绝路。",
            }
        else:
            res = {
                "audience_type": audience,
                "narrative_kernel": kernel,
                "master_style": "杀伐果断、推进极快，强调代价、反馈与因果反杀。",
                "world_setting": target_background or "古代玄幻秩序崩坏之地，资源稀缺，力量体系明确。",
                "main_character": {
                    "name": "主角",
                    "base_personality": "冷硬克制，记仇，行动优先于情绪",
                    "initial_inventory": "一件残破却能改写命运的古老信物",
                },
                "initial_conflict": "主角刚被废掉立身根基，追杀者却在今夜找上门来。",
            }
        
        # 这里的冗余逻辑修正：如果强制了背景，必须反馈在 world_setting 里
        if target_background:
            res["world_setting"] = target_background
            
        return res

    def _sanitize_setting_payload(self, normalized, fallback):
        expected_mode = infer_setting_mode(fallback.get("world_setting"), default="ancient_fantasy")

        world_conflicts = detect_setting_conflicts(fallback.get("world_setting"), normalized.get("world_setting"))
        if world_conflicts:
            normalized["world_setting"] = fallback["world_setting"]

        if infer_setting_mode(normalized.get("world_setting"), default=expected_mode) == "forbidden_scifi":
            normalized["world_setting"] = fallback["world_setting"]

        for field_name in ("initial_conflict", "master_style"):
            field_value = normalized.get(field_name, "")
            if keyword_hits(field_value, FORBIDDEN_SCI_FI_TOKENS, limit=3):
                normalized[field_name] = fallback[field_name]
                continue
            field_conflicts = detect_setting_conflicts(normalized["world_setting"], field_value)
            if field_conflicts:
                normalized[field_name] = fallback[field_name]

        main_character = normalized.get("main_character", {})
        for field_name in ("base_personality", "initial_inventory"):
            field_value = main_character.get(field_name, "")
            if keyword_hits(field_value, FORBIDDEN_SCI_FI_TOKENS, limit=3):
                main_character[field_name] = fallback["main_character"][field_name]
        normalized["main_character"] = main_character
        normalized["setting_guardrail"] = infer_setting_mode(normalized["world_setting"], default=expected_mode)
        return normalized

    def _ensure_setting_fields(self, payload, seed_hint="", raw_response="", target_audience=None, target_background=None):
        fallback = self._build_setting_fallback(seed_hint, raw_response, target_audience=target_audience, target_background=target_background)
        audience = target_audience or payload.get("audience_type")
        audience = normalize_audience_type(audience, default=fallback["audience_type"])

        main_character = payload.get("main_character")
        if not isinstance(main_character, dict):
            main_character = {}

        normalized = {
            "audience_type": audience,
            "narrative_kernel": payload.get("narrative_kernel") or self._default_kernel_for_audience(audience, seed_hint),
            "emotional_formula": payload.get("emotional_formula") or "未知情节拉扯公式",
            "master_style": payload.get("master_style") or fallback["master_style"],
            "world_setting": target_background or payload.get("world_setting") or fallback["world_setting"],
            "main_character": {
                "name": main_character.get("name") or fallback["main_character"]["name"],
                "base_personality": main_character.get("base_personality") or fallback["main_character"]["base_personality"],
                "initial_inventory": main_character.get("initial_inventory") or fallback["main_character"]["initial_inventory"],
            },
            "initial_conflict": payload.get("initial_conflict") or fallback["initial_conflict"],
        }
        return self._sanitize_setting_payload(normalized, fallback)

    def _ensure_essence_fields(self, payload, seed_hint="", raw_response=""):
        audience = payload.get("audience_type")
        audience = normalize_audience_type(audience, default=self._infer_audience_type(seed_hint, raw_response))

        stylistic_markers = payload.get("stylistic_markers")
        if not isinstance(stylistic_markers, list) or not stylistic_markers:
            if audience == "female_oriented":
                stylistic_markers = ["微表情推进关系", "短句收刀，停在情绪拐点", "不直白说爱，用动作制造压迫感"]
            else:
                stylistic_markers = ["动作先于解释", "用反馈与代价推进升级", "句式短促，冲突节点直接爆开"]

        entity_blacklist = payload.get("entity_blacklist")
        if isinstance(entity_blacklist, str):
            entity_blacklist = [item.strip() for item in re.split(r"[，,、\s]+", entity_blacklist) if item.strip()]
        if not isinstance(entity_blacklist, list):
            entity_blacklist = []

        return {
            "audience_type": audience,
            "emotional_formula": payload.get("emotional_formula") or ("情感压制与反杀翻盘" if audience == "female_oriented" else "资源争夺与绝境逆袭"),
            "narrative_pacing": payload.get("narrative_pacing") or ("高压短句、关系拉扯前置" if audience == "female_oriented" else "短促推进、反馈密集"),
            "stylistic_markers": stylistic_markers[:3],
            "entity_blacklist": entity_blacklist,
        }

    def _build_fallback_payload(self, fallback_kind, seed_hint="", raw_response="", target_audience=None, target_background=None):
        if fallback_kind == "essence":
            return self._ensure_essence_fields({}, seed_hint, raw_response)
        return self._build_setting_fallback(seed_hint, raw_response, target_audience=target_audience, target_background=target_background)
