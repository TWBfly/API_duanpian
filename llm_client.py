import os
from dotenv import load_dotenv
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None

# 自动加载当前目录下的 .env 文件
load_dotenv()

# 默认设置
OPENROUTER_BASE_URL = 'https://openrouter.ai/api/v1'
ARK_BASE_URL = 'https://ark.cn-beijing.volces.com/api/v3'
DEEPSEEK_BASE_URL = 'https://api.deepseek.com'
DEFAULT_MODEL = os.getenv("LLM_MODEL", "auto")

TASK_PROFILES = {
    "chapter_write": {"max_tokens": 3200},
    "hook_write": {"max_tokens": 260},
    "planner_json": {"max_tokens": 2600},
    "genesis_json": {"max_tokens": 1800},
    "master_audit": {"max_tokens": 1400},
    "span_fix": {"max_tokens": 1200},
    "audit_short": {"max_tokens": 320},
    "audit_medium": {"max_tokens": 680},
    "reference_semantic": {"max_tokens": 480},
    "id_extract": {"max_tokens": 120},
    "learning_json": {"max_tokens": 520},
}

def _get_all_backends():
    backends = {}
    
    # 0. Google
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        backends["google"] = {
            "api_key": gemini_key,
            "default_model": os.getenv("GEMINI_MODEL") or os.getenv("LLM_MODEL") or "gemma-4-31b-it",
        }
        
    # 1. DeepSeek
    deepseek_key = os.getenv("DEEPSEEK_API_KEY")
    if deepseek_key:
        backends["deepseek"] = {
            "api_key": deepseek_key,
            "base_url": DEEPSEEK_BASE_URL,
            "default_model": os.getenv("DEEPSEEK_MODEL") or "deepseek-reasoner",
        }
        
    # 2. Ark
    ark_key = os.getenv("ARK_API_KEY") or os.getenv("VOLCENGINE_ARK_API_KEY")
    if ark_key:
        backends["ark"] = {
            "api_key": ark_key,
            "base_url": ARK_BASE_URL,
            "default_model": os.getenv("ARK_MODEL") or os.getenv("LLM_MODEL"),
        }
        
    # 3. OpenRouter
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    if openrouter_key:
        backends["openrouter"] = {
            "api_key": openrouter_key,
            "base_url": OPENROUTER_BASE_URL,
            "default_model": os.getenv("OPENROUTER_MODEL") or "openrouter/elephant-alpha",
        }
    return backends

def _get_backend_for_model(model_name):
    backends = _get_all_backends()
    
    # 如果指定了模型名，尝试通过前缀路由
    if model_name:
        if "deepseek" in model_name.lower():
            if "deepseek" in backends: return "deepseek", backends["deepseek"]
            if "openrouter" in backends: return "openrouter", backends["openrouter"]
        if "gemma" in model_name.lower() or "gemini" in model_name.lower():
            if "google" in backends: return "google", backends["google"]
    
    # 默认兜底逻辑：按原有优先级返回第一个可用的
    for p in ["google", "deepseek", "ark", "openrouter"]:
        if p in backends:
            return p, backends[p]
            
    raise RuntimeError("未检测到任何可用的 LLM 后端。")

def _get_backend_config():
    """保留旧接口，返回优先级最高的后端"""
    p, cfg = _get_backend_for_model(None)
    cfg["provider"] = p
    return cfg

def _resolve_model(requested_model, backend_config):
    model = requested_model
    if model in (None, "", "auto"):
        model = backend_config.get("default_model")
    return model

def resolve_model_name(requested_model=DEFAULT_MODEL):
    p, cfg = _get_backend_for_model(requested_model)
    return _resolve_model(requested_model, cfg)


def _build_request_kwargs(task_profile=None, max_tokens=None):
    profile = TASK_PROFILES.get(task_profile, {})
    resolved_max_tokens = max_tokens if max_tokens is not None else profile.get("max_tokens")
    request_kwargs = {}
    if resolved_max_tokens:
        request_kwargs["max_tokens"] = int(resolved_max_tokens)
    return request_kwargs

def get_ark_client(timeout=120.0, provider=None, api_key=None, base_url=None):
    """
    获取指定或默认 Provider 的 Client
    """
    if not provider:
        p, cfg = _get_backend_for_model(None)
        provider = p
        api_key = cfg["api_key"]
        base_url = cfg.get("base_url")

    if provider == "google":
        if genai is None:
            raise RuntimeError("未安装 google-genai，请运行 pip install google-genai")
        return genai.Client(api_key=api_key)

    return OpenAI(
        base_url=base_url, 
        api_key=api_key, 
        timeout=timeout,
        default_headers={
            "HTTP-Referer": "https://github.com/OpenNovel/API_duanpian", 
            "X-Title": "Novel Evolution Engine", 
        } if base_url == OPENROUTER_BASE_URL else None
    )

def generate_text(
    prompt,
    system_prompt="You are an expert novel writer.",
    model=DEFAULT_MODEL,
    task_profile=None,
    max_tokens=None,
):
    """通用文本生成接口"""
    res = generate_text_full(
        prompt,
        system_prompt,
        model,
        task_profile=task_profile,
        max_tokens=max_tokens,
    )
    return res["content"]

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
def _request_chat_completion(client, model, messages, request_kwargs=None, provider="openai"):
    if provider == "google":
        # Google GenAI SDK logic
        contents = []
        for m in messages:
            role = "user" if m["role"] in ["user", "system"] else "model"
            contents.append(types.Content(role=role, parts=[types.Part.from_text(text=m["content"])]))
        
        try:
            thinking_config = types.ThinkingConfig(thinking_level="HIGH")
        except Exception:
            thinking_config = types.ThinkingConfig(include_thoughts=True)

        generate_content_config = types.GenerateContentConfig(
            thinking_config=thinking_config,
            tools=[], 
            max_output_tokens=request_kwargs.get("max_tokens") if request_kwargs else None
        )
        
        return client.models.generate_content(
            model=model,
            contents=contents,
            config=generate_content_config,
        )

    return client.chat.completions.create(model=model, messages=messages, **(request_kwargs or {}))

def generate_text_full(
    prompt,
    system_prompt="You are an expert novel writer.",
    model=DEFAULT_MODEL,
    task_profile=None,
    max_tokens=None,
):
    """带用量统计的文本生成接口"""
    provider_name, cfg = _get_backend_for_model(model)
    client = get_ark_client(provider=provider_name, api_key=cfg["api_key"], base_url=cfg.get("base_url"))
    resolved_model = _resolve_model(model, cfg)
    
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
    request_kwargs = _build_request_kwargs(task_profile=task_profile, max_tokens=max_tokens)
    
    response = _request_chat_completion(
        client, 
        resolved_model, 
        messages, 
        request_kwargs=request_kwargs, 
        provider=provider_name
    )
    
    if provider_name == "google":
        content = response.text or ""
        usage_metadata = getattr(response, "usage_metadata", None)
        usage_data = {
            "prompt_tokens": usage_metadata.prompt_token_count if usage_metadata else 0,
            "completion_tokens": usage_metadata.candidates_token_count if usage_metadata else 0,
            "total_tokens": usage_metadata.total_token_count if usage_metadata else 0,
        }
    else:
        choice = response.choices[0]
        content = choice.message.content or ""
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

def generate_text_safe(
    prompt,
    system_prompt="You are a master style extractor.",
    model=DEFAULT_MODEL,
    task_profile=None,
    max_tokens=None,
):
    """带有异常捕获的文本生成接口"""
    try:
        return generate_text(
            prompt,
            system_prompt,
            model,
            task_profile=task_profile,
            max_tokens=max_tokens,
        )
    except Exception as e:
        print(f"   ❌ [LLM 响应失败] {str(e)[:100]}")
        return None
