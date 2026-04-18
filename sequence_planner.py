from llm_client import generate_text
import json
import re

import sys

class SequencePlanner:
    """
    工业级骨架引擎：在动笔前产出 11 段逻辑全景图 (楔子 + 10章)
    确保因果锁死、伏笔预埋、以及状态转换。
    """
    def __init__(self):
        self.skeleton_prompt = """你是一个“高阶故事架构师代理”（Architect Agent）。
你的任务是根据给定的世界观设定、主角初始状态和核心矛盾，为一个短篇小说产出详细的【逻辑骨架 JSON】。

必须要规划的关键点：
1. **结构要求**：严格按照要求的章节范围生成。
2. **伏笔埋设与回收**：在早期章节点（如楔子或前三章）埋下伏笔，并在后期章节明确回收。
3. **状态变迁**：跟踪主角的物理状态（受伤、获得武器、换马甲等）。
4. **节奏控制**：确保【楔子】高危爆发，中间转折，结局合龙并首尾呼应。

输入环境设定：
{genesis_setting}

输出格式（严格 JSON）：
{{
  "novel_arc": [
    {{
      "chapter_idx": 序号,
      "title": "章节标题",
      "plot_beat": "详细的情节爆点",
      "foreshadowing_to_plant": "此处埋下的伏笔描述",
      "state_transition": "本段后的主角状态变更"
    }},
    ... {chapter_range_desc}
  ],
  "global_resolution": "最终章节如何呼应楔子的具体设计"
}}
"""

    def plan_novel_arc(self, genesis_setting):
        print(f"\n📐 [Sequence Planner] 启动三阶段碎粒化推演模式 (楔子 + 10章)...")
        sys.stdout.flush()
        
        # 阶段 1: 楔子 + 前三章 (0-3)
        print(f"   [Phase 1] 正在构思核心开局 (楔子 + 1-3章)...")
        sys.stdout.flush()
        p1_prompt = self.skeleton_prompt.format(genesis_setting=json.dumps(genesis_setting, ensure_ascii=False), chapter_range_desc="只生成第0章(楔子)到第3章。不要生成后面的章节。")
        
        p1_response = generate_text(p1_prompt, "You are a master literary architect. Output ONLY valid JSON.")
        arc_p1 = self._parse_partial_json(p1_response)
        
        if not arc_p1 or "novel_arc" not in arc_p1:
            print("⚠️ [Phase 1] 失败，尝试进入兜底逻辑。")
            sys.stdout.flush()
            return self._get_fallback_arc(genesis_setting)

        # 阶段 2: 中场四章 (4-7)
        print(f"   [Phase 2] 正在构思中场转折 (4-7章)...")
        sys.stdout.flush()
        p2_prompt = self.skeleton_prompt.format(
            genesis_setting=f"【世界观设定】：\n{json.dumps(genesis_setting, ensure_ascii=False)}\n\n【已有前期骨架(0-3章)】：\n{json.dumps(arc_p1['novel_arc'], ensure_ascii=False)}",
            chapter_range_desc="基于已有前期骨架，请只生成第4章到第7章。延续伏笔，推进矛盾升级。不要生成其他章节。"
        )
        p2_response = generate_text(p2_prompt, "You are a master literary architect. Output ONLY valid JSON.")
        arc_p2 = self._parse_partial_json(p2_response)

        if not arc_p2 or "novel_arc" not in arc_p2:
            print("⚠️ [Phase 2] 失败，仅保留前期逻辑。")
            sys.stdout.flush()
            return arc_p1

        # 阶段 3: 后三章 + 终局 (8-10)
        print(f"   [Phase 3] 正在构思终局合龙 (8-10章)...")
        sys.stdout.flush()
        p3_prompt = self.skeleton_prompt.format(
            genesis_setting=f"【世界观设定】：\n{json.dumps(genesis_setting, ensure_ascii=False)}\n\n【已有骨架(0-7章)】：\n{json.dumps(arc_p1['novel_arc'] + arc_p2['novel_arc'], ensure_ascii=False)}",
            chapter_range_desc="基于已有骨架，请只生成第8章到第10章。确保在第10章完成终极合龙，并包含 global_resolution。"
        )
        p3_response = generate_text(p3_prompt, "You are a master literary architect. Output ONLY valid JSON.")
        arc_p3 = self._parse_partial_json(p3_response)

        if not arc_p3 or "novel_arc" not in arc_p3:
            print("⚠️ [Phase 3] 失败，保留前 8 段逻辑。")
            sys.stdout.flush()
            combined_arc = {
                "novel_arc": arc_p1["novel_arc"] + arc_p2["novel_arc"],
                "global_resolution": "待定"
            }
            return combined_arc

        # 合并结果
        combined_arc = {
            "novel_arc": arc_p1["novel_arc"] + arc_p2["novel_arc"] + arc_p3["novel_arc"],
            "global_resolution": arc_p3.get("global_resolution", "圆满收官。")
        }
        print(f"✅ [骨架全量推演成功] 楔子+10章全景图已锁死。")
        sys.stdout.flush()
        return combined_arc

    def _parse_partial_json(self, response):
        """支持清洗、修复截断并提取第一个合法的 JSON 块"""
        try:
            if not response or not isinstance(response, str):
                return None
            
            # 找到第一个 { 
            start_idx = response.find('{')
            if start_idx == -1:
                return None
            
            # 找到最后一个 }
            end_idx = response.rfind('}')
            
            # 核心容错：如果没找到 } 或者 JSON 被截断
            if end_idx == -1 or end_idx < start_idx:
                # 尝试通过补完括号来修复截断的 JSON
                return self._repair_json(response[start_idx:])
            
            potential_json = response[start_idx:end_idx+1]
            
            # 尝试逐步修复/缩减
            while potential_json:
                try:
                    return json.loads(potential_json)
                except json.JSONDecodeError as e:
                    # 如果报错是由于截断，尝试补完
                    if "Expecting" in str(e) or "Unterminated" in str(e):
                        repaired = self._repair_json(potential_json)
                        if repaired: return repaired
                    
                    # 如果是 Extra Data，尝试缩减尾部
                    if "Extra data" in str(e):
                        end_idx = potential_json.rfind('}', 0, -1)
                        if end_idx == -1: break
                        potential_json = potential_json[:end_idx+1]
                    else:
                        break
            return None
        except Exception as e:
            print(f"   ❌ JSON 深度解析/修复失败: {e}")
            sys.stdout.flush()
        return None

    def _repair_json(self, truncated_str):
        """暴力尝试修复截断的 JSON 结构"""
        # 统计未闭合的括号
        stack = []
        for char in truncated_str:
            if char == '{': stack.append('}')
            elif char == '[': stack.append(']')
            elif char == '}' or char == ']':
                if stack and stack[-1] == char:
                    stack.pop()
        
        # 倒序补完
        repaired_str = truncated_str
        while stack:
            repaired_str += stack.pop()
            try:
                data = json.loads(repaired_str)
                return data
            except:
                continue
        return None

    def replan_novel_arc(self, genesis_setting, current_arc, current_idx, new_state, new_clue):
        print(f"\n🦋 [Sequence Replanner] 触发蝴蝶效应！基于第 {current_idx} 章的突变进行后续大纲重铸...")
        prompt = f"""你是一个“高阶故事架构师代理”。
目前小说刚完成了第 {current_idx} 章。在这个过程中发生了意外偏离或产生了重大新线索。
为了保证逻辑严密，你需要重新规划第 {current_idx + 1} 章到最终章的大纲。

【初始世界观设定】：
{json.dumps(genesis_setting, ensure_ascii=False)}

【之前的大纲】：
{json.dumps(current_arc, ensure_ascii=False)}

【最新状态突变】：
主角当前最新状态：{new_state}
本章新产生的重大(S级)伏笔/线索：{new_clue}

输出格式同样为严格的 JSON (只需返回剩余章节和结局，以及一个融合了旧章节的新完整列表)：
{{
  "novel_arc": [
    ...从第1章到最后一章的完整列表...
  ],
  "global_resolution": "更新后的最终结局。"
}}
"""
        response = generate_text(prompt, "You are a master literary architect. Output ONLY valid JSON.")
        arc = self._parse_partial_json(response)
        if arc:
            print(f"✅ [大纲重铸成功] 蝴蝶效应生效，后续因果图景已更新。")
            return arc
        else:
            print(f"⚠️ [Replanner] 重铸失败。保留原有大纲。")
            return current_arc

    def _get_fallback_arc(self, genesis_setting):
        # 兜底逻辑：线性推进
        arc = {"novel_arc": []}
        # 第0段：楔子
        arc["novel_arc"].append({
            "chapter_idx": 0,
            "title": "楔子",
            "plot_beat": "线性开局",
            "foreshadowing_to_plant": "无",
            "state_transition": "无"
        })
        # 第1-10段
        for i in range(1, 11):
            arc["novel_arc"].append({
                "chapter_idx": i,
                "title": f"第{i}章",
                "plot_beat": "线性剧情推进",
                "foreshadowing_to_plant": "无",
                "state_transition": "无"
            })
        arc["global_resolution"] = "线性结局。"
        return arc
