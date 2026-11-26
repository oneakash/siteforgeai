"use client";

import { useEffect, useRef, useState } from "react";

export type RunEvent = {
  id: number;
  ts: string;
  type: "phase" | "task" | "log";
  stage: string | null;
  status: string | null;
  message: string;
  data: Record<string, unknown>;
};

/**
 * Live progress for one project over Server-Sent Events.
 * - Reconnects automatically; the browser re-sends Last-Event-ID so nothing is missed or repeated.
 * - `onActivity` fires (debounced) whenever something new arrives, so the page can refresh /status.
 */
export function useProjectEvents(
  apiUrl: string,
  projectId: string | null,
  onActivity?: () => void,
) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const activity = useRef(onActivity);
  useEffect(() => {
    activity.current = onActivity;
  });

  useEffect(() => {
    if (!projectId) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const es = new EventSource(`${apiUrl}/v1/projects/${projectId}/events`);
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false); // EventSource retries on its own

    const onMessage = (m: MessageEvent) => {
      const ev: RunEvent = JSON.parse(m.data);
      setEvents((prev) => (prev.some((e) => e.id === ev.id) ? prev : [...prev, ev]));
      clearTimeout(timer);
      timer = setTimeout(() => activity.current?.(), 250);
    };
    for (const t of ["phase", "task", "log"]) es.addEventListener(t, onMessage as EventListener);

    return () => {
      clearTimeout(timer);
      es.close();
      setConnected(false);
    };
  }, [apiUrl, projectId]);

  return { events, connected };
}
