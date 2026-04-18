from llm_client import generate_text
import json
import re
import os
import hashlib

class GenesisDirector:
    """创世大脑：推演设定并生成男/女频以及核心世界观"""
    def __init__(self):
        self.genesis_prompt = """你是一个“世界观创世引擎”（Genesis API）。
给定一个极简的灵感火花或书名，你必须完全自主推演出以下这本小说的核心设定。
必须以强格式 JSON 输出！不要有解释性文本！

灵感/书名：{title_seed}

必须要推演的关键字段：
1. "audience_type": "male_oriented" 或者是 "female_oriented"
2. "narrative_kernel": 根据分类选择核心爽点/虐点逻辑（例如：男频为“无敌流/智斗/系统”，女频为“追妻火葬场/马甲流/独宠”）。
3. "master_style": 推荐的最匹配的主力文风门派。
4. "world_setting": 详细的背景世界观与力量体系描述。
5. "main_character": {{"name": "...", "base_personality": "...", "initial_inventory": "..."}}。
6. "initial_conflict": 剧情即将爆发的【楔子矛盾点】。

请立刻返回JSON:
"""

    def generate_genesis_setting(self, title_seed):
        """Path 2: 根据背景设定扩展生成世界观"""
        print(f"\n🌍 [Genesis 创世引擎] 正在为《{title_seed}》推演宏大世界观与受众模型...")
        prompt = self.genesis_prompt.format(title_seed=title_seed)
        response = generate_text(prompt, "You are the Genesis God Engine. Output purely valid JSON.")
        
        return self._parse_json(response, fallback_kind="setting", seed_hint=title_seed)

    def analyze_reference_essence(self, file_paths):
        """Path 1: 深度分析原著精髓并列出实体黑名单"""
        if isinstance(file_paths, str):
            file_paths = [file_paths]
            
        combined_content = ""
        for path in file_paths:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    combined_content += f.read()[:5000] # 采样前5000字
        
        print(f"\n🧬 [Essence 分析] 正在从 {len(file_paths)} 本原著中提取核心 DNA...")
        
        essence_prompt = f"""你是一个文学DNA分析专家。请阅读以下文本（截取），提取其灵魂精髓。

【原著文本】：
{combined_content}

你必须提交一份高度精炼的“DNA报告”，并以 JSON 格式输出：
1. "audience_type": 原著的受众定位。
2. "emotional_formula": 原著最核心的底层冲突与情绪拉扯公式（例如：上位者失控/克苏鲁式绝望）。
3. "narrative_pacing": 叙事节奏特征（如：极简短句/华丽排比/慢节奏写实）。
4. "stylistic_markers": 3条最具代表性的文风特征指令。
5. "entity_blacklist": 列出原著中出现的所有【真实姓名】、【具体地名】、【独特的道具/功法/系统名】。我们将严禁仿写中出现这些词。

请立刻返回JSON:
"""
        response = generate_text(essence_prompt, "You are a master literary analyst. Output JSON.")
        return self._parse_json(response, fallback_kind="essence", seed_hint=combined_content)

    def generate_evolved_setting(self, essence_report):
        """Path 1: 基于 DNA 报告生成完全原创的【载体映射】设定"""
        print(f"✨ [DNA 重构] 正在基于原著精髓构建全新的题材载体...")
        
        evolve_prompt = f"""你是一个高级文学架构引擎。
你的任务是根据这份“DNA报告”，创造一个全新的、【神似而形不似】的小说设定。

【DNA报告】：
{json.dumps(essence_report, ensure_ascii=False)}

要求：
1. 【零容忍抄袭】：严禁使用 "entity_blacklist" 中的任何名词！
2. 【禁止平行时空】：不要做简单的背景替换或“平行世界”。必须通过改变“时代背景、题材载体、核心职业或社会形态”来实现完全原创。
   （例如：如果原著是现代职场，你可以将其 DNA 映射到【古代江湖、星际修罗场、东方玄幻】等完全不同的舞台）。
3. 【精髓继承】：必须无缝继承原著的 "emotional_formula"（情绪拉扯公式）和 "narrative_pacing"（叙事节奏）。
4. 必须包含：audience_type, master_style, world_setting, main_character, initial_conflict。
5. 写出一个全新的、具备顶级市场竞争力的开局设定。

请立刻返回JSON:
"""
        response = generate_text(evolve_prompt, "You are the Sovereign Creator Engine. Output JSON.")
        return self._parse_json(
            response,
            fallback_kind="setting",
            seed_hint=json.dumps(essence_report, ensure_ascii=False),
        )

    def _parse_json(self, response, fallback_kind="setting", seed_hint=""):
        try:
            if not response or not isinstance(response, str):
                raise ValueError(f"响应内容异常: {type(response)}")
                
            match = re.search(r'\{.*\}', response, re.DOTALL)
            if match:
                payload = json.loads(match.group(0))
                if not isinstance(payload, dict):
                    raise ValueError("JSON 根结构不是对象")
                return self._normalize_payload(payload, fallback_kind, seed_hint, response)
            else:
                raise ValueError("未匹配到JSON结构")
        except Exception as e:
            print(f"⚠️ [Genesis] JSON 推演失败: {e}，将下发默认保险兜底层。")
            return self._build_fallback_payload(fallback_kind, seed_hint, response)

    def _normalize_payload(self, payload, fallback_kind, seed_hint="", raw_response=""):
        if fallback_kind == "essence":
            return self._ensure_essence_fields(payload, seed_hint, raw_response)
        return self._ensure_setting_fields(payload, seed_hint, raw_response)

    def _infer_audience_type(self, seed_hint="", extra_text=""):
        combined = f"{seed_hint}\n{extra_text}"
        female_terms = [
            "白月光", "回国", "婚", "夫人", "联姻", "千金", "总裁", "前夫", "太太", "未婚夫",
            "宴会", "离婚", "绿茶", "修罗场", "替身", "秘书", "影后", "豪门",
        ]
        male_terms = [
            "系统", "末世", "宗门", "剑", "刀", "帝", "皇", "仙", "修", "神", "魔",
            "签到", "战神", "诸天", "高武", "荒", "龙", "兵王", "赘婿",
        ]
        female_hits = sum(term in combined for term in female_terms)
        male_hits = sum(term in combined for term in male_terms)
        if female_hits > male_hits:
            return "female_oriented"
        if male_hits > female_hits:
            return "male_oriented"
        digest = hashlib.md5((combined or "genesis").encode("utf-8")).hexdigest()
        return "female_oriented" if int(digest[-1], 16) % 2 else "male_oriented"

    def _default_kernel_for_audience(self, audience, seed_hint=""):
        if audience == "female_oriented":
            if any(term in seed_hint for term in ("白月光", "回国", "前夫", "离婚")):
                return "白月光回国/追妻火葬场"
            if any(term in seed_hint for term in ("联姻", "豪门", "千金", "总裁")):
                return "豪门联姻/先婚后爱"
            return "马甲流/修罗场/情感博弈"
        if any(term in seed_hint for term in ("系统", "签到")):
            return "系统流/签到升级"
        if any(term in seed_hint for term in ("末世", "废土")):
            return "末世进化/资源争夺"
        if any(term in seed_hint for term in ("宗门", "仙", "帝", "皇")):
            return "废柴逆袭/宗门争霸"
        return "无敌流/升级反杀"

    def _build_setting_fallback(self, seed_hint="", raw_response=""):
        audience = self._infer_audience_type(seed_hint, raw_response)
        kernel = self._default_kernel_for_audience(audience, seed_hint)
        if audience == "female_oriented":
            return {
                "audience_type": audience,
                "narrative_kernel": kernel,
                "master_style": "张力十足的情感博弈爽文，强微表情、强拉扯、强反差。",
                "world_setting": "架空都市豪门棋局，关系网络层层嵌套，名分、利益与旧情相互绞杀。",
                "main_character": {
                    "name": "主角",
                    "base_personality": "外冷内狠，极擅情绪伪装与局势拿捏",
                    "initial_inventory": "被尘封的旧婚约与一份足以翻盘的录音",
                },
                "initial_conflict": "旧爱携白月光高调回归，主角却在晚宴上被逼当众失去一切。",
            }
        return {
            "audience_type": audience,
            "narrative_kernel": kernel,
            "master_style": "杀伐果断、推进极快的硬派爽文，强调代价、反馈与因果反杀。",
            "world_setting": "高武或末世秩序崩坏之地，资源稀缺，力量体系明确，弱者会被当场碾碎。",
            "main_character": {
                "name": "主角",
                "base_personality": "冷硬克制，记仇，行动优先于情绪",
                "initial_inventory": "一件残破却能改写命运的旧器",
            },
            "initial_conflict": "主角刚被废掉立身根基，追杀者却在今夜踩着尸堆找上门来。",
        }

    def _ensure_setting_fields(self, payload, seed_hint="", raw_response=""):
        fallback = self._build_setting_fallback(seed_hint, raw_response)
        audience = payload.get("audience_type")
        if audience not in {"male_oriented", "female_oriented"}:
            audience = fallback["audience_type"]

        main_character = payload.get("main_character")
        if not isinstance(main_character, dict):
            main_character = {}

        normalized = {
            "audience_type": audience,
            "narrative_kernel": payload.get("narrative_kernel") or self._default_kernel_for_audience(audience, seed_hint),
            "master_style": payload.get("master_style") or fallback["master_style"],
            "world_setting": payload.get("world_setting") or fallback["world_setting"],
            "main_character": {
                "name": main_character.get("name") or fallback["main_character"]["name"],
                "base_personality": main_character.get("base_personality") or fallback["main_character"]["base_personality"],
                "initial_inventory": main_character.get("initial_inventory") or fallback["main_character"]["initial_inventory"],
            },
            "initial_conflict": payload.get("initial_conflict") or fallback["initial_conflict"],
        }
        return normalized

    def _ensure_essence_fields(self, payload, seed_hint="", raw_response=""):
        audience = payload.get("audience_type")
        if audience not in {"male_oriented", "female_oriented", "general"}:
            audience = self._infer_audience_type(seed_hint, raw_response)

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

    def _build_fallback_payload(self, fallback_kind, seed_hint="", raw_response=""):
        if fallback_kind == "essence":
            return self._ensure_essence_fields({}, seed_hint, raw_response)
        return self._build_setting_fallback(seed_hint, raw_response)
