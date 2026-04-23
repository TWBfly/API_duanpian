import os
from google import genai
from google.genai import types

def generate():
    client = genai.Client(
        api_key="AIzaSyBaqQfhLTWWIp2KW60uaB3x2bBb2w_B_so",
    )
    model = "gemma-4-31b-it"
    contents = [types.Content(role="user", parts=[types.Part.from_text(text="Hello!")])]
    
    try:
        generate_content_config = types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(
                include_thoughts=True
            )
        )
        print("Config created successfully with include_thoughts=True")
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=generate_content_config,
        )
        print(f"Response: {response.text}")
    except Exception as e:
        print(f"Failed with include_thoughts=True: {e}")

if __name__ == "__main__":
    generate()
