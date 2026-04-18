import os
import argparse
import concurrent.futures
from unified_entry import run_path_1_reference

def run_batch_reference(directory, chapters=10, max_workers=2):
    """
    工业级批处理器：并发启动多本原著的进化任务
    directory: 存放原著 .md 文件的目录
    chapters: 每本书生成的章节数
    max_workers: 同时进行的任务数（建议不要超过 3，因为内部还有并发）
    """
    if not os.path.exists(directory):
        print(f"❌ 目录不存在: {directory}")
        return

    files = [os.path.join(directory, f) for f in os.listdir(directory) if f.endswith('.md')]
    if not files:
        print(f"ℹ️ 目录下未找到 .md 原著文件。")
        return

    print(f"🚀 [并行调度启动] 发现 {len(files)} 本原著，计划并发数: {max_workers}")

    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        # 每个文件启动一个任务
        futures = {executor.submit(run_path_1_reference, [f], chapters): f for f in files}
        
        for future in concurrent.futures.as_completed(futures):
            filename = futures[future]
            try:
                future.result()
                print(f"✅ [批量任务成功] {os.path.basename(filename)}")
            except Exception as e:
                print(f"❌ [批量任务失败] {os.path.basename(filename)}: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="短篇小说 API 进化系统 - 工业级并发运行工具")
    parser.add_argument("--dir", type=str, required=True, help="存放原著文件的目录")
    parser.add_argument("--chapters", type=int, default=10, help="每本书生成的章节数")
    parser.add_argument("--workers", type=int, default=2, help="同时生产的书籍数量")

    args = parser.parse_args()
    run_batch_reference(args.dir, args.chapters, args.workers)
