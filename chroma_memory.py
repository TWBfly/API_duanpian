import chromadb
import uuid
import os
from pathlib import Path


class InMemoryCollection:
    def __init__(self):
        self.items = []

    def count(self):
        return len(self.items)

    def add(self, documents, metadatas, ids):
        for document, metadata, item_id in zip(documents, metadatas, ids):
            self.items.append({
                "id": item_id,
                "document": document,
                "metadata": metadata or {},
            })

    def query(self, query_texts, n_results=1, where=None):
        query = query_texts[0] if query_texts else ""
        filtered = [item for item in self.items if _metadata_match(item["metadata"], where)]
        ranked = sorted(
            filtered,
            key=lambda item: _simple_similarity(query, item["document"]),
            reverse=True,
        )[:n_results]
        documents = [item["document"] for item in ranked]
        metadatas = [item["metadata"] for item in ranked]
        distances = [1.0 - _simple_similarity(query, item["document"]) for item in ranked]
        return {
            "documents": [documents],
            "metadatas": [metadatas],
            "distances": [distances],
        }

    def delete(self, where=None):
        self.items = [item for item in self.items if not _metadata_match(item["metadata"], where)]


def _metadata_match(metadata, where):
    if not where:
        return True
    for key, value in where.items():
        if metadata.get(key) != value:
            return False
    return True


def _simple_similarity(left, right):
    left_set = set((left or "").split())
    right_set = set((right or "").split())
    if not left_set or not right_set:
        left_set = set(left or "")
        right_set = set(right or "")
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)

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
        self.client = None
        self.plot_collection = None
        self.reference_collection = None
        
        # 工业化加固：预检查物理数据库健康度，防止 Rust 层直接 Panic
        db_path_obj = Path(db_path)
        if db_path_obj.exists():
            # 检查是否可写，以及是否存在明显的锁定文件
            if not os.access(db_path, os.W_OK):
                print(f"⚠️ [向量库] 数据库目录 {db_path} 权限不足，降级到 InMemoryMode。")
                self._init_in_memory()
                return

        try:
            self.client = chromadb.PersistentClient(path=str(db_path))
            self._init_collections()
        except BaseException as e:
            error_str = str(e)
            print(f"⚠️ [环境修复] PersistentClient 初始化失败 ({error_str})")
            if "range start index" in error_str or "panic" in error_str.lower():
                print("💡 [诊断报告] 检测到底层 Rust/SQLite 数据损坏。建议：手动删除 '.chroma_db' 文件夹后重启系统。")
            
            print("🔄 [自动降级] 正在切换到 InMemoryVectorMode 以保证业务不中断...")
            self._init_in_memory()
            return

    def _init_in_memory(self):
        self.plot_collection = InMemoryCollection()
        self.reference_collection = InMemoryCollection()

    def _init_collections(self):
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
        try:
            self.plot_collection = self.client.get_or_create_collection(
                name="plot_memory",
                embedding_function=embedding_function,
                metadata={"hnsw:space": "cosine"}
            )
            self.reference_collection = self.client.get_or_create_collection(
                name="reference_memory",
                embedding_function=embedding_function,
                metadata={"hnsw:space": "cosine"}
            )
            print("✅ [本地向量库] 剧情记忆集合就绪。")
        except BaseException as e:
            print(f"⚠️ [环境修复] Collection 初始化失败 ({e})，切换到 InMemoryVectorMode。")
            self.plot_collection = InMemoryCollection()
            self.reference_collection = InMemoryCollection()

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

    def add_reference_chunk(self, text, metadata=None):
        if not metadata:
            metadata = {"source": "reference_chunk"}
        self.reference_collection.add(
            documents=[text],
            metadatas=[metadata],
            ids=[str(uuid.uuid4())]
        )

    def search_similar_reference(self, text, top_k=1, threshold=0.85, where_filter=None):
        if self.reference_collection.count() == 0:
            return None, 0.0, None

        kwargs = {
            "query_texts": [text],
            "n_results": top_k,
        }
        if where_filter:
            kwargs["where"] = where_filter

        results = self.reference_collection.query(**kwargs)
        distances = results["distances"][0]
        documents = results["documents"][0]
        metadatas = results.get("metadatas", [[]])[0]
        if not distances:
            return None, 0.0, None

        similarity = 1.0 - distances[0]
        if similarity >= threshold:
            metadata = metadatas[0] if metadatas else None
            return documents[0], similarity, metadata
        return None, similarity, None

    def remove_novel_plots(self, novel_id):
        """删除失败任务为某本书写入的向量记忆。"""
        if not novel_id:
            return
        try:
            self.plot_collection.delete(where={"novel_id": novel_id})
        except Exception:
            # Chroma 清理失败不应阻断主流程，调用方会继续做 SQL/文件回滚。
            pass

    def remove_reference_chunks(self, book_id):
        if not book_id:
            return
        try:
            self.reference_collection.delete(where={"book_id": book_id})
        except Exception:
            pass
