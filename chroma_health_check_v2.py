import chromadb
import sys
from pathlib import Path

class SimpleEmbeddingFunction(chromadb.EmbeddingFunction):
    def __call__(self, input):
        # Extremely simple embedding: just a mock vector for testing
        return [[0.1] * 384 for _ in input]

def health_check():
    print("✨ Starting ChromaDB Health Check V2 (with simple fallback)...")
    db_path = Path(__file__).resolve().parent / ".chroma_db_test_v2"
    
    try:
        client = chromadb.PersistentClient(path=str(db_path))
        print("✅ Client creation successful.")
        
        # Test with custom embedding function to bypass onnxruntime
        collection = client.get_or_create_collection(
            name="health_check_collection",
            embedding_function=SimpleEmbeddingFunction()
        )
        print("✅ Collection creation successful (using fallback embedding).")
        
        collection.add(
            documents=["Small test document."],
            metadatas=[{"type": "test"}],
            ids=["test_id_v2"]
        )
        print("✅ Data insertion successful.")
        
        results = collection.query(query_texts=["test"], n_results=1)
        print(f"✅ Query successful. Results found: {len(results['ids'])}")
        
        import shutil
        shutil.rmtree(db_path)
        print("✅ Cleaned up test db.")
        print("\n🏆 FALLBACK STRATEGY VERIFIED.")
        
    except Exception as e:
        print(f"❌ Health check failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    health_check()
