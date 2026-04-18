from chroma_memory import ChromaMemory
import os

def test_fallback():
    print("🚀 [集成测试] 验证 ChromaMemory 降级逻辑...")
    # 强制清理环境 (如果有残留)
    if os.path.exists(".chroma_db_integration_test"):
        import shutil
        shutil.rmtree(".chroma_db_integration_test")
        
    try:
        memory = ChromaMemory(db_path=".chroma_db_integration_test")
        print("✅ ChromaMemory 初始化成功。")
        
        # 测试写入
        memory.add_plot("这是一段测试剧情", metadata={"test": "true"})
        print("✅ 写入测试成功。")
        
        # 测试查询
        doc, sim = memory.search_similar_plot("这段剧情怎么样", threshold=0.0)
        print(f"✅ 查询结果: {doc}, 相似度: {sim}")
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if os.path.exists(".chroma_db_integration_test"):
            import shutil
            shutil.rmtree(".chroma_db_integration_test")

if __name__ == "__main__":
    test_fallback()
