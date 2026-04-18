import chromadb
import sys
from pathlib import Path

def health_check():
    print("✨ Starting ChromaDB Health Check...")
    db_path = Path(__file__).resolve().parent / ".chroma_db_test"
    
    try:
        # 1. Test Client Creation
        client = chromadb.PersistentClient(path=str(db_path))
        print("✅ Client creation successful.")
        
        # 2. Test Collection Creation
        collection = client.get_or_create_collection(name="health_check_collection")
        print("✅ Collection creation successful.")
        
        # 3. Test Add/Query
        collection.add(
            documents=["Health check document content."],
            metadatas=[{"type": "test"}],
            ids=["test_id"]
        )
        print("✅ Data insertion successful.")
        
        results = collection.query(query_texts=["Health check"], n_results=1)
        if len(results['ids']) > 0:
            print("✅ Query retrieval successful.")
        else:
            print("❌ Query returned no results.")
            sys.exit(1)
            
        # 4. Cleanup test db
        import shutil
        shutil.rmtree(db_path)
        print("✅ Test data cleaned up.")
        print("\n🏆 ChromaDB IS HEALTHY.")
        
    except Exception as e:
        print(f"❌ Health check failed with error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    health_check()
