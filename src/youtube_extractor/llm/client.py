from __future__ import annotations

import json
import re

import httpx


class LLMError(Exception):
    def __init__(self, message: str, *, code: str = "LLM_ERROR") -> None:
        super().__init__(message)
        self.code = code


_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)


def _extract_json(content: str) -> dict:
    """Robustly pull a JSON object out of an LLM response.

    Tries (in order):
    1. Direct json.loads — works when the model produces clean JSON.
    2. Strip ```json ... ``` code fences (some models wrap output even when
       response_format=json_object is requested — Hermes/Claude/GPT can all do this).
    3. Slice from the first { to the last } and try once more — handles cases where
       the model adds a "Here's the JSON:" preamble.
    """
    s = content.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    m = _FENCE_RE.search(s)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Last resort: grab the outermost {...} or [...]
    first_obj = s.find("{")
    last_obj = s.rfind("}")
    if first_obj >= 0 and last_obj > first_obj:
        try:
            return json.loads(s[first_obj : last_obj + 1])
        except json.JSONDecodeError:
            pass

    raise json.JSONDecodeError("no parseable JSON found in content", s, 0)


def missing_required(obj: dict, schema: dict | None) -> list[str]:
    """Top-level `required` keys of `schema` absent from `obj`.

    A cheap conformance probe, not a validator — the caller's pydantic model does
    the real checking. Its job is to tell "the endpoint enforced the schema" apart
    from "the endpoint accepted response_format and ignored it", which otherwise
    look identical: both return HTTP 200 with parseable JSON.
    """
    if not schema or not isinstance(obj, dict):
        return []
    required = schema.get("required")
    if not isinstance(required, list):
        return []
    return [k for k in required if isinstance(k, str) and k not in obj]


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
        schema: dict | None = None,
        max_retries: int = 1,
    ) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        base_body: dict = {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
        }
        if self.model:
            base_body["model"] = self.model

        # Response-format modes to try, in order. When a JSON schema is supplied we
        # ask the server to *enforce* it (vLLM/OpenAI structured outputs) so the shape
        # is guaranteed regardless of which model is behind the endpoint. Backends that
        # don't understand json_schema (some Ollama/older servers) reject it with
        # 400/422 — fall back to plain json_object so the client stays multi-backend.
        if schema is not None:
            modes: list[dict] = [
                {"type": "json_schema", "json_schema": {"name": response_schema_name, "schema": schema, "strict": True}},
                {"type": "json_object"},
            ]
        else:
            modes = [{"type": "json_object"}]

        last_err: Exception | None = None
        schema_ignored = False
        for mode in modes:
            body = {**base_body, "response_format": mode}
            for _attempt in range(max_retries + 1):
                try:
                    async with httpx.AsyncClient(timeout=self.timeout_s) as cli:
                        r = await cli.post(
                            f"{self.base_url}/v1/chat/completions", json=body, headers=headers
                        )
                except httpx.HTTPError as e:
                    raise LLMError(
                        f"transport error to {self.base_url}: {e}", code="LLM_UNREACHABLE"
                    ) from e

                if r.status_code != 200:
                    if mode.get("type") == "json_schema" and r.status_code in (400, 422):
                        # Backend doesn't support json_schema — stop retrying this mode
                        # and fall through to the json_object fallback.
                        last_err = LLMError(f"json_schema unsupported ({r.status_code}): {r.text[:200]}")
                        break
                    # 4xx is a deterministic client error (e.g. prompt over the context window) —
                    # a replay fails identically. 5xx is a transient server fault worth retrying.
                    code = "LLM_REQUEST_REJECTED" if 400 <= r.status_code < 500 else "LLM_UPSTREAM_ERROR"
                    raise LLMError(f"upstream {r.status_code}: {r.text[:200]}", code=code)

                try:
                    payload = r.json()
                    content = payload["choices"][0]["message"]["content"]
                    obj = _extract_json(content)
                except (KeyError, IndexError, ValueError, json.JSONDecodeError) as e:
                    last_err = e
                    continue

                # The endpoint answered 200, so it "accepted" response_format. That
                # is not the same as honouring it: the Hermes gateway accepts
                # json_schema, returns 200, and replies with whatever the model felt
                # like — prose, or a different object shape. The failure then surfaced
                # stages later as a pydantic error about missing fields, pointing at
                # the model instead of at the endpoint. Check conformance here, while
                # we still know which mode produced it.
                gaps = missing_required(obj, schema)
                if not gaps:
                    return obj
                # Sticky: the json_object fallback failing afterwards must not erase
                # the evidence that json_schema mode was accepted and not honoured.
                if mode.get("type") == "json_schema":
                    schema_ignored = True
                last_err = LLMError(
                    f"response missing required key(s) {gaps}; got {sorted(obj)[:8]}"
                )
                continue

        if schema_ignored:
            # Worth naming precisely: no amount of prompt work fixes an endpoint that
            # drops response_format, and the fix is to point at one that enforces it
            # (vLLM guided decoding) rather than to keep retrying here.
            raise LLMError(
                f"{self.base_url} accepted response_format=json_schema and returned "
                f"non-conforming output for {response_schema_name} — the endpoint is "
                f"ignoring structured output. Last error: {last_err}",
                code="LLM_SCHEMA_IGNORED",
            )
        raise LLMError(
            f"could not get valid JSON ({response_schema_name}): {last_err}",
            code="LLM_BAD_JSON",
        )
