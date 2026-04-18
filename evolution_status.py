from db import DatabaseManager


def show_dashboard():
    db = DatabaseManager()

    print("\n" + "=" * 60)
    print("🚀 亿级短篇小说全自动进化引擎 - 结构化智力看板")
    print("=" * 60)

    stats = db.get_learning_stats()
    overview = db.get_pipeline_overview()
    print("\n🧠 规则积累:")
    print(f"   - 剧情伏笔法则: {stats.get('plot_rule_total', 0)} 条")
    print(f"   - 人类文风法则: {stats.get('style_rule_total', 0)} 条")

    print("\n🏗️ 生产资产:")
    print(f"   - 书籍档案: {overview['book_count']} 本")
    print(f"   - 章节档案: {overview['chapter_count']} 章")
    print(f"   - 机器终稿: {overview['machine_final_count']} 版")
    print(f"   - 人工终稿: {overview['human_final_count']} 版")

    print("\n🔁 闭环状态:")
    print(f"   - 待处理配对学习: {overview['pending_learning_pairs']} 组")
    print(f"   - 待运行任务: {overview['pending_tasks']} 个")
    print(f"   - 重试中任务: {overview['retrying_tasks']} 个")
    print(f"   - 运行中任务: {overview['running_tasks']} 个")
    print(f"   - 失败任务: {overview['failed_tasks']} 个")

    latest = db.get_latest_rules(5)
    print("\n🔮 最近顿悟规则 (Top 5):")
    if not latest:
        print("   暂无进化记录，系统正在酝酿中...")
    else:
        for category, rule in latest:
            category_cn = "剧情" if "plot" in category else "文风"
            print(f"   [{category_cn}] {rule}")

    print("\n" + "=" * 60)
    print("💡 系统状态: 已支持结构化落库、量化评分、规则回写与 SQLite 任务队列")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    show_dashboard()
