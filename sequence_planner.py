from llm_client import generate_text
import json
import re
import sys
from logger import logger
from novel_utils import (
    chapter_title_for_index,
    expected_chapter_indices,
    normalize_total_chapters,
    validate_skeleton_contract,
)

class SequencePlanner:
    """
    工业级骨架引擎：在动笔前产出固定章节逻辑全景图 (楔子 + 10章)
    采用【渐进式解构规划】：逐章推演，确保每一章的 acts 具备极致的独特性与因果律。
    """
    def __init__(self):
        self.step_skeleton_prompt = """你是一个“高阶故事架构师代理”（Architect Agent）。
你的任务是为一个短篇小说规划【当前章节】的详细逻辑骨架。

【当前目标】：规划第 {current_idx} 章
【全书最终结局（不可偏离的目标）】：
{global_resolution}

【先前已规划的剧情脉络】：
{arc_history}

【核心世界观设定】：
{genesis_setting}

---
【规划要求】：
1. **场景具体化**：严禁模糊描述。必须提供具体、符合世界观的场景（如：翰林院东庑、落梅池边的石凳）。
2. **三幕式行动段落 (Mandatory)**：必须通过 `acts` 字段拆解为三个具体的行动段落。
   - 严禁：使用模板化词汇（如“寻找借力点”、“展开交锋”）。
   - 必须：写出具体的、符合女频情感拉扯/男频逆袭质感的动作（如：“借由归还玉佩之机，在众目睽睽下点破对方身份穿帮”、“在岁末试上一字不差地默出从未公开的禁书残卷”）。
3. **因果连续性**：本章必须承接上文，并为后续推演埋下逻辑引线。
4. **受众倾向**：本次受众为 {audience}。请根据受众偏好调整侧重点。
5. **题材底色**：{track_hint}。

【起名/用词约束】：
- 严禁出现任何科幻/现代术语（数据、流、系统、程序、实验室、芯片、逻辑、算法）。
- 映射建议：主角的聪明才智映射为“玲珑心、博闻强记”；敌人的算计映射为“阴谋、局、杀机”。

输出格式（严格返回一个 JSON 对象，不要包含其他键）：
{{
  "chapter_idx": {current_idx},
  "title": "充满张力的本章标题",
  "scene": "主场景具象化描述",
  "acts": {{
    "act_1": "起：本章冲突的引火点",
    "act_2": "承/转：本章情感或局势的最高潮",
    "act_3": "合：本章收尾的余韵或钩子"
  }},
  "characters": ["本章涉及的所有角色"],
  "foreshadowing_to_plant": "此处埋下的具体伏笔（如：落在现场的一方手帕）",
  "state_transition": "主角此时的处境/心境变化"
}}
"""

    def plan_novel_arc(self, genesis_setting, anti_plagiarism_context="", total_chapters=10):
        total_chapters = normalize_total_chapters(total_chapters)
        expected_indices = expected_chapter_indices(total_chapters)
        total_sections = len(expected_indices)
        final_title = chapter_title_for_index(total_chapters)

        print(f"\n📐 [Sequence Planner] 开启“全局逻辑底片 + 上帝视角并发扩写”模式 (共 {total_sections} 段)...")
        sys.stdout.flush()

        from llm_client import generate_text
        import concurrent.futures

        # ---------------------------------------------------------
        # 第一阶段：生成【全局逻辑底片】（包含人物、道具、伏笔流转）
        # ---------------------------------------------------------
        beat_sheet_prompt = f"""请根据以下设定，推演全书 {total_sections} 段的逻辑底片。
设定：{json.dumps(genesis_setting, ensure_ascii=False)}
{anti_plagiarism_context}

请严格按以下格式输出（纯文本，绝不要 JSON），这决定了全书的因果闭环：
全局结局：[描述最终结局与核心反转点]

[章节逻辑流转]：
第0章：[标题] | 剧情：[核心动作] | 人物：[主要登场] | 道具伏笔：[本章关键物件或埋下的雷]
第1章：[标题] | 剧情：[核心动作] | 人物：[主要登场] | 道具伏笔：[物件流转或新埋伏笔]
... (请务必写完 0 到 {total_chapters} 章)
第{total_chapters}章：[标题] | 剧情：[终极冲突、真相揭示、反派清算、主角命运定格] | 人物：[主要登场] | 道具伏笔：[全书伏笔终极收束，严禁新增续章钩子]

注意：请确保人物的行为逻辑一致，道具的出现和消失必须有因果，伏笔必须在后文有呼应。"""

        print(f"   [阶段1] 正在绘制 {total_sections} 段全局逻辑底片（因果链条构建中）...")
        sys.stdout.flush()
        
        master_logic_map = ""
        for attempt in range(3):
            try:
                master_logic_map = generate_text(beat_sheet_prompt, "You are a master story architect. Build a consistent causal chain.")
                if final_title in master_logic_map:
                    break
            except Exception as e:
                print(f"      ⚠️ 第一阶段主线生成异常: {e}")

        # ---------------------------------------------------------
        # 第二阶段：带上【上帝视角】进行并发扩写
        # ---------------------------------------------------------
        track_hint = "古代背景" if "古代" in str(genesis_setting.get("world_setting", "")) else "现代背景"
        audience = genesis_setting.get("audience_type", "女频")
        
        def expand_chapter(idx):
            # 关键：每一章扩写时，都把全书逻辑底片塞进去
            if idx == total_chapters:
                chapter_mission = (
                    f"这是第{total_chapters}章，也是全书大结局。JSON 必须把 goal 写成终章收束目标；"
                    "acts.act_1 必须引爆终极冲突，acts.act_2 必须揭示核心真相并清算主要反派，"
                    "acts.act_3 必须完成首尾呼应、主角命运定格、全书落幕。"
                    "foreshadowing_to_plant 必须写“终章不新增伏笔；只回收、揭示、清算、定格。”"
                )
                act_3_hint = "合：完成首尾呼应、全书伏笔回收、主角命运定格，确定性落幕"
                clue_hint = "终章不新增伏笔；只回收、揭示、清算、定格。"
            else:
                chapter_mission = "本章必须承接前文，并为后续推演埋下逻辑引线。"
                act_3_hint = "合：本章收尾的余韵或钩子"
                clue_hint = "本章埋下或收回的伏笔描述"
            p_prompt = f"""你是一个高阶故事架构师。请根据【全局逻辑底片】，将【第{idx}章】扩写为详细 JSON。

【全局上帝视角 - 逻辑底片】：
{master_logic_map}

【世界观设定】：{json.dumps(genesis_setting, ensure_ascii=False)[:400]}

任务：
1. 严格遵循逻辑底片中对第{idx}章的规划。
2. **因果对齐**：检查前文章节（0到{idx-1}章）的道具和伏笔，若逻辑底片要求在本章收束，请务必在 acts 中体现。
3. **环境渲染**：场景需具象化，动作需符合{audience}受众偏好。
4. **本章任务**：{chapter_mission}

输出 JSON 格式：
{{
  "chapter_idx": {idx},
  "title": "章节标题",
  "goal": "本章核心目标",
  "scene": "主场景具象化描述",
  "acts": {{
    "act_1": "起：本章冲突的引火点",
    "act_2": "承/转：本章情感或局势的最高潮",
    "act_3": "{act_3_hint}"
  }},
  "characters": ["本章角色列表"],
  "foreshadowing_to_plant": "{clue_hint}",
  "state_transition": "主角状态变化"
}}
"""
            return self._generate_single_step_with_retry(
                idx,
                p_prompt,
                genesis_setting,
                "逻辑一致性扩写",
                retries=3,
                total_chapters=total_chapters,
            )

        novel_arc = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_idx = {executor.submit(expand_chapter, i): i for i in expected_indices}
            for future in concurrent.futures.as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    chapter_data = future.result()
                    if chapter_data:
                        novel_arc.append(chapter_data)
                        print(f"      ✔️ 第 {idx} 章逻辑细节扩写完成")
                except Exception as e:
                    print(f"      ⚠️ 第 {idx} 章扩写失败: {e}")
                    novel_arc.append(self._get_fallback_chapter(idx, genesis_setting, "逻辑兜底", total_chapters=total_chapters))

        novel_arc.sort(key=lambda x: x["chapter_idx"])
        
        # 提取结局描述
        res_match = re.search(r"全局结局：(.*?)(?=\n\[章节逻辑流转\]|$)", master_logic_map, re.DOTALL)
        final_resolution = res_match.group(1).strip() if res_match else "圆满收官"

        result = validate_skeleton_contract(
            {
                "global_resolution": final_resolution,
                "novel_arc": novel_arc
            },
            total_chapters=total_chapters,
        )

        print(f"✅ [高并发规划成功] {total_sections} 段精密大纲已通过上帝视角模式极速交付！")
        sys.stdout.flush()
        return result

    def _generate_single_step_with_retry(self, idx, prompt, genesis_setting, global_resolution, retries=3, total_chapters=10):
        total_chapters = normalize_total_chapters(total_chapters)
        for attempt in range(retries):
            try:
                response = generate_text(prompt, "Output ONLY valid JSON object.", task_profile="planner_json")
                parsed = self._parse_json_object(response)
                if parsed and int(parsed.get("chapter_idx")) == idx:
                    parsed["chapter_idx"] = idx
                    return parsed
                print(f"      ⚠️ 第 {idx} 章第 {attempt+1} 次尝试解析失败或索引不符，正在重试...")
            except Exception as e:
                print(f"      ⚠️ 第 {idx} 章尝试 {attempt+1} 抛出异常: {e}")
            sys.stdout.flush()
        
        # 如果重试均失败，使用更智能一点的紧急方案，而不是全重复
        return self._get_fallback_chapter(idx, genesis_setting, global_resolution, total_chapters=total_chapters)

    def _generate_with_retry(self, prompt, system_msg, retries=3):
        for attempt in range(retries):
            try:
                res = generate_text(prompt, system_msg)
                if res and len(res.strip()) > 10:
                    return res
            except Exception as e:
                print(f"      ⚠️ 生成尝试 {attempt+1} 失败: {e}")
        return "圆满收官。"

    def _parse_json_object(self, response):
        try:
            if not response or not isinstance(response, str):
                return None
            match = re.search(r'\{.*\}', response, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        except:
            pass
        return None

    def _get_fallback_chapter(self, idx, genesis_setting, global_resolution, total_chapters=10):
        """兜底逻辑也需要一点灵性"""
        total_chapters = normalize_total_chapters(total_chapters)
        mc_name = genesis_setting.get("main_character", {}).get("name", "主角")
        world_setting = str(genesis_setting.get("world_setting", ""))
        is_ancient = "古代" in world_setting or "书院" in world_setting or "修仙" in world_setting
        
        is_prologue = idx == 0
        is_final = idx == total_chapters
        title = "阶段性进展"
        if is_prologue:
            title = "序章：宿命开启"
        elif is_final:
            title = "终章：尘埃落定"

        if is_final:
            acts = {
                "act_1": f"{mc_name}直面最终阻力，公开引爆全书核心冲突。",
                "act_2": f"围绕结局“{global_resolution[:40]}”完成真相揭示、证据落地与反派清算。",
                "act_3": "主角命运定格，核心伏笔闭环，全书在确定性的最终画面中结束。",
            }
            foreshadowing = "终章不新增伏笔；只回收、揭示、清算、定格。"
            state_transition = "主角完成最终蜕变，故事闭环。"
        else:
            acts = {
                "act_1": f"{mc_name}在关键时刻察觉到了局势的微妙变化。",
                "act_2": f"双方在当前场景下产生了一场无法回避的争锋（基于结局：{global_resolution[:20]}...）。",
                "act_3": f"事态暂时平息，但留下了更深的阴影。"
            }
            foreshadowing = "无"
            state_transition = "处境更加紧迫"

        return {
            "chapter_idx": idx,
            "title": f"{title}(自适应补全)",
            "scene": world_setting[:50],
            "acts": acts,
            "characters": [mc_name],
            "foreshadowing_to_plant": foreshadowing,
            "state_transition": state_transition
        }

    def replan_novel_arc(self, genesis_setting, current_arc, current_idx, new_state, new_clue, anti_plagiarism_context="", total_chapters=10):
        """局部重塑也改为逐章模式"""
        total_chapters = normalize_total_chapters(total_chapters)
        print(f"\n🦋 [Sequence Replanner] 正在执行逐章重塑流程...")
        sys.stdout.flush()
        
        global_resolution = current_arc.get("global_resolution", "圆满收官。")
        novel_arc = current_arc.get("novel_arc", [])[:current_idx + 1]
        track_hint = "古代背景" if "古代" in str(genesis_setting.get("world_setting", "")) else "现代背景"
        audience = genesis_setting.get("audience_type", "女频")

        for i in range(current_idx + 1, total_chapters + 1):
            print(f"   [Replan Chapter {i}/{total_chapters}] 逻辑修正中...")
            arc_history = json.dumps(novel_arc[-2:], ensure_ascii=False)
            mutation_info = f"【状态突变】：{json.dumps(new_state, ensure_ascii=False)}\n【关键新线索】：{new_clue}"
            
            p_prompt = self.step_skeleton_prompt.format(
                current_idx=i,
                global_resolution=global_resolution,
                arc_history=arc_history,
                genesis_setting=f"{json.dumps(genesis_setting, ensure_ascii=False)}\n{mutation_info}",
                audience=audience,
                track_hint=track_hint
            )
            
            chapter_data = self._generate_single_step_with_retry(
                i,
                p_prompt,
                genesis_setting,
                global_resolution,
                total_chapters=total_chapters,
            )
            novel_arc.append(chapter_data)
            sys.stdout.flush()

        return validate_skeleton_contract({"novel_arc": novel_arc, "global_resolution": global_resolution}, total_chapters=total_chapters)
