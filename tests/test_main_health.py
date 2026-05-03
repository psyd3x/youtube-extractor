import httpx
import respx
from fastapi.testclient import TestClient

from youtube_extractor.main import create_app


def test_health_basic_shape():
    app = create_app()
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert "hermes_reachable" in body


@respx.mock
def test_health_hermes_reachable_true():
    """When the configured LLM endpoint returns 200 on /v1/models, hermes_reachable is True."""
    from youtube_extractor.config import settings

    respx.get(f"{settings.llm_base_url.rstrip('/')}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    app = create_app()
    client = TestClient(app)
    r = client.get("/health")
    assert r.json()["hermes_reachable"] is True
