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
