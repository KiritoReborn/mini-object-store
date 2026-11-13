"""Controlled A-only integration check with disposable Docker resources.

This harness verifies inventories and supplies worker eligibility in lieu of B's
absent reconciler. It NEVER installs a production promotion shortcut. Run with
--controller-image and --worker-image after building the existing Dockerfiles.
"""
import argparse
import json
import subprocess
import uuid


PROBE = r'''
import hashlib, http.client, json, os, sys, tempfile, time, urllib.request
from pathlib import Path
from controller import database as db

def request(path, method='GET', body=None):
    payload = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request('http://127.0.0.1:8000'+path, data=payload, method=method,
                                 headers={'Content-Type':'application/json'} if payload else {})
    with urllib.request.urlopen(req, timeout=30) as response:
        data=response.read()
        return json.loads(data) if data else None

for _ in range(100):
    try:
        request('/health')
        break
    except OSError: time.sleep(.2)
else: raise RuntimeError('controller not ready')

def qualify_workers():
    # TEST ONLY: B must deliver this lifecycle in production. Verify against DB.
    for worker in db.get_workers():
        origin=worker['base_url']
        for _ in range(100):
            try:
                inventory=json.load(urllib.request.urlopen(origin+'/internal/workers/'+worker['worker_id']+'/chunks',timeout=5))
                break
            except OSError: time.sleep(.2)
        else: raise RuntimeError('worker inventory did not become available')
        for item in inventory['chunks']:
            oid=item['chunk_id'].rsplit('_',1)[0]
            obj=db.get_object_manifest(oid)
            expected=next((c for c in obj['chunks'] if c['chunk_id']==item['chunk_id']),None) if obj else None
            assert expected is not None, 'unexpected orphan in controlled test'
            try:
                data=urllib.request.urlopen(origin+'/internal/chunks/'+item['chunk_id'],timeout=5).read()
            except urllib.error.HTTPError as exc:
                assert exc.code==409
                db.set_replica_state(item['chunk_id'],worker['worker_id'],'CORRUPT')
                continue
            assert len(data)==expected['size'] and hashlib.sha256(data).hexdigest()==expected['sha256']
        db.set_worker_state(worker['worker_id'],'ALIVE')

def upload(size):
    boundary='ControllerIntegrationBoundary'
    prefix=('--'+boundary+'\r\nContent-Disposition: form-data; name="metadata"\r\n\r\n'
            '{"course":"CC"}\r\n--'+boundary+'\r\nContent-Disposition: form-data; name="file"; filename="binary.bin"\r\n'
            'Content-Type: application/octet-stream\r\n\r\n').encode()
    suffix=('\r\n--'+boundary+'--\r\n').encode()
    chunk=bytes(range(256))*256
    digest=hashlib.sha256()
    connection=http.client.HTTPConnection('127.0.0.1',8000,timeout=60)
    connection.putrequest('POST','/api/v1/objects')
    connection.putheader('Content-Type','multipart/form-data; boundary='+boundary)
    connection.putheader('Content-Length',str(len(prefix)+size+len(suffix)))
    connection.endheaders()
    connection.send(prefix)
    remaining=size
    while remaining:
        data=chunk[:min(remaining,len(chunk))]
        digest.update(data)
        connection.send(data)
        remaining-=len(data)
    connection.send(suffix)
    response=connection.getresponse()
    body=response.read()
    assert response.status==201,(response.status,body)
    obj=json.loads(body)
    assert obj['sha256']==digest.hexdigest()
    connection.close()
    return obj

def download(oid):
    obj=request('/api/v1/objects/'+oid+'/metadata')
    digest=hashlib.sha256()
    size=0
    with urllib.request.urlopen('http://127.0.0.1:8000/api/v1/objects/'+oid,timeout=60) as response:
        while data:=response.read(65536):
            digest.update(data)
            size+=len(data)
    assert size==obj['size'] and digest.hexdigest()==obj['sha256']
    # Network receipt can precede the server's after-send cleanup by one turn.
    for _ in range(100):
        if not list(Path('/data/downloads').glob('download-*.tmp')): break
        time.sleep(.02)
    else: raise AssertionError('verified download temporary file was not cleaned')

stage=sys.argv[1]
if stage=='initial':
    for _ in range(100):
        if len(db.get_workers())==4: break
        time.sleep(.2)
    else: raise RuntimeError('four workers did not register')
    assert request('/health')['recovery_available'] is False
    assert all(w['status']=='JOINING' for w in db.get_workers())
    qualify_workers()
    obj=upload(5000001)
    assert [c['size'] for c in obj['chunks']]==[1000000]*5+[1]
    for c in obj['chunks']:
        assert len(set(c['workers']))==2
    assert len({w for c in obj['chunks'] for w in c['workers']})==4
    download(obj['object_id'])
    patched=request('/api/v1/objects/'+obj['object_id']+'/metadata','PATCH',{'metadata':{'reviewed':True}})
    assert patched['metadata']=={'course':'CC','reviewed':True}
    assert patched['sha256']==obj['sha256']
    print(json.dumps({'object_id':obj['object_id'],'sha256':obj['sha256'],'chunks':obj['num_chunks']}))
elif stage=='fallback':
    download(sys.argv[2])
    print('worker stopped: controller fallback download matches SHA-256')
elif stage=='corrupt':
    oid=sys.argv[2]
    for _ in range(100):
        if next(w for w in db.get_workers() if w['worker_id']=='worker2')['status']=='JOINING': break
        time.sleep(.2)
    else: raise RuntimeError('restarted worker did not re-register')
    qualify_workers()
    obj=db.get_object_manifest(oid)
    chunk=next(c for c in obj['chunks'] if any(r['worker_id']=='worker1' for r in c['replicas']))
    print(chunk['chunk_id'])
elif stage=='verify-corrupt':
    oid=sys.argv[2]
    download(oid)
    assert any(r['state']=='CORRUPT' for c in db.get_object_manifest(oid)['chunks'] for r in c['replicas'])
    print('corrupted stored bytes: clean fallback matches SHA-256; CORRUPT state recorded')
elif stage=='restart-large':
    assert all(w['status']=='JOINING' for w in db.get_workers())
    qualify_workers()
    download(sys.argv[2])
    def peak():
        return int(next(line for line in Path('/proc/1/status').read_text().splitlines() if line.startswith('VmHWM:')).split()[1])
    before=peak()
    obj=upload(50000000)
    download(obj['object_id'])
    print('controller restart retains metadata; 50,000,000-byte streaming round-trip matches SHA-256; controller peak-RSS increase KiB='+str(peak()-before))
    for item in request('/api/v1/objects'):
        request('/api/v1/objects/'+item['object_id'],'DELETE')
    assert request('/api/v1/objects')==[]
    print('all six public APIs verified against four real workers')
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--controller-image", required=True)
    parser.add_argument("--worker-image", required=True)
    args = parser.parse_args()
    prefix = "object-store-check-" + uuid.uuid4().hex[:10]
    containers, volumes = [], []
    network = False

    def docker(*args, input=None):
        result = subprocess.run(["docker", *args], input=input, text=True, capture_output=True)
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)
        return result.stdout.strip()

    def probe(stage, *args):
        return docker("exec", "-i", prefix + "-controller", "python", "-", stage, *args, input=PROBE)

    try:
        docker("network", "create", prefix)
        network = True
        for service in ["controller", "worker1", "worker2", "worker3", "worker4"]:
            volume = prefix + "-" + service + "-data"
            docker("volume", "create", volume)
            volumes.append(volume)
            name = prefix + "-" + service
            command = ["run", "-d", "--name", name, "--network", prefix, "--network-alias", service,
                       "--mount", f"type=volume,source={volume},target=/data"]
            if service != "controller":
                command += ["-e", "WORKER_ID=" + service, "-e", "CONTROLLER_URL=http://controller:8000"]
            command.append(args.controller_image if service == "controller" else args.worker_image)
            docker(*command)
            containers.append(name)
        first = json.loads(probe("initial"))
        oid = first["object_id"]
        print("5,000,001-byte round-trip:", json.dumps(first), flush=True)
        docker("stop", prefix + "-worker2")
        print(probe("fallback", oid), flush=True)
        docker("start", prefix + "-worker2")
        cid = probe("corrupt", oid)
        docker("exec", prefix + "-worker1", "python", "-c",
               "from pathlib import Path; p=Path('/data/chunks')/" + repr(cid) + "; p.write_bytes(p.read_bytes()+b'corruption')")
        print(probe("verify-corrupt", oid), flush=True)
        docker("restart", prefix + "-controller")
        print(probe("restart-large", oid), flush=True)
    finally:
        for name in reversed(containers):
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        for volume in volumes:
            subprocess.run(["docker", "volume", "rm", volume], capture_output=True)
        if network:
            subprocess.run(["docker", "network", "rm", prefix], capture_output=True)
        print("Disposed only this check's containers, volumes and network", flush=True)


if __name__ == "__main__":
    main()
