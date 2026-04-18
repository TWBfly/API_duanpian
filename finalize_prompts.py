import os
import re
import argparse
import sys

def num_to_chinese(num):
    chinese_nums = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]
    if 0 <= num <= 10:
        return chinese_nums[num]
    if 10 < num < 20:
        return "十" + chinese_nums[num - 10]
    if 20 <= num < 100:
        tens = num // 10
        ones = num % 10
        if ones == 0:
            return chinese_nums[tens] + "十"
        return chinese_nums[tens] + "十" + chinese_nums[ones]
    return str(num)

CORE_STYLE_HARDCORE = """
【创作目标：字数达标】
- 必须：本章文字创作目标为 [2000字以上]。
- 增长技巧：严禁水字数，通过增加人物内心博弈、感官细节、碎碎念、对话中的交锋、详细的肢体动作来拉长篇幅，而非靠形容词或重复。

【核心原则：烽火戏诸侯/长短句张力风】
1. 节奏打散：绝对禁止排比式、对称式联结。必须采用 3-5 字的极短短句与超长句进行极端交错断裂，制造突兀的节奏感。
2. 脱离悬浮：禁止使用任何主观或哲学抽象词(如“痛苦、绝望、生理极限”)，必须替换为粗粝的底层生理体征(如胃酸反流、手指发麻、眼前泛黑、太阳穴狂跳、喉咙干渴、牙龈生疼、指甲嵌入掌心的刺痛)。
3. 前100字定生死：开篇必须“开幕雷击”，直接切入冲突或悬念，严禁写环境、背景或抒情。
4. 感官颗粒感：不要总结，要“展示”。用触觉、嗅觉、听觉的瞬间爆发取代泛泛的视觉，让读者如临其境。

【钢铁禁令：严禁 AI 味总结】
- 严禁章末总结：禁止在章末进行任何感慨、评价或画外音（如“他不知道……”、“这只是开始”、“一切都变了”）。最后一句必须收在动作、对话或具体的画面上，戛而止。
- 语义隔离：禁止正文出现元概念词汇：“卷”、“阶段”、“幕”、“伏笔”、“回收”、“系统化”、“结构”。
- 句式拉黑：彻底禁用： “不仅如此”、“总之”、“随着时间的推移”、“说时迟那时快”、“已经不再只是……”、“这才是真正的……”、“没有 xxx，也没有 xxx”。

【去 AI 化策略】
- 必须：将 AI 检查率降为 0%。
- 笔触：保持准职业写手的原生态，允许合理的口语化表达。
- 对话：用对话推进剧情，而非旁白叙述。
"""

def split_and_prompt(content):
    chapters_data = []
    chinese_num = r'[\u96f6\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e\u53430-9]+'
    pattern_str = rf'^(#{{1,4}})\s*(\u6954\u5b50|\u7b2c{chinese_num}\u7ae0|\u7ed3\u5c40)[:\uff1a]?\s*(.*)$'
    pattern = re.compile(pattern_str, re.MULTILINE)
    
    matches = list(pattern.finditer(content))
    if not matches:
        return []

    for i, m in enumerate(matches):
        chapter_type = m.group(2).strip()
        chapter_suffix = m.group(3).strip()
        full_title = f"{chapter_type}：{chapter_suffix}" if chapter_suffix else chapter_type
        
        start_pos = m.end()
        end_pos = matches[i+1].start() if i + 1 < len(matches) else len(content)
        
        body = content[start_pos:end_pos].strip()
        
        if chapter_type == "楔子":
            idx = 0
            filename = "00_楔子"
        else:
            try:
                num_str = re.search(r'\d+', chapter_type).group()
                idx = int(num_str)
            except:
                idx = i
            filename = f"{idx:02d}_{chapter_type}"
            
        chapters_data.append((idx, filename, full_title, body))
    return chapters_data

def main():
    parser = argparse.ArgumentParser(description="工业化大纲固化器 - 将大纲转为独立提示词")
    parser.add_argument("--input", type=str, required=True, help="输入大纲文件路径 (如 report/2大纲.md)")
    parser.add_argument("--out_dir", type=str, default="prompt_manual", help="输出文件夹")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"❌ 错误：未找到输入文件 {args.input}")
        return

    with open(args.input, "r", encoding="utf-8") as f:
        content = f.read()
        
    os.makedirs(args.out_dir, exist_ok=True)
    chapters = split_and_prompt(content)
    
    for i, (idx, filename, title, body) in enumerate(chapters):
        next_body = chapters[i+1][3] if i+1 < len(chapters) else "结局"
        
        full_prompt = f"""【prompt：【
- 作为一名职业网文大师，你的任务是创作引人入胜的{title}。
{CORE_STYLE_HARDCORE}
】】

【本章大纲】
# {title}
{body}

- 必须：与下一章之间自然过度，下一章大纲预览「\n{next_body[:200]}...\n」

请开始创作{title}正文（要求字数 2000+，必须带上标题，标题固定为‘{title}’，笔触遵循“烽火戏诸侯/长短句张力风”）：
"""
        with open(os.path.join(args.out_dir, f"{filename}.md"), "w", encoding="utf-8") as f:
            f.write(full_prompt)
    print(f"✅ 已成功生成 {len(chapters)} 个独立章节提示词存入 {args.out_dir}")

if __name__ == "__main__":
    main()
