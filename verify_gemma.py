import os
import sys
# Ensure we can import from the current directory
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from llm_client import generate_text_full, DEFAULT_MODEL

def test_google_integration():
    print(f"Default model configured: {DEFAULT_MODEL}")
    prompt = "Hello! Please tell me who you are and if you can 'think' deeply."
    print(f"Testing prompt: {prompt}")
    
    try:
        res = generate_text_full(prompt, system_prompt="You are a helpful assistant with deep thinking capabilities.")
        print("\n--- Response ---")
        print(res['content'])
        print("\n--- Usage ---")
        print(res['usage'])
        print("\n--- Model Used ---")
        print(res['model'])
        
        if "google" in str(res['model']).lower() or "gemma" in str(res['model']).lower():
            print("\n✅ Verification successful: Google/Gemma provider used.")
        else:
            print("\n❌ Verification failed: Unexpected provider/model used.")
            
    except Exception as e:
        print(f"\n❌ Error during verification: {e}")

if __name__ == "__main__":
    test_google_integration()
