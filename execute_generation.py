import os
import sys
import argparse
import re
from pathlib import Path

# 动态定位 root 路径
ROOT_DIR = Path(__file__).resolve().parent
sys.path.append(str(ROOT_DIR))
from db import DatabaseManager
from chroma_memory import ChromaMemory
from llm_client import generate_text
from novel_utils import expected_chapter_indices, normalize_total_chapters
from reference_guard import HardReferenceGuard, ReferenceFingerprintLibrary

def main():
    parser = argparse.ArgumentParser(description="工业化正文批量执行器 - 断点续传神器")
    parser.add_argument("--prompt_dir", type=str, required=True, help="提示词文件夹路径 (如 2026-04-19/xxx/prompt)")
    parser.add_argument("--output", type=str, required=True, help="输出文件路径")
    parser.add_argument("--style", type=str, default="Fenghuo Xi Zhuhou", help="文学风格限定")
    parser.add_argument("--book_id", type=str, help="书籍 ID。若为参考仿写模式，必须提供以启用原著硬查重。")
    parser.add_argument("--chapters", type=int, default=10, help="主线章节数，楔子另算；短篇系统上限为10")
    args = parser.parse_args()

    prompt_dir = args.prompt_dir
    output_file = args.output
    try:
        total_chapters = normalize_total_chapters(args.chapters)
    except ValueError as exc:
        print(f"❌ 错误：{exc}")
        return
    
    # 获取提示词列表并排序
    if not os.path.exists(prompt_dir):
        print(f"❌ 错误：路径不存在: {prompt_dir}")
        return

    indexed_prompts = []
    invalid_prompt_files = []
    for filename in os.listdir(prompt_dir):
        if not filename.endswith(".md"):
            continue
        match = re.match(r"^(\d+)_", filename)
        if not match:
            invalid_prompt_files.append(filename)
            continue
        indexed_prompts.append((int(match.group(1)), filename))

    expected = set(expected_chapter_indices(total_chapters))
    actual = {idx for idx, _ in indexed_prompts}
    overflow = sorted(actual - expected)
    missing = sorted(expected - actual)
    if invalid_prompt_files or overflow or missing:
        if invalid_prompt_files:
            print(f"❌ 错误：存在无法识别章节序号的提示词文件：{invalid_prompt_files[:5]}")
        if overflow:
            print(f"❌ 错误：提示词目录包含越界章节：{overflow}，当前契约只允许 0..{total_chapters}")
        if missing:
            print(f"❌ 错误：提示词目录缺失章节：{missing}")
        return

    prompt_files = [filename for _, filename in sorted(indexed_prompts)]
    if not prompt_files:
        print("❌ 错误：在 prompt 文件夹下未找到提示词文件。")
        return

    report_dir = Path(prompt_dir).parent / "report"
    is_reference_workspace = (report_dir / "1DNA核心.md").exists()
    hard_guard = None
    if is_reference_workspace:
        if not args.book_id:
            print("❌ 错误：检测到参考仿写工作区，必须提供 --book_id 以启用原著硬查重。")
            return
        db = DatabaseManager()
        library = ReferenceFingerprintLibrary(db)
        bundle = library.load_bundle(args.book_id)
        if not bundle:
            print(f"❌ 错误：未找到书籍 {args.book_id} 的原著指纹库，拒绝继续生成。")
            return
        hard_guard = HardReferenceGuard(args.book_id, bundle, ChromaMemory())

    print(f"🚀 [工业化执行] 开始批量创作，目标文件: {output_file}")
    
    with open(output_file, "w", encoding="utf-8") as out:
        out.write(f"# 作品创作正文 (手动执行版 - {args.style})\n\n")

    for filename in prompt_files:
        print(f"✍️  正在创作章节：{filename}...")
        with open(os.path.join(prompt_dir, filename), "r", encoding="utf-8") as f:
            prompt_content = f.read()
        
        # 调用大模型生成正文
        chapter_text = generate_text(
            prompt_content,
            f"You are a professional novel writer. Write in {args.style} style. Ensure 2000+ words.",
            task_profile="chapter_write",
        )
        
        if chapter_text:
            if hard_guard:
                audit = hard_guard.audit_body_text(chapter_text)
                if not audit.get("passed"):
                    print(f"🛑 章节 {filename} 触发原著硬查重闸门：{'；'.join(audit.get('blockers', [])[:3])}")
                    return
            print(f"✅ 章节 {filename} 创作完成。")
            with open(output_file, "a", encoding="utf-8") as out:
                out.write(f"\n\n{chapter_text}\n\n---\n")
        else:
            print(f"❌ 章节 {filename} 创作失败。")

    print(f"✨ 全书创作完成！最终文件存放在：{output_file}")

if __name__ == "__main__":
    main()
