import {
  clearRequestLog,
  startObservation,
  type RequestOutcome,
} from "./diagnostics";

let accessKey = "";
const configured = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

export function validateBackend(value: string): string {
  if (!value.trim()) return "";
  const url = new URL(value.trim());
  const local = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
  if (
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    url.pathname !== "/" ||
    (url.protocol !== "https:" && !(local && url.protocol === "http:"))
  )
    throw new Error(
      "Use an HTTPS backend origin, or HTTP localhost. Do not include a path or credentials.",
    );
  return url.origin;
}

export function backendOrigin(): string {
  return typeof sessionStorage !== "undefined"
    ? (sessionStorage.getItem("artaud-backend") ?? configured)
    : configured;
}
export function apiUrl(path: string): string {
  return backendOrigin() + path;
}
export function connectionHeaders(): Record<string, string> {
  return {
    ...(accessKey ? { "X-Artaud-Key": accessKey } : {}),
    ...(backendOrigin().includes(".ngrok-free.")
      ? { "ngrok-skip-browser-warning": "1" }
      : {}),
  };
}
export function configureConnection(origin: string, key: string): void {
  const validated = validateBackend(origin);
  sessionStorage.setItem("artaud-backend", validated);
  clearRequestLog();
  accessKey = key;
  window.dispatchEvent(new Event("artaud-connection"));
}

export async function testBackendConnection(
  origin: string,
  key: string,
): Promise<string> {
  const validated = validateBackend(origin);
  const complete = startObservation("GET", "/api/v1/overview");
  let status: number | null = null;
  let outcome: RequestOutcome = "Network failure";
  try {
    const response = await fetch(validated + "/api/v1/overview", {
      headers: {
        Accept: "application/json",
        ...(key ? { "X-Artaud-Key": key } : {}),
        ...(validated.includes(".ngrok-free.")
          ? { "ngrok-skip-browser-warning": "1" }
          : {}),
      },
      signal: AbortSignal.timeout(10_000),
    });
    status = response.status;
    outcome = "HTTP response";
    if (status === 401)
      throw new Error(
        "Controller reached. Enter the correct owner access key.",
      );
    if (status === 403)
      throw new Error(
        "Controller reached. Allow this frontend’s exact origin on the PC.",
      );
    if (!response.ok)
      throw new Error(
        `Backend returned HTTP ${status}. Check the HTTPS controller address and PC setup.`,
      );
    const snapshot = await response.json().catch(() => null);
    if (
      !snapshot ||
      typeof snapshot.available_workers !== "number" ||
      typeof snapshot.recovery_available !== "boolean"
    ) {
      outcome = "Invalid response";
      throw new Error("The address did not return a controller overview.");
    }
    return `Controller reached. API access accepted. ${snapshot.available_workers} workers available. ${snapshot.recovery_available ? "Recovery module connected." : "Recovery module is not installed yet."}`;
  } catch (error) {
    if (status !== null && error instanceof Error) throw error;
    throw new Error(
      "Could not reach the API. Check the PC, ngrok HTTPS address and allowed frontend origin. The browser may have blocked the connection.",
    );
  } finally {
    complete(status, outcome);
  }
}
