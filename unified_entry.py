import argparse
import os
import sys
import uuid
import json
import concurrent.futures
from datetime import datetime
from pathlib import Path

from genesis_api import GenesisDirector
from sequence_planner import SequencePlanner
from chapter_director import ChapterDirector
from db import DatabaseManager
from logger import logger
import hashlib

def run_path_1_reference(file_paths, total_chapters=10, max_workers=3, verbose=False):
    """路径一：原著仿写（神似而形不似） - 多线程工厂版"""
    logger.info(f"\n🚀 [工业化开启] 正在并行创作 {len(file_paths)} 本作品 (并行数: {max_workers})...")
    
    db_manager = DatabaseManager()
    
    def process_book(path):
        book_name = os.path.basename(path).replace(".md", "")
        # 前缀日志，确保并发时不混乱
        pfx = f"[{book_name}]"
        logger.info(f"📖 {pfx} 任务入库，准备动笔...")
        
        try:
            genesis = GenesisDirector()
            planner = SequencePlanner()
            
            # 1. 提取 DNA
            essence = genesis.analyze_reference_essence([path])
            blacklist = essence.get("entity_blacklist", [])
            
            # 2. 生成进化设定
            setting = genesis.generate_evolved_setting(essence)
            
            # 3. 规划大纲
            skeleton = planner.plan_novel_arc(setting)
            
            # 断点续传加固：使用确定的 ID（基于文件路径哈希）以便重启后识别
            file_hash = hashlib.md5(os.path.abspath(path).encode()).hexdigest()[:8]
            novel_id = f"REF-{file_hash}"
            novel_name = f"{book_name}-仿写版"
            
            # 初始化工作空间
            today = datetime.now().strftime("%Y-%m-%d")
            workspace_dir = os.path.join(os.getcwd(), today, novel_name)
            os.makedirs(os.path.join(workspace_dir, "report"), exist_ok=True)
                
            # 存档 DNA 与大纲 (静态查看用)
            with open(os.path.join(workspace_dir, "report", "1DNA核心.md"), "w", encoding="utf-8") as f:
                f.write(f"# DNA 报告: {book_name}\n\n")
                f.write(json.dumps(essence, ensure_ascii=False, indent=2))
            with open(os.path.join(workspace_dir, "report", "2大纲.md"), "w", encoding="utf-8") as f:
                f.write(f"# 创作蓝图: {novel_name}\n\n")
                f.write(json.dumps(skeleton, ensure_ascii=False, indent=2))

            director = ChapterDirector(
                novel_id=novel_id,
                novel_name=novel_name,
                setting=setting,
                skeleton=skeleton,
                total_chapters=total_chapters,
                blacklist=blacklist,
                db_manager=db_manager,
                workspace_dir=workspace_dir,
                verbose=verbose
            )
            
            director.run_pipeline()
            logger.info(f"✅ {pfx} 全书创作完成，已存入: {workspace_dir}")
            return book_name
        except Exception as e:
            logger.error(f"❌ {pfx} 任务溃败：{str(e)}")
            import traceback
            logger.debug(traceback.format_exc())
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_book, p): p for p in file_paths}
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if res:
                logger.info(f"🏁 [工厂出货] {res} 制作完毕。")

def run_path_2_prompt(background_prompt, total_chapters=10, verbose=False):
    """路径二：背景设定原创（单本精修模式）"""
    logger.info(f"\n🌟 [命题创作开启] 正在针对该设定进行深度构思...")
    
    genesis = GenesisDirector()
    planner = SequencePlanner()
    
    setting = genesis.generate_genesis_setting(background_prompt)
    skeleton = planner.plan_novel_arc(setting)
    
    # 命题创作模式：基于提示词摘要的确定 ID
    prompt_hash = hashlib.md5(background_prompt.encode()).hexdigest()[:8]
    novel_id = f"PROMPT-{prompt_hash}"
    novel_name = setting.get("novel_title", f"命题创作-{prompt_hash}")
    
    today = datetime.now().strftime("%Y-%m-%d")
    workspace_dir = os.path.join(os.getcwd(), today, novel_name)
    os.makedirs(os.path.join(workspace_dir, "report"), exist_ok=True)
        
    with open(os.path.join(workspace_dir, "report", "1大纲.md"), "w", encoding="utf-8") as f:
        f.write(f"# 创作蓝图: {novel_name}\n\n")
        f.write(json.dumps(skeleton, ensure_ascii=False, indent=2))

    director = ChapterDirector(
        novel_id=novel_id,
        novel_name=novel_name,
        setting=setting,
        skeleton=skeleton,
        total_chapters=total_chapters,
        workspace_dir=workspace_dir,
        verbose=verbose
    )
    
    director.run_pipeline()
    logger.info(f"✅ [原创模式完成] 作品《{novel_name}》已产出。")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="短篇小说 API 进化系统 - 工业化全自动工厂")
    parser.add_argument("--mode", type=str, choices=["reference", "prompt"], required=True, help="创作模式")
    parser.add_argument("--paths", type=str, nargs="+", help="原著文件路径列表 (仅限 reference 模式)")
    parser.add_argument("--background", type=str, help="背景设定描述 (仅限 prompt 模式)")
    parser.add_argument("--chapters", type=int, default=10, help="生成章节数")
    parser.add_argument("--workers", type=int, default=3, help="并行并发数 (建议 3-5)")
    parser.add_argument("--verbose", action="store_true", help="显示极尽详细的工程日志（默认关闭，仅输出核心事件）")

    args = parser.parse_args()

    if args.mode == "reference":
        if not args.paths:
            print("❌ 错误: reference 模式下必须提供 --paths")
        else:
            run_path_1_reference(args.paths, args.chapters, max_workers=args.workers, verbose=args.verbose)
    elif args.mode == "prompt":
        if not args.background:
            logger.error("❌ 错误: prompt 模式下必须提供 --background")
        else:
            run_path_2_prompt(args.background, args.chapters, verbose=args.verbose)
