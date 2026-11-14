CREATE TABLE IF NOT EXISTS objects (
    object_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    size INTEGER NOT NULL CHECK(size >= 0),
    content_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    num_chunks INTEGER NOT NULL CHECK(num_chunks >= 0),
    custom_metadata_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL CHECK(status IN ('UPLOADING','READY','DELETING','FAILED'))
);
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    object_id TEXT NOT NULL REFERENCES objects(object_id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL CHECK(chunk_index >= 0),
    size INTEGER NOT NULL CHECK(size >= 0),
    sha256 TEXT NOT NULL,
    UNIQUE(object_id, chunk_index)
);
CREATE TABLE IF NOT EXISTS workers (
    worker_id TEXT PRIMARY KEY,
    base_url TEXT NOT NULL,
    last_heartbeat TEXT,
    status TEXT NOT NULL CHECK(status IN ('JOINING','ALIVE','DEAD'))
);
CREATE TABLE IF NOT EXISTS worker_settings (
    worker_id TEXT PRIMARY KEY REFERENCES workers(worker_id) ON DELETE CASCADE,
    display_name TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    placement_enabled INTEGER NOT NULL DEFAULT 1 CHECK(placement_enabled IN (0,1))
);
CREATE TABLE IF NOT EXISTS replicas (
    chunk_id TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    worker_id TEXT NOT NULL REFERENCES workers(worker_id),
    state TEXT NOT NULL CHECK(state IN ('HEALTHY','CORRUPT','MISSING','PENDING_DELETE')),
    last_verified_at TEXT,
    PRIMARY KEY(chunk_id, worker_id)
);
CREATE INDEX IF NOT EXISTS idx_chunks_object ON chunks(object_id, chunk_index);
CREATE INDEX IF NOT EXISTS idx_replicas_worker ON replicas(worker_id);
CREATE INDEX IF NOT EXISTS idx_objects_status ON objects(status);
