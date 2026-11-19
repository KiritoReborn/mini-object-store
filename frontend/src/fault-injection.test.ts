import { afterEach, expect, it, vi } from "vitest";
import {
  faultCapability,
  replicaFaultState,
  requestConfirmedReplicaFault,
} from "./fault-injection";

afterEach(() => vi.unstubAllGlobals());

it("requires an explicitly enabled capability and an owner key", () => {
  expect(faultCapability(undefined, true)).toBe(false);
  expect(faultCapability(false, true)).toBe(false);
  expect(faultCapability(true, false)).toBe(false);
  expect(faultCapability(true, true)).toBe(true);
});

it("offers the action only for healthy replicas and disables unavailable or blocked targets", () => {
  expect(replicaFaultState(false, "HEALTHY", true, false)).toBe("hidden");
  expect(replicaFaultState(true, "CORRUPT", true, false)).toBe("hidden");
  expect(replicaFaultState(true, "HEALTHY", false, false)).toBe("disabled");
  expect(replicaFaultState(true, "HEALTHY", true, true)).toBe("disabled");
  expect(replicaFaultState(true, "HEALTHY", true, false)).toBe("ready");
});

it("sends only a confirmed, actionable target through the admin API", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response('{"action":"corrupted"}'));
  vi.stubGlobal("fetch", fetch);
  const target = { workerId: "worker1", chunkId: "object_0" };
  expect(requestConfirmedReplicaFault(null, "ready")).toBeNull();
  expect(requestConfirmedReplicaFault(target, "disabled")).toBeNull();
  expect(requestConfirmedReplicaFault(target, "hidden")).toBeNull();
  expect(fetch).not.toHaveBeenCalled();
  await requestConfirmedReplicaFault(target, "ready");
  expect(fetch).toHaveBeenCalledExactlyOnceWith(
    "/api/v1/demo/workers/worker1/chunks/object_0/corrupt",
    expect.objectContaining({
      method: "POST",
      headers: expect.objectContaining({ "X-Artaud-Admin": "1" }),
    }),
  );
});
