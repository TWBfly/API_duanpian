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
    
    # 1. Load Reference Style (Gold Library)
    ref_path = "/Users/tang/PycharmProjects/pythonProject/fiveNovel/2026-03-27/半糖缘/半糖缘.md"
    if os.path.exists(ref_path):
        with open(ref_path, "r", encoding="utf-8") as f:
            content = f.read()
            # Split by chapters or long paragraphs to load into gold library
            samples = content.split("\n\n")
            db.clear_and_load_gold([s for s in samples if len(s.strip()) > 50])
    
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
