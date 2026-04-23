import os
from google import genai
from google.genai import types

def generate():
    client = genai.Client(
        api_key="AIzaSyBaqQfhLTWWIp2KW60uaB3x2bBb2w_B_so", # Hardcoded for test
    )

    model = "gemma-4-31b-it"
    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_text(text="""Hello!"""),
            ],
        ),
    ]
    # user said close google search
    # tools = [
    #     types.Tool(googleSearch=types.GoogleSearch(
    #     )),
    # ]
    try:
        generate_content_config = types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(
                thinking_level="HIGH",
            ),
            # tools=tools,
        )
        print("Config created successfully with thinking_level")
    except Exception as e:
        print(f"Failed to create config with thinking_level: {e}")

    try:
        # Actually try to generate
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=generate_content_config if 'generate_content_config' in locals() else None,
        )
        print(f"Response: {response.text}")
    except Exception as e:
        print(f"Generation failed: {e}")

if __name__ == "__main__":
    generate()
