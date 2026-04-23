import os
import re
import argparse
import sys
from novel_utils import expected_chapter_indices, normalize_total_chapters, chapter_type_for_index
from prompts_config import get_v3_prompt_bundle

def split_and_prompt_data(content):
    """解析大纲文件并返回结构化数据列表"""
    chapters_data = []
    chinese_num = r'[\u96f6\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e\u53430-9]+'
    pattern_str = rf'^(#{{1,4}})\s*(\u6954\u5b50|\u7b2c{chinese_num}\u7ae0|\u7ed3\u5c40)[:\uff1a]?\s*(.*)$'
    pattern = re.compile(pattern_str, re.MULTILINE)
    
    matches = list(pattern.finditer(content))
    if not matches:
        return []

    for i, m in enumerate(matches):
        chapter_label = m.group(2).strip()
        chapter_suffix = m.group(3).strip()
        full_title = f"{chapter_label}：{chapter_suffix}" if chapter_suffix else chapter_label
        
        start_pos = m.end()
        end_pos = matches[i+1].start() if i + 1 < len(matches) else len(content)
        body = content[start_pos:end_pos].strip()
        
        if chapter_label == "楔子":
            idx = 0
            filename = "00_楔子"
        else:
            try:
                num_str = re.search(r'\d+', chapter_label).group()
                idx = int(num_str)
            except:
                idx = i
            filename = f"{idx:02d}_{chapter_label}"
            
        chapters_data.append({"idx": idx, "filename": filename, "title": full_title, "body": body})
    return chapters_data

def main():
    parser = argparse.ArgumentParser(description="工业化大纲固化器 V3 - 极致同步版")
    parser.add_argument("--input", type=str, required=True, help="输入大纲文件路径")
    parser.add_argument("--out_dir", type=str, default="prompt_v3_final", help="输出文件夹")
    parser.add_argument("--chapters", type=int, default=10, help="主线章节数")
    args = parser.parse_args()
    
    total_chapters = normalize_total_chapters(args.chapters)

    if not os.path.exists(args.input):
        print(f"❌ 错误：未找到输入文件 {args.input}")
        return

    with open(args.input, "r", encoding="utf-8") as f:
        content = f.read()
        
    os.makedirs(args.out_dir, exist_ok=True)
    chapters_list = split_and_prompt_data(content)
    
    if not chapters_list:
        print("❌ 错误：未能从文件中解析出章节内容。")
        return

    for i, item in enumerate(chapters_list):
        idx = item['idx']
        prev_item = chapters_list[i-1] if i > 0 else None
        next_item = chapters_list[i+1] if i + 1 < len(chapters_list) else None
        
        # 直接调用 prompts_config 里的统一 V3 发动机
        full_output = get_v3_prompt_bundle(
            idx=idx,
            total_chapters=total_chapters,
            title=item['title'],
            body=item['body'],
            prev_data=prev_item,
            next_data=next_item
        )
        
        # 写入文件
        save_path = os.path.join(args.out_dir, f"{item['filename']}.md")
        with open(save_path, "w", encoding="utf-8") as f:
            f.write(full_output)
            
    print(f"✅ [同步验证成功] 已调用 prompts_config 统一引擎生成 V3 提示词，存入：{args.out_dir}")

if __name__ == "__main__":
    main()
