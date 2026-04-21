import sys
import os
from pathlib import Path

# Add the current directory to sys.path to import modules
sys.path.append(str(Path(__file__).resolve().parent))

from db import DatabaseManager
from evolution_api import MasterEvolutionEngine
from genesis_api import GenesisDirector
from auditors import DisguiseLogicAuditor

def start():
    db = DatabaseManager()
    
    # 1. Legacy Gold Library loading is disabled.
    ref_path = "/Users/tang/PycharmProjects/pythonProject/fiveNovel/2026-03-27/半糖缘/半糖缘.md"
    if os.path.exists(ref_path):
        print("⚠️ [安全策略] 已停用原文全文写入 Gold Library 的旧路径，仅保留抽象规则学习。")
    
    # 2. Genesis: Create Book Setting
    director = GenesisDirector()
    title = "白月光回国了，统统闪开"
    setting = director.generate_genesis_setting(title)
    
    db.create_or_update_book(
        book_id="white-moonlight-return",
        title=title,
        genesis=setting,
        status="initializing"
    )
    
    print(f"✔️ Book '{title}' initialized with Genesis setting.")
    return setting

if __name__ == "__main__":
    start()
