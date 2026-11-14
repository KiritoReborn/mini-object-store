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
  accessKey = key;
  window.dispatchEvent(new Event("artaud-connection"));
}
