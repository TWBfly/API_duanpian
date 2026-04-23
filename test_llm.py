import sys
import os
sys.path.append('.')
from llm_client import generate_text

try:
    print("Testing LLM...")
    res = generate_text("Hi, say 'OK' if you can hear me.", "You are a tester.")
    print(f"Result: {res}")
except Exception as e:
    print(f"Error: {e}")
