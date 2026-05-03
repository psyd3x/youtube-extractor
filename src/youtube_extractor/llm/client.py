from __future__ import annotations

import json

import httpx


class LLMError(Exception):
    pass


class LLMClient:
    """Minimal OpenAI-compatible chat client. Works with Hermes, vLLM, Ollama, OpenAI."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        model: str | None = None,
        timeout_s: int = 300,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s

    async def chat_json(
        self,
        *,
        system: str,
        user: str,
        response_schema_name: str,
        max_retries: int = 1,
    ) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        body: dict = {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        }
        if self.model:
            body["model"] = self.model

        last_err: Exception | None = None
        for _attempt in range(max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout_s) as cli:
                    r = await cli.post(
                        f"{self.base_url}/v1/chat/completions", json=body, headers=headers
                    )
            except httpx.HTTPError as e:
                raise LLMError(f"transport error to {self.base_url}: {e}") from e

            if r.status_code != 200:
                raise LLMError(f"upstream {r.status_code}: {r.text[:200]}")

            try:
                payload = r.json()
                content = payload["choices"][0]["message"]["content"]
                return json.loads(content)
            except (KeyError, IndexError, ValueError, json.JSONDecodeError) as e:
                last_err = e
                continue

        raise LLMError(
            f"could not parse JSON after {max_retries + 1} attempts ({response_schema_name}): {last_err}"
        )
