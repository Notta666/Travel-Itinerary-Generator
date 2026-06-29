"""
Multi-LLM backend abstraction
==============================
LLMClient class with pluggable backends.
Currently implemented: DeepSeek (default).
Placeholders: OpenAI, Qwen.

Usage:
    from utils.llm import LLMClient, call_deepseek

    # New API
    client = LLMClient(provider="deepseek")
    result = client.call(system_prompt, user_prompt)

    # Legacy backward-compatible shortcut
    result = call_deepseek(system_prompt, user_prompt)
"""
import json
import logging
import time
import urllib.request
import urllib.error

logger = logging.getLogger("travel_pipeline")


# ---------------------------------------------------------------------------
#  LLM Client — abstract base + implementations
# ---------------------------------------------------------------------------

class LLMClient:
    """Multi-provider LLM client.

    Parameters
    ----------
    provider : str
        One of 'deepseek', 'openai', 'qwen'.
    api_key : str, optional
        Override the default key for the provider.
    """

    PROVIDERS = {
        "deepseek": {
            "key_env": "DEEPSEEK_API_KEY",
            "default_model": "deepseek-chat",
        },
        "openai": {
            "key_env": "OPENAI_API_KEY",
            "default_model": "gpt-4o",
        },
        "qwen": {
            "key_env": "QWEN_API_KEY",
            "default_model": "qwen-max",
        },
    }

    def __init__(self, provider="deepseek", api_key=None):
        self.provider = provider
        if api_key:
            self.api_key = api_key
        else:
            # Lazy-import config to avoid circular imports
            from utils.config import DEEPSEEK_API_KEY, BASE_DIR
            env_key = self.PROVIDERS.get(provider, {}).get("key_env", "")
            self.api_key = getattr(__import__("utils.config", fromlist=[env_key]), env_key, "")
        if not self.api_key:
            raise RuntimeError(
                f"API key for provider '{provider}' not configured. "
                f"Set the {self.PROVIDERS.get(provider, {}).get('key_env', 'env var')} environment variable."
            )

    @property
    def model(self):
        return self.PROVIDERS.get(self.provider, {}).get("default_model", "deepseek-chat")

    def call(self, system_prompt, user_prompt, temperature=0.3, max_tokens=4000,
             max_retries=3, response_format=None):
        """Execute a generation call against the configured provider.

        Parameters
        ----------
        system_prompt : str
        user_prompt : str
        temperature : float
        max_tokens : int
        max_retries : int
        response_format : dict or None
            e.g. {"type": "json_object"} for DeepSeek

        Returns
        -------
        dict
            Parsed JSON response content.
        """
        if self.provider == "deepseek":
            return self._call_deepseek(system_prompt, user_prompt, temperature,
                                       max_tokens, max_retries, response_format)
        elif self.provider == "openai":
            # Placeholder — not yet implemented
            raise NotImplementedError("OpenAI backend not yet implemented")
        elif self.provider == "qwen":
            # Placeholder — not yet implemented
            raise NotImplementedError("Qwen backend not yet implemented")
        else:
            raise ValueError(f"Unknown provider: {self.provider}")

    # ---- DeepSeek implementation ----

    def _call_deepseek(self, system_prompt, user_prompt, temperature=0.3,
                       max_tokens=4000, max_retries=3, response_format=None):
        """Direct DeepSeek API call with retry logic."""
        req_body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            req_body["response_format"] = response_format
        elif "json" in system_prompt.lower() or "json" in user_prompt.lower():
            # Auto-enable JSON mode when prompts mention JSON
            req_body["response_format"] = {"type": "json_object"}

        body_bytes = json.dumps(req_body).encode("utf-8")
        last_error = None

        for attempt in range(max_retries):
            try:
                req = urllib.request.Request(
                    "https://api.deepseek.com/v1/chat/completions",
                    data=body_bytes,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=90) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                content = result["choices"][0]["message"]["content"]
                return json.loads(content)

            except (urllib.error.URLError, json.JSONDecodeError, KeyError) as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait = 2 ** attempt
                    logger.warning(
                        f"DeepSeek call failed (attempt {attempt+1}/{max_retries}): {e}, "
                        f"retrying in {wait}s"
                    )
                    time.sleep(wait)
                else:
                    logger.error(
                        f"DeepSeek call failed (max retries {max_retries}): {e}"
                    )
                    raise RuntimeError(f"DeepSeek API call failed: {e}") from e
            except Exception as e:
                raise RuntimeError(f"DeepSeek API call error: {e}") from e


# ---------------------------------------------------------------------------
#  Legacy backward-compatible shortcut
# ---------------------------------------------------------------------------

def call_deepseek(system_prompt, user_prompt, temperature=0.3,
                  max_tokens=4000, max_retries=3):
    """Legacy wrapper — equivalent to LLMClient(provider='deepseek').call(...)."""
    client = LLMClient(provider="deepseek")
    return client.call(system_prompt, user_prompt, temperature, max_tokens, max_retries)


def call_llm(system_prompt, user_prompt, provider="deepseek", **kwargs):
    """Generic entry point for multi-provider calls."""
    client = LLMClient(provider=provider)
    return client.call(system_prompt, user_prompt, **kwargs)
