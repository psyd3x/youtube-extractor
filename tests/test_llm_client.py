import httpx
import pytest
import respx

from youtube_extractor.llm.client import LLMClient, LLMError


@respx.mock
async def test_chat_json_happy():
    respx.post("http://x/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": '{"answer": 42}'}}]},
        )
    )
    client = LLMClient(base_url="http://x", api_key=None, timeout_s=5)
    result = await client.chat_json(system="be helpful", user="prompt", response_schema_name="answer")
    assert result == {"answer": 42}


@respx.mock
async def test_chat_json_retries_on_bad_json():
    route = respx.post("http://x/v1/chat/completions").mock(
        side_effect=[
            httpx.Response(200, json={"choices": [{"message": {"content": "not-json"}}]}),
            httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]}),
        ]
    )
    client = LLMClient(base_url="http://x", api_key=None, timeout_s=5)
    result = await client.chat_json(system="s", user="u", response_schema_name="x")
    assert result == {"ok": True}
    assert route.call_count == 2


@respx.mock
async def test_chat_json_fails_after_retries():
    respx.post("http://x/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "still-not-json"}}]})
    )
    client = LLMClient(base_url="http://x", api_key=None, timeout_s=5)
    with pytest.raises(LLMError):
        await client.chat_json(system="s", user="u", response_schema_name="x")


@respx.mock
async def test_http_error():
    respx.post("http://x/v1/chat/completions").mock(return_value=httpx.Response(503))
    client = LLMClient(base_url="http://x", api_key=None, timeout_s=5)
    with pytest.raises(LLMError):
        await client.chat_json(system="s", user="u", response_schema_name="x")


@respx.mock
async def test_chat_json_strips_code_fences():
    """Hermes (and Claude/GPT sometimes) wrap JSON in ```json ... ``` even with json_object mode.
    The client must strip the fences before parsing, or every distillation call fails."""
    fenced = '```json\n{"greeting": "Hello"}\n```'
    respx.post("http://x/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": fenced}}]})
    )
    client = LLMClient(base_url="http://x", api_key=None, timeout_s=5)
    result = await client.chat_json(system="s", user="u", response_schema_name="x")
    assert result == {"greeting": "Hello"}


@respx.mock
async def test_chat_json_schema_enforced_when_supported():
    """When a schema is supplied, the first attempt uses json_schema response_format."""
    captured: dict = {}

    def _capture(request):
        import json as _json
        captured.update(_json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]})

    respx.post("http://x/v1/chat/completions").mock(side_effect=_capture)
    client = LLMClient(base_url="http://x", api_key=None, timeout_s=5)
    result = await client.chat_json(system="s", user="u", response_schema_name="Foo", schema={"type": "object"})
    assert result == {"ok": True}
    assert captured["response_format"]["type"] == "json_schema"
    assert captured["response_format"]["json_schema"]["name"] == "Foo"


@respx.mock
async def test_chat_json_falls_back_when_schema_unsupported():
    """If the backend 400s on json_schema, retry with plain json_object."""
    route = respx.post("http://x/v1/chat/completions").mock(
        side_effect=[
            httpx.Response(400, text="response_format json_schema not supported"),
            httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]}),
        ]
    )
    client = LLMClient(base_url="http://x", api_key=None, timeout_s=5)
    result = await client.chat_json(
        system="s", user="u", response_schema_name="x", schema={"type": "object"}
    )
    assert result == {"ok": True}
    assert route.call_count == 2


@respx.mock
async def test_chat_json_strips_preamble():
    """Some models add a 'Here is the JSON:' preamble. We slice from first { to last }."""
    preamble = 'Sure, here is the JSON you asked for:\n{"key": "value", "n": 3}\nLet me know if you need more.'
    respx.post("http://x/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": preamble}}]})
    )
    client = LLMClient(base_url="http://x", api_key=None, timeout_s=5)
    result = await client.chat_json(system="s", user="u", response_schema_name="x")
    assert result == {"key": "value", "n": 3}
