from openai import OpenAI
import os
from dotenv import load_dotenv

# 加载 .env 文件
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path=dotenv_path)

def main():
    api_key = os.getenv("ARK_API_KEY") or os.getenv("VOLCENGINE_ARK_API_KEY")
    if not api_key:
        raise RuntimeError("ARK_API_KEY 未设置，无法运行 main.py 示例。")

    client = OpenAI(
        base_url='https://ark.cn-beijing.volces.com/api/v3',
        api_key=api_key,
        timeout=600.0 
    )

    tools = [{
        "type": "web_search",
        "max_keyword": 2,
    }]

    response = client.responses.create(
        model="deepseek-v3-2-251201",
        input=[{"role": "user", "content": "北京的天气怎么样？"}],
       # tools=tools,
    )

    print(response)


if __name__ == "__main__":
    main()
