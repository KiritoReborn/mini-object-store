import { useCallback, useEffect, useRef, useState } from "react";
import { request } from "./api";
import { errorMessage } from "./format";
import { mergeActivity, type ActivityHistory } from "./system";
import type { ActivityBatch } from "./types";

export function useActivity(paused: boolean, pollInterval = 2000) {
  const [history, setHistory] = useState<ActivityHistory | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [capturedAt, setCapturedAt] = useState<string | null>(null);
  const cursor = useRef(0);
  const stream = useRef<string | null>(null);
  const [retry, setRetry] = useState(0);
  const refresh = useCallback(() => setRetry((value) => value + 1), []);
  useEffect(() => {
    if (paused) return;
    const controller = new AbortController();
    let timer: number | undefined;
    const poll = async () => {
      if (document.hidden) {
        timer = window.setTimeout(() => void poll(), pollInterval);
        return;
      }
      try {
        const signal = AbortSignal.any([
          controller.signal,
          AbortSignal.timeout(15_000),
        ]);
        const batch = await request<ActivityBatch>(
          `/api/v1/activity?after=${cursor.current}`,
          { signal },
        );
        if (
          !Array.isArray(batch.events) ||
          typeof batch.stream_id !== "string" ||
          !Number.isInteger(batch.next_cursor)
        )
          throw new Error("Activity returned an unexpected response.");
        if (controller.signal.aborted) return;
        // A new stream must include its retained events, including when its IDs exceed our old cursor.
        if (
          stream.current !== null &&
          stream.current !== batch.stream_id &&
          cursor.current !== 0
        ) {
          cursor.current = 0;
          const reset = await request<ActivityBatch>(
            "/api/v1/activity?after=0",
            { signal },
          );
          if (controller.signal.aborted) return;
          setHistory((previous) => mergeActivity(previous, reset));
          cursor.current = reset.next_cursor;
          stream.current = reset.stream_id;
        } else {
          setHistory((previous) => mergeActivity(previous, batch));
          cursor.current = batch.next_cursor;
          stream.current = batch.stream_id;
        }
        setCapturedAt(new Date().toISOString());
        setError(null);
      } catch (error) {
        if (!controller.signal.aborted) setError(errorMessage(error));
      } finally {
        if (!controller.signal.aborted)
          timer = window.setTimeout(() => void poll(), pollInterval);
      }
    };
    void poll();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [paused, retry, pollInterval]);
  return { history, error, capturedAt, refresh };
}
