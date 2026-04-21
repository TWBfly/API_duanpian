import os
import shutil
from pathlib import Path

from auditors import DisguiseLogicAuditor
from db import DatabaseManager, ForeshadowingLedger
from evolution_api import MasterEvolutionEngine
from human_revision_importer import HumanRevisionBulkImporter


def main():
    print("========================================")
    print("🚀 短篇小说无尽演化引擎 - 结构化评估版")
    print("========================================")

    base_dir = Path(__file__).resolve().parent
    db_path = base_dir / "novel_memory.db"
    chroma_path = base_dir / ".chroma_db"
    if db_path.exists():
        os.remove(db_path)
    if chroma_path.exists():
        shutil.rmtree(chroma_path)

    db_manager = DatabaseManager()
    ledger = ForeshadowingLedger(db_manager)
    ledger.add_clue("北凉关外的飞雪压断了百年老松，那柄名为‘断流’的古剑在铁匠炉里哀鸣。")

    db_manager.create_or_update_book(
        book_id="demo-novel",
        title="雪落客栈",
        genesis={"audience_type": "male_oriented", "master_style": "刀锋短句，雪夜肃杀"},
        status="generating",
    )
    chapter_id = db_manager.upsert_chapter_record(
        book_id="demo-novel",
        chapter_index=1,
        title="第1章",
        chapter_type="prologue",
        skeleton_data={"plot_beat": "雪夜客栈遇刺", "foreshadowing_to_plant": "断流古剑"},
        history_context="无前情提要（开局）。",
        status="generating",
    )

    engine = MasterEvolutionEngine(
        db_manager=db_manager,
        audience_type="male_oriented",
        logic_layer=DisguiseLogicAuditor,
    )
    engine.main_character_name = "徐凤年"

    print("\n--- 【核心测试】：验证结构化落库 + 量化评估 ---")
    result = engine.generate_chapter(
        novel_id="demo-novel",
        seed_prompt="徐凤年在客栈二楼独酌，窗外马蹄声碎，刺客青衣蒙面踏雪而来。",
        title="雪落客栈",
        chapter_type="prologue",
        chapter_index=1,
        skeleton_data={"plot_beat": "雪夜客栈遇刺", "foreshadowing_to_plant": "断流古剑"},
        chapter_id=chapter_id,
        history_context="无前情提要（开局）。",
        candidate_count=1,
    )

    print("\n" + "=" * 50)
    print("【最终锻造结晶】:")
    print(result["content"])
    print("=" * 50)
    print(f"【量化总分】{result['evaluation']['metrics']['overall']:.2f}")
    print(f"【风险项】{result['evaluation']['risk_flags']}")
    print(f"【候选竞赛】{result['candidate_results']}")

    print("\n--- 【配对学习验证】：注册一版人工终稿 ---")
    human_final = (
        "雪腥味先撞进肺里。徐凤年把酒盏倒扣在桌面，指节一紧。"
        "青衣人落地时没有声音，剑却已经到了窗边。楼下的马蹄声没停。"
    )
    db_manager.register_human_revision(
        book_id="demo-novel",
        chapter_index=1,
        content=human_final,
        summary="雪夜客栈遇刺，徐凤年提前感知杀机。",
        notes="人工压缩解释句，增强压迫感。",
    )
    engine.start_perpetual_learning()

    print("\n--- 【批量导入验证】：扫描历史优化/最终稿 ---")
    importer = HumanRevisionBulkImporter(db_manager=db_manager)
    import_summary = importer.import_from_directory(base_dir / "2026-04-17")
    print(f"【导入结果】{import_summary}")

    overview = db_manager.get_pipeline_overview()
    print(
        "\n📊 [概览] "
        f"books={overview['book_count']} "
        f"chapters={overview['chapter_count']} "
        f"machine_finals={overview['machine_final_count']} "
        f"human_finals={overview['human_final_count']} "
        f"pending_pairs={overview['pending_learning_pairs']}"
    )


if __name__ == "__main__":
    main()
