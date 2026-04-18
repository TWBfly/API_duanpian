import os
import sys
import argparse
from pathlib import Path

# 动态定位 root 路径
ROOT_DIR = Path(__file__).resolve().parent
sys.path.append(str(ROOT_DIR))
from llm_client import generate_text

def main():
    parser = argparse.ArgumentParser(description="工业化正文批量执行器 - 断点续传神器")
    parser.add_argument("--prompt_dir", type=str, required=True, help="提示词文件夹路径 (如 2026-04-19/xxx/prompt)")
    parser.add_argument("--output", type=str, required=True, help="输出文件路径")
    parser.add_argument("--style", type=str, default="Fenghuo Xi Zhuhou", help="文学风格限定")
    args = parser.parse_args()

    prompt_dir = args.prompt_dir
    output_file = args.output
    
    # 获取提示词列表并排序
    if not os.path.exists(prompt_dir):
        print(f"❌ 错误：路径不存在: {prompt_dir}")
        return

    prompt_files = sorted([f for f in os.listdir(prompt_dir) if f.endswith(".md")])
    if not prompt_files:
        print("❌ 错误：在 prompt 文件夹下未找到提示词文件。")
        return

    print(f"🚀 [工业化执行] 开始批量创作，目标文件: {output_file}")
    
    with open(output_file, "w", encoding="utf-8") as out:
        out.write(f"# 作品创作正文 (手动执行版 - {args.style})\n\n")

    for filename in prompt_files:
        print(f"✍️  正在创作章节：{filename}...")
        with open(os.path.join(prompt_dir, filename), "r", encoding="utf-8") as f:
            prompt_content = f.read()
        
        # 调用大模型生成正文
        chapter_text = generate_text(prompt_content, f"You are a professional novel writer. Write in {args.style} style. Ensure 2000+ words.")
        
        if chapter_text:
            print(f"✅ 章节 {filename} 创作完成。")
            with open(output_file, "a", encoding="utf-8") as out:
                out.write(f"\n\n{chapter_text}\n\n---\n")
        else:
            print(f"❌ 章节 {filename} 创作失败。")

    print(f"✨ 全书创作完成！最终文件存放在：{output_file}")

if __name__ == "__main__":
    main()
