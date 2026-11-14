import asyncio
import hashlib
import os
from io import BytesIO
from threading import Event
from types import SimpleNamespace

import httpx
import anyio
import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile
from starlette.requests import Request


def test_cancelled_lock_waiter_does_not_allow_overlapping_mutations():
    from controller.objects import object_lock

    async def scenario():
        entered = []

        async def waiter(label):
            async with object_lock("shared-object"):
                entered.append(label)

        async with object_lock("shared-object"):
            second = asyncio.create_task(waiter("cancelled"))
            await asyncio.sleep(0)
            second.cancel()
            try:
                await second
            except asyncio.CancelledError:
                pass
            third = asyncio.create_task(waiter("next"))
            await asyncio.sleep(0)
            assert not third.done()
        await third
        assert entered == ["next"]

    asyncio.run(scenario())


def test_interrupted_file_response_removes_verified_temporary_file(tmp_path):
    from controller.objects import VerifiedFileResponse
    path = tmp_path / "verified.tmp"
    path.write_bytes(b"verified bytes")

    async def scenario():
        async def receive():
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.body":
                raise ConnectionError("client disconnected")

        try:
            await VerifiedFileResponse(path)({"type": "http", "method": "GET", "headers": [],
                "asgi": {"spec_version": "2.4"}}, receive, send)
        except ConnectionError:
            pass

    asyncio.run(scenario())
    assert not path.exists()


def test_recovery_hooks_support_awaitable_start_and_stop(tmp_path, monkeypatch):
    from controller import config, main
    events = []

    async def start():
        events.append("start")

    async def stop():
        events.append("stop")

    monkeypatch.setattr(config, "DATABASE_PATH", str(tmp_path / "metadata.db"))
    monkeypatch.setattr(config, "DOWNLOAD_TEMP_DIR", tmp_path / "downloads")
    monkeypatch.setattr(main, "_optional_module", lambda name: SimpleNamespace(start_reconciler=start, stop_reconciler=stop) if name.endswith("recovery") else None)
    with TestClient(main.create_app(worker_transport=httpx.MockTransport(lambda req: httpx.Response(204)))) as client:
        assert events == ["start"]
        assert client.get("/health").json()["recovery_available"] is True
    assert events == ["start", "stop"]


@pytest.mark.parametrize("cancellation", ["task", "repeated-task", "anyio-scope"])
def test_cancelled_temp_acquisition_does_not_leave_a_late_file_or_descriptor(tmp_path, monkeypatch, cancellation):
    from controller import config, objects
    monkeypatch.setattr(config, "DOWNLOAD_TEMP_DIR", tmp_path)
    entered, release, finished = Event(), Event(), Event()
    acquired = []
    real_mkstemp = objects.tempfile.mkstemp

    def paused_creation(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        result = real_mkstemp(*args, **kwargs)
        acquired.append(result)
        finished.set()
        return result

    monkeypatch.setattr(objects.tempfile, "mkstemp", paused_creation)

    async def scenario():
        obj = {"chunks": [], "size": 0, "num_chunks": 0, "sha256": hashlib.sha256(b"").hexdigest()}
        scopes = []

        async def prepare():
            with anyio.CancelScope() as scope:
                scopes.append(scope)
                return await objects._prepare_download(None, obj)

        task = asyncio.create_task(prepare())
        assert await asyncio.to_thread(entered.wait, 3)
        if cancellation == "anyio-scope":
            scopes[0].cancel()
        else:
            task.cancel("original cancellation")
        await asyncio.sleep(0)
        if cancellation == "repeated-task":
            task.cancel("later cancellation")
        await asyncio.sleep(0)
        release.set()
        try:
            await task
        except asyncio.CancelledError as exc:
            assert str(exc) == "original cancellation"
        assert await asyncio.to_thread(finished.wait, 3)

    asyncio.run(scenario())
    try:
        assert list(tmp_path.iterdir()) == []
        try:
            os.fstat(acquired[0][0])
        except OSError:
            pass
        else:
            raise AssertionError("temporary-file descriptor was leaked")
    finally:
        for fd, filename in acquired:
            try:
                os.close(fd)
            except OSError:
                pass
            objects.remove_download(objects.Path(filename))


def test_cancellation_during_initial_insert_cannot_leave_an_active_upload(tmp_path, monkeypatch):
    from controller import config, database as db, main, objects
    monkeypatch.setattr(config, "DATABASE_PATH", str(tmp_path / "metadata.db"))
    monkeypatch.setattr(config, "DOWNLOAD_TEMP_DIR", tmp_path / "downloads")
    entered, release, finished = Event(), Event(), Event()
    real_create = db.create_object

    def paused_insert(*args):
        entered.set()
        assert release.wait(3)
        real_create(*args)
        finished.set()

    monkeypatch.setattr(db, "create_object", paused_insert)
    with TestClient(main.create_app(worker_transport=httpx.MockTransport(lambda r: httpx.Response(204)))) as client:
        async def scenario():
            request = Request({"type": "http", "app": client.app})
            file = UploadFile(BytesIO(b"payload"), filename="sample.bin")
            task = asyncio.create_task(objects.upload_object(request, file, None))
            assert await asyncio.to_thread(entered.wait, 3)
            task.cancel()
            await asyncio.sleep(0)
            release.set()
            try:
                await task
            except asyncio.CancelledError:
                pass
            assert await asyncio.to_thread(finished.wait, 3)
            with db.connection() as conn:
                assert conn.execute("SELECT count(*) FROM objects").fetchone()[0] == 0

        client.portal.call(scenario)
