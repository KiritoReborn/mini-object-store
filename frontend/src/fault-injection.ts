import { request } from "./api";
import type { Replica } from "./types";

export type FaultTarget = { chunkId: string; workerId: string };
type FaultState = "hidden" | "disabled" | "ready";

export function faultCapability(
  enabled: boolean | undefined,
  hasOwnerKey: boolean,
) {
  return enabled === true && hasOwnerKey;
}

export function replicaFaultState(
  enabled: boolean,
  replica: Replica["state"] | undefined,
  available: boolean,
  blocked: boolean,
): FaultState {
  if (!enabled || replica !== "HEALTHY") return "hidden";
  return available && !blocked ? "ready" : "disabled";
}

export function requestConfirmedReplicaFault(
  target: FaultTarget | null,
  state: FaultState,
) {
  if (!target || state !== "ready") return null;
  return request(
    `/api/v1/demo/workers/${encodeURIComponent(target.workerId)}/chunks/${encodeURIComponent(target.chunkId)}/corrupt`,
    { method: "POST", headers: { "X-Artaud-Admin": "1" } },
  );
}
