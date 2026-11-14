import httpx
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def demo(tmp_path, monkeypatch):
    from controller import config, main
    monkeypatch.setattr(config, "DATABASE_PATH", str(tmp_path / "metadata.db"))
    monkeypatch.setattr(config, "DOWNLOAD_TEMP_DIR", tmp_path / "downloads")
    monkeypatch.setattr(config, "API_KEY", "a" * 48, raising=False)
    monkeypatch.setattr(config, "ALLOWED_ORIGINS", ["https://artaud-test.vercel.app"], raising=False)
    monkeypatch.setattr(config, "DEMO_CONTROLS", True, raising=False)
    calls = []
    def docker(request):
        calls.append((request.method, request.url.path))
        if request.method == "GET":
            wid = request.url.path.split("/")[-2]
            return httpx.Response(200, json={"Id": "id-" + wid, "Name": "/" + wid,
                "Config": {"Labels": {"com.docker.compose.project": "mini-object-store", "com.docker.compose.service": wid}},
                "State": {"Status": "running", "Running": True}})
        return httpx.Response(204)
    with TestClient(main.create_app(docker_transport=httpx.MockTransport(docker))) as client:
        yield client, calls


def test_public_api_requires_key_and_allows_exact_configured_frontend(demo):
    client, _ = demo
    assert client.get("/api/v1/objects").status_code == 401
    headers = {"X-Artaud-Key": "a" * 48, "Origin": "https://artaud-test.vercel.app"}
    result = client.get("/api/v1/objects", headers=headers)
    assert result.status_code == 200
    assert result.headers["access-control-allow-origin"] == "https://artaud-test.vercel.app"
    assert client.post("/api/v1/objects", headers=headers, files={"file": ("empty", b"")}).status_code == 201
    assert client.post("/api/v1/objects", headers={**headers, "Origin": "https://evil.example"}, files={"file": ("x", b"")}).status_code == 403


def test_demo_actions_only_target_the_named_project_workers(demo):
    client, calls = demo
    headers = {"X-Artaud-Key": "a" * 48, "X-Artaud-Admin": "1"}
    assert client.get("/api/v1/demo/workers", headers=headers).json()["enabled"] is True
    for action in ["stop", "start", "restart"]:
        result = client.post(f"/api/v1/demo/workers/worker1/{action}", headers=headers)
        assert result.status_code == 200, result.text
    assert ("POST", "/containers/id-worker1/stop") in calls
    for target in ["controller", "rabbitmq", "worker5"]:
        assert client.post(f"/api/v1/demo/workers/{target}/stop", headers=headers).status_code == 400
    assert client.post("/api/v1/demo/workers/worker1/delete", headers=headers).status_code == 400
    assert client.post("/api/v1/demo/workers/worker1/stop", headers={"X-Artaud-Key": "a" * 48}).status_code == 403


def test_controls_are_disabled_by_default_and_internal_routes_are_not_public(demo, monkeypatch):
    from controller import config
    client, calls = demo
    monkeypatch.setattr(config, "DEMO_CONTROLS", False)
    assert client.get("/api/v1/demo/workers", headers={"X-Artaud-Key": "a" * 48}).json()["enabled"] is False
    assert calls == []
    assert client.post("/api/v1/demo/workers/worker1/stop", headers={"X-Artaud-Key": "a" * 48, "X-Artaud-Admin": "1"}).status_code == 503
    assert client.post("/internal/workers/register", headers={"Host": "demo.ngrok-free.dev"}, json={"worker_id": "worker1", "base_url": "http://worker1:8001"}).status_code == 404


def test_wrong_project_and_missing_credentials_cannot_mutate_docker(demo):
    client, calls = demo
    assert client.post("/api/v1/demo/workers/worker1/stop", headers={"X-Artaud-Admin": "1"}).status_code == 401
    assert calls == []
    writes = []
    def wrong_project(request):
        if request.method == "POST": writes.append(request.url.path)
        return httpx.Response(200, json={"Id": "other", "Name": "/worker1", "Config": {"Labels": {"com.docker.compose.project": "unrelated", "com.docker.compose.service": "worker1"}}, "State": {"Status": "running", "Running": True}})
    client.app.state.docker_transport = httpx.MockTransport(wrong_project)
    result = client.post("/api/v1/demo/workers/worker1/stop", headers={"X-Artaud-Key": "a" * 48, "X-Artaud-Admin": "1"})
    assert result.status_code == 409
    assert writes == []


def test_remote_preflight_supports_direct_upload_and_does_not_allow_unknown_sites(demo):
    client, _ = demo
    headers = {"Origin": "https://artaud-test.vercel.app", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "x-artaud-key,content-type,ngrok-skip-browser-warning"}
    assert client.options("/api/v1/objects", headers=headers).status_code == 200
    assert client.options("/api/v1/objects", headers={**headers, "Origin": "https://other.vercel.app"}).status_code == 400
