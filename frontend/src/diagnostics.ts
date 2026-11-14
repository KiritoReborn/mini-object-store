export type RequestOutcome =
  | "HTTP response"
  | "Network failure"
  | "Cancelled"
  | "Invalid response"
  | "Response handling failed";
export interface RequestObservation {
  id: number;
  method: string;
  endpoint: string;
  started_at: string;
  duration_ms: number;
  status: number | null;
  outcome: RequestOutcome;
}
let sequence = 0;
let generation = 0;
let observations: RequestObservation[] = [];
const changed = () => {
  if (typeof window !== "undefined")
    window.dispatchEvent(new Event("artaud-request"));
};
export function getRequestLog(): RequestObservation[] {
  return observations.map((row) => ({ ...row }));
}
export function clearRequestLog(): void {
  generation++;
  observations = [];
  changed();
}
export function startObservation(method: string, path: string) {
  const observedGeneration = generation;
  const started = performance.now();
  const timestamp = new Date().toISOString();
  const route = path.split("?")[0];
  const endpoint =
    route === "/api/v1/overview"
      ? "Overview"
      : route === "/api/v1/activity"
        ? "Activity"
        : route === "/api/v1/objects"
          ? "Objects"
          : route.startsWith("/api/v1/objects/")
            ? route.endsWith("/metadata")
              ? "Object metadata"
              : "Object"
            : route.startsWith("/api/v1/demo/")
              ? "Container controls"
              : route.startsWith("/api/v1/workers")
                ? "Workers"
                : "API";
  let recorded = false;
  return (status: number | null, outcome: RequestOutcome) => {
    if (recorded || observedGeneration !== generation) return;
    recorded = true;
    observations = [
      ...observations.slice(-59),
      {
        id: ++sequence,
        method: ["GET", "POST", "PATCH", "DELETE"].includes(
          method.toUpperCase(),
        )
          ? method.toUpperCase()
          : "OTHER",
        endpoint,
        started_at: timestamp,
        duration_ms: Math.max(0, Math.round(performance.now() - started)),
        status,
        outcome,
      },
    ];
    changed();
  };
}
