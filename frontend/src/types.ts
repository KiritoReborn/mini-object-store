export interface StoredObject {
  object_id: string;
  name: string;
  size: number;
  content_type: string;
  created_at: string;
  updated_at: string;
  sha256: string;
  num_chunks: number;
  metadata: Record<string, unknown>;
  status: "READY";
}
export interface Replica {
  worker_id: string;
  state: "HEALTHY" | "CORRUPT" | "MISSING" | "PENDING_DELETE";
  worker_status: "ALIVE" | "JOINING" | "DEAD";
  last_verified_at: string | null;
}
export interface Chunk {
  chunk_id: string;
  index: number;
  size: number;
  sha256: string;
  workers: string[];
  replicas: Replica[];
}
export interface ObjectDetails extends StoredObject {
  chunks: Chunk[];
}
export interface Worker {
  worker_id: string;
  status: "ALIVE" | "JOINING" | "DEAD";
  last_heartbeat: string | null;
  heartbeat_age_seconds: number | null;
  available: boolean;
  chunk_count: number;
  stored_bytes: number;
}
export interface Overview {
  object_count: number;
  logical_bytes: number;
  chunk_count: number;
  healthy_replica_count: number;
  under_replicated_chunks: number;
  corrupt_replicas: number;
  worker_count: number;
  available_workers: number;
  replication_factor: number;
  chunk_size: number;
  recovery_available: boolean;
  workers: Worker[];
}
export type ToastMessage = {
  id: number;
  text: string;
  kind: "success" | "error" | "info";
};
export type Notify = (text: string, kind?: ToastMessage["kind"]) => void;

export interface ActivityEvent {
  id: number;
  timestamp: string;
  kind: string;
  object_id: string | null;
  chunk_id: string | null;
  worker_id: string | null;
  transfer_id: string | null;
  direction: "to_worker" | "from_worker" | null;
  size: number | null;
  state: string | null;
  previous_state: string | null;
  name: string | null;
  detail: string | null;
}
export interface ActivityBatch {
  stream_id: string;
  oldest_id: number;
  latest_id: number;
  next_cursor: number;
  truncated: boolean;
  events: ActivityEvent[];
}
