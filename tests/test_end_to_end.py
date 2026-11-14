"""Joint live acceptance check using the production controller and four workers.

Standalone: python tests/test_end_to_end.py --controller-image IMAGE --worker-image IMAGE
Add --large for a streamed 50,000,000-byte round-trip. Every resource is disposable;
existing Compose containers and data are never used. No worker state is set by this
harness. Normal pytest runs skip the Docker check; opt in with
MINI_OBJECT_STORE_LIVE=1 and optional MINI_OBJECT_STORE_CONTROLLER_IMAGE,
MINI_OBJECT_STORE_WORKER_IMAGE and MINI_OBJECT_STORE_LARGE=1 environment variables.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path


LABEL = "mini-object-store.joint-check"
CONTROLLER_IMAGE = "mini-object-store-controller:integration"
WORKER_IMAGE = "mini-object-store-worker:integration"
WORKERS = tuple(f"worker{i}" for i in range(1, 5))
FILENAME = "\u0926\u0938\u094d\u0924\u093e\u0935\u0947\u091c\u093c-qa.bin"

# Read actual chunk files, including the locally claimed sidecar hash. The
# controller's public manifest supplies the expected size/hash independently.
DISK_PROBE = r'''
import hashlib, json, os, sys
from pathlib import Path
prefix = sys.argv[1] + '_'
result = {}
for path in Path('/data/chunks').glob(prefix + '*'):
    if not path.is_file() or path.name.endswith(('.sha256', '.tmp')):
        continue
    try:
        with path.open('rb') as source:
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
            size = os.fstat(source.fileno()).st_size
        sidecar = path.with_name(path.name + '.sha256')
        result[path.name] = {'size': size, 'sha256': digest,
                             'sidecar_sha256': sidecar.read_text().strip() if sidecar.exists() else None}
    except FileNotFoundError:
        pass  # Recovery may remove a surplus copy while this snapshot is read.
print(json.dumps(result))
'''

CORRUPT_CHUNK = r'''
import hashlib, os, re, sys
from pathlib import Path
cid = sys.argv[1]
assert re.fullmatch(r'[0-9a-f-]{36}_[0-9]+', cid), 'unsafe QA chunk id'
path = Path('/data/chunks') / cid
data = path.read_bytes()
assert data, 'expected a nonempty QA chunk'
data = bytes([data[0] ^ 1]) + data[1:]
with path.open('wb') as target:
    target.write(data)
    target.flush()
    os.fsync(target.fileno())
# Forge a self-consistent sidecar too: the controller must use its DB hash.
path.with_name(cid + '.sha256').write_text(hashlib.sha256(data).hexdigest())
print(hashlib.sha256(data).hexdigest())
'''


def evidence(phase: str, **fields) -> None:
    print(json.dumps({"phase": phase, **fields}, ensure_ascii=True), flush=True)


class LiveCheck:
    def __init__(self, controller_image: str, worker_image: str, timeout: float):
        self.controller_image, self.worker_image = controller_image, worker_image
        self.timeout = timeout
        self.prefix = "object-store-joint-" + uuid.uuid4().hex
        self.containers: list[str] = []
        self.volumes: list[str] = []
        self.networks: list[str] = []
        self.port: int | None = None

    def docker(self, *args: str, timeout: float = 60) -> str:
        result = subprocess.run(["docker", *args], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=timeout)
        if result.returncode:
            raise RuntimeError(f"docker {' '.join(args[:3])}: {result.stderr or result.stdout}")
        # Docker preserves the container's stdout/stderr separation for logs.
        return (result.stdout + result.stderr if args[0] == "logs" else result.stdout).strip()

    def name(self, service: str) -> str:
        if service not in ("controller", *WORKERS):
            raise ValueError(f"Unknown QA service: {service}")
        return self.prefix + "-" + service

    def owned(self, kind: str, name: str) -> dict | None:
        # Exact resource lists, names and labels must all agree before mutation.
        recorded = {"container": self.containers, "volume": self.volumes,
                    "network": self.networks}[kind]
        if name not in recorded or not name.startswith(self.prefix + "-"):
            raise RuntimeError(f"Refusing unrecorded {kind}: {name}")
        result = subprocess.run(["docker", kind, "inspect", name], capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=30)
        if result.returncode:
            if "no such" in result.stderr.lower() or "not found" in result.stderr.lower():
                return None
            raise RuntimeError(result.stderr or result.stdout)
        item = json.loads(result.stdout)[0]
        labels = item.get("Config", {}).get("Labels", {}) if kind == "container" else item.get("Labels", {})
        if (labels or {}).get(LABEL) != self.prefix:
            raise RuntimeError(f"Refusing unowned {kind}: {name}")
        return item

    def container(self, action: str, service: str, *args: str) -> str:
        name = self.name(service)
        if self.owned("container", name) is None:
            raise RuntimeError(f"Missing QA container {name}")
        return self.docker(action, name, *args)

    def start(self) -> None:
        # Inspect first: this check never pulls/builds an image or needs Internet.
        for image in (self.controller_image, self.worker_image):
            self.docker("image", "inspect", image)
        network = self.prefix + "-network"
        self.networks.append(network)
        self.docker("network", "create", "--label", f"{LABEL}={self.prefix}", network)
        for service in ("controller", *WORKERS):
            volume = self.name(service) + "-data"
            self.volumes.append(volume)
            self.docker("volume", "create", "--label", f"{LABEL}={self.prefix}", volume)
            name = self.name(service)
            self.containers.append(name)  # Also clean up an ambiguously failed run.
            args = ["run", "-d", "--pull", "never", "--name", name,
                    "--label", f"{LABEL}={self.prefix}", "--network", network,
                    "--network-alias", service, "--mount", f"type=volume,source={volume},target=/data"]
            if service == "controller":
                args += ["--publish", "127.0.0.1::8000", self.controller_image]
            else:
                args += ["--env", f"WORKER_ID={service}", "--env", "CONTROLLER_URL=http://controller:8000",
                         self.worker_image]
            self.docker(*args)
        self.refresh_port()
        evidence("created", prefix=self.prefix, controller_port=self.port)

    def refresh_port(self) -> None:
        # Docker may assign a different random published port after restart.
        port = self.docker("port", self.name("controller"), "8000/tcp")
        if not port.startswith("127.0.0.1:"):
            raise RuntimeError(f"QA controller is not loopback-only: {port}")
        self.port = int(port.rsplit(":", 1)[1])

    def request(self, path: str, *, method: str = "GET", body=None, expected: int = 200):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        try:
            payload = None if body is None else json.dumps(body).encode("utf-8")
            connection.request(method, path, body=payload,
                               headers={"Content-Type": "application/json"} if payload is not None else {})
            response = connection.getresponse()
            data = response.read()
            assert response.status == expected, (method, path, response.status, data[:1000])
            return json.loads(data) if data else None
        finally:
            connection.close()

    def wait(self, description: str, check):
        deadline, last = time.monotonic() + self.timeout, None
        while time.monotonic() < deadline:
            try:
                result = check()
                if result:
                    return result
            except (AssertionError, OSError, http.client.HTTPException) as exc:
                last = str(exc)
            time.sleep(min(1, max(0, deadline - time.monotonic())))
        raise AssertionError(f"Timed out after {self.timeout}s: {description}; last observation: {last}")

    def workers(self) -> dict:
        return {w["worker_id"]: w for w in self.request("/api/v1/workers")["workers"]}

    def admitted(self) -> dict:
        health = self.request("/health")
        assert health["recovery_available"] is True, health
        workers = self.workers()
        assert set(workers) == set(WORKERS), workers
        assert all(w["status"] == "ALIVE" and w["available"] for w in workers.values()), workers
        return {wid: w["status"] for wid, w in workers.items()}

    def upload(self, size: int) -> dict:
        boundary = "JointAcceptance" + uuid.uuid4().hex
        prefix = (f'--{boundary}\r\nContent-Disposition: form-data; name="metadata"\r\n\r\n'
                  '{"course":"CC","check":"joint-recovery"}\r\n'
                  f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{FILENAME}"\r\n'
                  'Content-Type: application/octet-stream\r\n\r\n').encode("utf-8")
        suffix = f"\r\n--{boundary}--\r\n".encode("ascii")
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=120)
        digest, remaining = hashlib.sha256(), size
        block = bytes(range(256)) * 256
        try:
            connection.putrequest("POST", "/api/v1/objects")
            connection.putheader("Content-Type", "multipart/form-data; boundary=" + boundary)
            connection.putheader("Content-Length", str(len(prefix) + size + len(suffix)))
            connection.endheaders()
            connection.send(prefix)
            while remaining:
                part = block[:min(remaining, len(block))]
                connection.send(part)
                digest.update(part)
                remaining -= len(part)
            connection.send(suffix)
            response = connection.getresponse()
            raw = response.read()
            assert response.status == 201, (response.status, raw[:1000])
            obj = json.loads(raw)
            assert obj["size"] == size and obj["sha256"] == digest.hexdigest(), obj
            assert obj["name"] == FILENAME, obj
            return obj
        finally:
            connection.close()

    def manifest(self, oid: str) -> dict:
        return self.request(f"/api/v1/objects/{oid}/metadata")

    def download(self, obj: dict) -> None:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=120)
        digest, length = hashlib.sha256(), 0
        try:
            connection.request("GET", "/api/v1/objects/" + obj["object_id"])
            response = connection.getresponse()
            assert response.status == 200, (response.status, response.read(1000))
            assert response.getheader("Content-Type") == "application/octet-stream"
            assert response.getheader("X-Object-SHA256") == obj["sha256"]
            while part := response.read(65_536):
                digest.update(part)
                length += len(part)
            assert length == obj["size"] and digest.hexdigest() == obj["sha256"], (length, digest.hexdigest())
        finally:
            connection.close()

    def disks(self, oid: str, services=WORKERS) -> dict:
        return {wid: json.loads(self.container("exec", wid, "python", "-c", DISK_PROBE, oid))
                for wid in services}

    def two_copies(self, oid: str, *, services=WORKERS) -> dict:
        manifest, workers = self.manifest(oid), self.workers()
        disks = self.disks(oid, services)
        locations = {}
        for chunk in manifest["chunks"]:
            cid = chunk["chunk_id"]
            healthy = {r["worker_id"] for r in chunk["replicas"] if r["state"] == "HEALTHY"
                       and workers[r["worker_id"]]["available"]}
            assert len(healthy) == 2 and healthy <= set(services), (cid, healthy)
            actual = {wid for wid, files in disks.items() if cid in files}
            assert actual == healthy, (cid, healthy, actual)
            for wid in actual:
                stored = disks[wid][cid]
                assert stored == {"size": chunk["size"], "sha256": chunk["sha256"],
                                  "sidecar_sha256": chunk["sha256"]}, (cid, wid, stored)
            locations[cid] = sorted(actual)
        return locations

    def volume_preserved(self, service: str) -> None:
        item = self.owned("container", self.name(service))
        mounts = [m for m in item["Mounts"] if m["Destination"] == "/data"]
        assert len(mounts) == 1 and mounts[0]["Name"] == self.name(service) + "-data", mounts

    def diagnostics(self) -> None:
        for name in self.containers:
            try:
                if self.owned("container", name) is not None:
                    evidence("failure_logs", container=name, tail=self.docker("logs", "--tail", "60", name))
            except Exception as exc:
                evidence("diagnostics_failed", container=name, error=str(exc))

    def cleanup(self) -> list[str]:
        errors = []
        for kind, names in (("container", reversed(self.containers)),
                            ("volume", reversed(self.volumes)), ("network", reversed(self.networks))):
            for name in names:
                try:
                    if self.owned(kind, name) is not None:
                        args = (kind, "rm", "--force", name) if kind == "container" else (kind, "rm", name)
                        self.docker(*args)
                except Exception as exc:
                    errors.append(f"{kind} {name}: {exc}")
        evidence("cleanup", prefix=self.prefix, errors=errors)
        return errors


def run_live_check(controller_image=CONTROLLER_IMAGE, worker_image=WORKER_IMAGE,
                   *, large=False, browser=False, timeout=240) -> None:
    check = LiveCheck(controller_image, worker_image, timeout)
    try:
        check.start()
        evidence("C1_admitted", workers=check.wait("four inventory-verified ALIVE workers", check.admitted))
        if browser:
            frontend = Path(__file__).resolve().parents[1] / "frontend"
            subprocess.run(["node", str(frontend / "e2e" / "live-dashboard.mjs"),
                            f"http://127.0.0.1:{check.port}", "workflow"], cwd=frontend,
                           check=True, timeout=120)
            evidence("real_browser_workflow", verified=True)
        obj = check.upload(5_000_001)
        oid = obj["object_id"]
        manifest = check.manifest(oid)
        assert [c["size"] for c in manifest["chunks"]] == [1_000_000] * 5 + [1]
        assert manifest["num_chunks"] == 6 and manifest["name"] == FILENAME
        assert any(item["object_id"] == oid for item in check.request("/api/v1/objects"))
        check.download(obj)
        locations = check.wait("two hash-valid physical replicas per chunk", lambda: check.two_copies(oid))
        assert {wid for copies in locations.values() for wid in copies} == set(WORKERS), locations
        patched = check.request(f"/api/v1/objects/{oid}/metadata", method="PATCH",
                                body={"metadata": {"reviewed": True}})
        assert patched["metadata"] == {"course": "CC", "check": "joint-recovery", "reviewed": True}
        assert all(patched[key] == manifest[key] for key in ("object_id", "name", "size", "sha256", "num_chunks"))
        evidence("C2_roundtrip", object_id=oid, size=obj["size"], sha256=obj["sha256"], locations=locations,
                 metadata=patched["metadata"], unicode_filename=True)

        affected = [cid for cid, copies in locations.items() if "worker2" in copies]
        assert affected, "worker2 must hold tested chunks before the failure"
        check.volume_preserved("worker2")
        check.container("stop", "worker2")
        check.download(obj)
        evidence("C4_stopped_fallback", worker="worker2", affected_chunks=affected, sha256=obj["sha256"])

        def repaired_without_worker2():
            assert check.workers()["worker2"]["status"] == "DEAD"
            return check.two_copies(oid, services=("worker1", "worker3", "worker4"))

        evidence("C4_dead_repaired", locations=check.wait("DEAD worker2 and factor two on surviving workers",
                                                         repaired_without_worker2))
        check.container("start", "worker2")
        check.volume_preserved("worker2")
        check.wait("rejoining worker verified ALIVE", check.admitted)
        evidence("C4_rejoined_trimmed", locations=check.wait("rejoin surplus trimmed to two physical copies",
                                                           lambda: check.two_copies(oid)))
        check.download(obj)

        chunk = check.manifest(oid)["chunks"][0]
        corrupt_worker = sorted(r["worker_id"] for r in chunk["replicas"] if r["state"] == "HEALTHY")[0]
        bad_hash = check.container("exec", corrupt_worker, "python", "-c", CORRUPT_CHUNK, chunk["chunk_id"])
        assert bad_hash != chunk["sha256"]
        check.download(obj)
        logs = check.docker("logs", "--tail", "500", check.name("controller"))
        assert any(chunk["chunk_id"] in line and ("REPLICA_CORRUPT" in line or "CHUNK_CORRUPTED" in line)
                   for line in logs.splitlines()), "controller did not record corruption detection"
        repaired = check.wait("corrupt bytes restored to DB hash", lambda: check.two_copies(oid))
        assert corrupt_worker in repaired[chunk["chunk_id"]]
        evidence("C4_corruption_repaired", worker=corrupt_worker, chunk_id=chunk["chunk_id"],
                 forged_sidecar=True, corrupted_sha256=bad_hash, restored_sha256=chunk["sha256"])

        check.container("restart", "controller")
        check.refresh_port()
        check.volume_preserved("controller")
        check.wait("controller restart and verified worker readmission", check.admitted)
        assert check.manifest(oid)["sha256"] == obj["sha256"]
        check.download(obj)
        check.wait("persistent two-copy data after restart", lambda: check.two_copies(oid))
        evidence("C5_restart_persistence", object_id=oid, sha256=obj["sha256"])
        objects = [obj]
        if large:
            big = check.upload(50_000_000)
            check.download(big)
            check.wait("large object has two physical copies", lambda: check.two_copies(big["object_id"]))
            objects.append(big)
            evidence("C5_large_stream", size=big["size"], sha256=big["sha256"], num_chunks=big["num_chunks"])
        for item in objects:
            deleted_id = item["object_id"]
            check.request("/api/v1/objects/" + deleted_id, method="DELETE", expected=204)
            check.request(f"/api/v1/objects/{deleted_id}/metadata", expected=404)
            check.request("/api/v1/objects/" + deleted_id, expected=404)
            check.wait("deleted bytes removed from all four QA disks",
                       lambda: all(not files for files in check.disks(deleted_id).values()))
        assert check.request("/api/v1/objects") == []
        evidence("six_public_APIs_and_delete_cleanup", deleted_objects=len(objects))
    except BaseException:
        check.diagnostics()
        raise
    finally:
        failed = sys.exc_info()[0] is not None
        errors = check.cleanup()
        if errors and not failed:
            raise RuntimeError("QA cleanup incomplete: " + "; ".join(errors))
    evidence("passed", large=large, browser=browser)


def test_joint_live_recovery():
    import pytest

    if os.getenv("MINI_OBJECT_STORE_LIVE") != "1":
        pytest.skip("set MINI_OBJECT_STORE_LIVE=1 to run the disposable five-container acceptance check")
    run_live_check(os.getenv("MINI_OBJECT_STORE_CONTROLLER_IMAGE", CONTROLLER_IMAGE),
                   os.getenv("MINI_OBJECT_STORE_WORKER_IMAGE", WORKER_IMAGE),
                   large=os.getenv("MINI_OBJECT_STORE_LARGE") == "1",
                   browser=os.getenv("MINI_OBJECT_STORE_BROWSER") == "1")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--controller-image", default=CONTROLLER_IMAGE, help="already-built controller image")
    parser.add_argument("--worker-image", default=WORKER_IMAGE, help="already-built worker image")
    parser.add_argument("--large", action="store_true", help="also stream a 50,000,000-byte upload/download")
    parser.add_argument("--browser", action="store_true", help="also run the existing real-browser workflow (requires frontend dependencies/Chromium)")
    parser.add_argument("--timeout", type=float, default=240, help="maximum seconds per convergence poll (default: 240)")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    run_live_check(args.controller_image, args.worker_image, large=args.large, browser=args.browser, timeout=args.timeout)


if __name__ == "__main__":
    main()
