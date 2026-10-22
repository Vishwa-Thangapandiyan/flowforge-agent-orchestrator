import { useEffect, useState } from "react";
import type { RunEvent } from "./types";

/** Every event of a run, live while it runs and replayed from storage afterwards (D16). */
export function useRunEvents(runId: string | undefined): { events: RunEvent[]; ended: boolean } {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [ended, setEnded] = useState(false);

  useEffect(() => {
    setEvents([]);
    setEnded(false);
    if (!runId || typeof EventSource === "undefined") return;
    const source = new EventSource(`/runs/${encodeURIComponent(runId)}/events`);
    const buffer: RunEvent[] = [];
    let frame = 0;
    const flush = () => {
      frame = 0;
      setEvents((prev) => prev.concat(buffer.splice(0)));
    };
    source.onmessage = (msg) => {
      buffer.push(JSON.parse(msg.data) as RunEvent);
      if (!frame) frame = requestAnimationFrame(flush);
    };
    source.addEventListener("end", () => {
      if (frame) cancelAnimationFrame(frame);
      flush();
      setEnded(true);
      source.close();
    });
    source.onerror = () => {
      // the server closes the stream after "end"; a real drop just stops updating
      if (source.readyState === EventSource.CLOSED) setEnded(true);
    };
    return () => {
      if (frame) cancelAnimationFrame(frame);
      source.close();
    };
  }, [runId]);

  return { events, ended };
}
