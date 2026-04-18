import os
from dotenv import load_dotenv
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

# 自动加载当前目录下的 .env 文件
load_dotenv()

# 默认设置
OPENROUTER_BASE_URL = 'https://openrouter.ai/api/v1'
ARK_BASE_URL = 'https://ark.cn-beijing.volces.com/api/v3'
DEFAULT_MODEL = os.getenv("LLM_MODEL", "auto")

def _get_backend_config():
    ark_key = os.getenv("ARK_API_KEY") or os.getenv("VOLCENGINE_ARK_API_KEY")
    if ark_key:
        return {
            "provider": "ark",
            "api_key": ark_key,
            "base_url": ARK_BASE_URL,
            "default_model": os.getenv("ARK_MODEL") or os.getenv("VOLCENGINE_ARK_MODEL") or os.getenv("LLM_MODEL"),
        }

    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    if openrouter_key:
        return {
            "provider": "openrouter",
            "api_key": openrouter_key,
            "base_url": OPENROUTER_BASE_URL,
            "default_model": os.getenv("OPENROUTER_MODEL") or os.getenv("LLM_MODEL") or "openrouter/elephant-alpha",
        }

    raise RuntimeError("未设置 API_KEY，无法调用 LLM。")

def _resolve_model(requested_model, backend_config):
    model = requested_model
    if model in (None, "", "auto"):
        model = backend_config.get("default_model")

    if not model:
        provider = backend_config["provider"]
        raise RuntimeError(
            f"当前使用 {provider} 后端，但未配置模型名。请设置 "
            "LLM_MODEL / OPENROUTER_MODEL / ARK_MODEL / VOLCENGINE_ARK_MODEL。"
        )

    if backend_config["provider"] == "ark" and str(model).startswith("openrouter/"):
        raise RuntimeError(
            "当前正在使用 Ark 后端，但模型名是 OpenRouter 模型。"
            "请设置 ARK_MODEL/LLM_MODEL，或显式传入 Ark 模型名。"
        )
    return model

def resolve_model_name(requested_model=DEFAULT_MODEL):
    return _resolve_model(requested_model, _get_backend_config())

def get_ark_client(timeout=120.0):
    """
    兼容层：虽保留 get_ark_client 名称，但实际指向 OpenRouter 或 Ark。
    """
    backend = _get_backend_config()
    base_url = backend["base_url"]

    return OpenAI(
        base_url=base_url, 
        api_key=backend["api_key"], 
        timeout=timeout,
        default_headers={
            "HTTP-Referer": "https://github.com/OpenNovel/API_duanpian", # 选填
            "X-Title": "Novel Evolution Engine", # 选填
        } if base_url == OPENROUTER_BASE_URL else None
    )

def generate_text(prompt, system_prompt="You are an expert novel writer.", model=DEFAULT_MODEL):
    """通用文本生成接口"""
    res = generate_text_full(prompt, system_prompt, model)
    return res["content"]

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
def _request_chat_completion(client, model, messages):
    return client.chat.completions.create(model=model, messages=messages)

def generate_text_full(prompt, system_prompt="You are an expert novel writer.", model=DEFAULT_MODEL):
    """带用量统计的文本生成接口"""
    backend = _get_backend_config()
    client = get_ark_client()
    resolved_model = _resolve_model(model, backend)
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
    response = _request_chat_completion(client, resolved_model, messages)
    content = response.choices[0].message.content or ""
    
    # 提取用量信息
    usage = getattr(response, "usage", None)
    usage_data = {
        "prompt_tokens": usage.prompt_tokens if usage else 0,
        "completion_tokens": usage.completion_tokens if usage else 0,
        "total_tokens": usage.total_tokens if usage else 0,
    }
    
    return {
        "content": content,
        "usage": usage_data,
        "model": resolved_model
    }

def generate_text_safe(prompt, system_prompt="You are a master style extractor.", model=DEFAULT_MODEL):
    """带有异常捕获的文本生成接口"""
    try:
        return generate_text(prompt, system_prompt, model)
    except Exception as e:
        print(f"   ❌ [LLM 响应失败] {str(e)[:100]}")
        return None
