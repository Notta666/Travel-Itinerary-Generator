"""
DeepSeek API 调用封装
用于对抗性辩论路线规划 (Bull/Bear/Fusion)
"""
import urllib.request, json, os, time

def _load_api_key():
    """从环境变量或项目根目录的 .env 加载 DeepSeek API Key"""
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if key:
        return key
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("DEEPSEEK_API_KEY="):
                        val = line.split("=", 1)[1].strip().strip("\"'")
                        if val and val != "***":
                            return val
        except Exception:
            pass
    return ""


def call_deepseek(system_prompt, user_prompt, temperature=0.3, max_tokens=4000):
    """
    调用 DeepSeek API，返回解析后的 JSON dict。
    支持 json_object 输出格式。
    """
    api_key = _load_api_key()
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY 未配置")

    req_body = json.dumps({
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"}
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.deepseek.com/v1/chat/completions",
        data=req_body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        },
        method="POST"
    )

    with urllib.request.urlopen(req, timeout=90) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    content = result["choices"][0]["message"]["content"]
    return json.loads(content)
