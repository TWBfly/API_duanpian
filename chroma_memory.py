import chromadb
import uuid
from pathlib import Path

class SafeEmbeddingFunction(chromadb.EmbeddingFunction):
    """
    一个极其稳健的 Fallback Embedding 函数。
    在 onnxruntime 损坏的本地环境下，提供最基础的向量映射以防止系统崩溃。
    """
    def __init__(self):
        # 即使 init 失败也不会崩溃
        pass

    def __call__(self, input):
        # 返回一个简单的、虽然语义能力弱但保证维度一致且合法的 mock 向量 (384维)
        import hashlib
        vectors = []
        for text in input:
            # 使用哈希种子生成确定性的 mock 向量
            seed = int(hashlib.md5(text.encode('utf-8')).hexdigest(), 16)
            # 生成 384 个伪随机数，保证同一文本生成的向量一致
            import random
            random.seed(seed)
            vectors.append([random.random() for _ in range(384)])
        return vectors

class ChromaMemory:
    def __init__(self, db_path=None):
        if db_path is None:
            db_path = Path(__file__).resolve().parent / ".chroma_db"
        self.client = chromadb.PersistentClient(path=str(db_path))
        
        # 1. 甄别可用 Embedding 引擎
        embedding_function = None
        try:
            from chromadb.utils import embedding_functions
            # 尝试预加载默认函数，如果 onnxruntime 损坏，这里会抛错
            default_ef = embedding_functions.DefaultEmbeddingFunction()
            # 简单测试一下
            default_ef(["test download"])
            embedding_function = default_ef
            print("💡 [本地向量库] 使用默认 OnnxRuntime 引擎。")
        except Exception as e:
            print(f"⚠️ [环境修复] 检测到引擎依赖异常 ({e})，正在挂载 SafeEmbeddingMode 补丁...")
            embedding_function = SafeEmbeddingFunction()
            
        # 2. 挂载集合
        self.plot_collection = self.client.get_or_create_collection(
            name="plot_memory",
            embedding_function=embedding_function,
            metadata={"hnsw:space": "cosine"}
        )
        print("✅ [本地向量库] 剧情记忆集合就绪。")

    def search_similar_plot(self, plot_text, top_k=1, threshold=0.75, where_filter=None):
        """撞库：查询是否存在高相似度的套路桥段"""
        # 如果库空，直接返回
        if self.plot_collection.count() == 0:
            return None, 0.0
            
        kwargs = {
            "query_texts": [plot_text],
            "n_results": top_k
        }
        if where_filter:
            kwargs["where"] = where_filter

        results = self.plot_collection.query(**kwargs)
        
        # ChromaDB 余弦距离：值越小越相似 (distance = 1 - cosine_similarity)
        # 所以 similarity = (1 - distance)
        distances = results['distances'][0]
        documents = results['documents'][0]
        
        if not distances:
            return None, 0.0
            
        # 转换为相似度分数 (这个依赖不同版本的 emb 函数，这里统一用大致估算或直接卡distance)
        # 若 distance 极小 (< 0.25)，说明高度相似(>0.75)
        closest_distance = distances[0]
        similarity = 1.0 - closest_distance
        
        if similarity >= threshold:
            return documents[0], similarity
        return None, similarity

    def add_plot(self, plot_text, metadata=None):
        if not metadata:
            metadata = {"source": "sandbox"}
        self.plot_collection.add(
            documents=[plot_text],
            metadatas=[metadata],
            ids=[str(uuid.uuid4())]
        )

    def remove_novel_plots(self, novel_id):
        """删除失败任务为某本书写入的向量记忆。"""
        if not novel_id:
            return
        try:
            self.plot_collection.delete(where={"novel_id": novel_id})
        except Exception:
            # Chroma 清理失败不应阻断主流程，调用方会继续做 SQL/文件回滚。
            pass
