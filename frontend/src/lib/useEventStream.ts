"use client";

import { useEffect, useRef, useState } from "react";

import { eventStreamUrl } from "@/lib/api";
import { lastSeq, mergeEvents, terminalStatus } from "@/lib/events";
import type { AgentEvent } from "@/lib/types";

const MAX_BACKOFF_MS = 8000;
const NOT_FOUND = 4404; // server close code: no such analysis, so retrying cannot help

/** Live agent events for an analysis. Reconnects with the last seen seq as cursor, so the
 *  timeline converges on the server's committed history without gaps or duplicates. */
export function useEventStream(analysisId: string) {
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const eventsRef = useRef<AgentEvent[]>([]);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;
    let stopped = false;

    const connect = () => {
      socket = new WebSocket(eventStreamUrl(analysisId, lastSeq(eventsRef.current)));
      socket.onopen = () => {
        attempt = 0;
        setConnected(true);
      };
      socket.onmessage = (message) => {
        eventsRef.current = mergeEvents(eventsRef.current, [JSON.parse(message.data) as AgentEvent]);
        setEvents(eventsRef.current);
      };
      socket.onclose = (event) => {
        setConnected(false);
        if (stopped || event.code === NOT_FOUND || terminalStatus(eventsRef.current)) return;
        attempt += 1;
        retry = setTimeout(connect, Math.min(MAX_BACKOFF_MS, 500 * 2 ** attempt));
      };
    };
    connect();
    return () => {
      stopped = true;
      clearTimeout(retry);
      socket?.close();
    };
  }, [analysisId]);

  return { events, connected, finalStatus: terminalStatus(events) };
}
