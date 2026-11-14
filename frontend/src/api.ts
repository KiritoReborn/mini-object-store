import type { StoredObject } from "./types";
import { apiUrl, connectionHeaders } from "./connection";

async function responseError(response: Response): Promise<Error> {
  const body = await response.json().catch(() => null);
  return new Error(
    typeof body?.message === "string"
      ? body.message
      : "The controller could not complete this request. Please try again.",
  );
}

export async function request<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(apiUrl(path), {
      ...options,
      headers: {
        Accept: "application/json",
        ...connectionHeaders(),
        ...options?.headers,
      },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError")
      throw error;
    throw new Error(
      "Could not reach the controller. Check the connection and try again.",
    );
  }
  if (!response.ok) throw await responseError(response);
  if (response.status === 204) return undefined as T;
  try {
    return await response.json();
  } catch {
    throw new Error(
      "The controller returned an unexpected response. Please refresh.",
    );
  }
}

export function uploadFile(
  file: File,
  metadata: Record<string, unknown>,
  signal: AbortSignal,
  progress: (percent: number) => void,
): Promise<StoredObject> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const abort = () => xhr.abort();
    xhr.open("POST", apiUrl("/api/v1/objects"));
    for (const [name, value] of Object.entries(connectionHeaders()))
      xhr.setRequestHeader(name, value);
    xhr.timeout = 180_000;
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable)
        progress(Math.min(100, Math.round((event.loaded / event.total) * 100)));
    };
    xhr.onload = () => {
      let data;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        reject(
          new Error(
            "Unexpected controller response. Refresh before retrying this file.",
          ),
        );
        return;
      }
      if (xhr.status === 201 && typeof data.object_id === "string")
        resolve(data);
      else
        reject(
          new Error(
            data.message ?? "The file could not be stored. Please try again.",
          ),
        );
    };
    xhr.onerror = xhr.ontimeout = () =>
      reject(
        new Error(
          "The connection was interrupted. Refresh before retrying; the file may already be stored.",
        ),
      );
    xhr.onabort = () =>
      reject(new DOMException("Upload cancelled", "AbortError"));
    xhr.onloadend = () => signal.removeEventListener("abort", abort);
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) {
      reject(new DOMException("Upload cancelled", "AbortError"));
      return;
    }
    const form = new FormData();
    form.append("file", file);
    form.append("metadata", JSON.stringify(metadata));
    xhr.send(form);
  });
}

type SaveTarget = { createWritable(): Promise<WritableStream<Uint8Array>> };
type SaveWindow = Window & {
  showSaveFilePicker?: (options: {
    suggestedName: string;
  }) => Promise<SaveTarget>;
};

export async function downloadFile(
  object: StoredObject,
): Promise<"saved" | "started" | "cancelled"> {
  let target: SaveTarget | undefined;
  const picker = (window as SaveWindow).showSaveFilePicker;
  if (picker) {
    try {
      target = await picker.call(window, { suggestedName: object.name });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError")
        return "cancelled";
      throw error;
    }
  }
  const response = await fetch(
    apiUrl(`/api/v1/objects/${encodeURIComponent(object.object_id)}`),
    { headers: connectionHeaders() },
  );
  if (!response.ok) throw await responseError(response);
  if (target && response.body) {
    await response.body.pipeTo(await target.createWritable());
    return "saved";
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob),
    link = document.createElement("a");
  link.href = url;
  link.download = object.name;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
  return "started";
}
