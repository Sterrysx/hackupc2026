import { twinWebSocketUrl } from "@/lib/agentApi";
import { useTwin } from "@/store/twin";

/**
 * Subscribes to FastAPI `WebSocket` `/ws/notifications` (watchdog `PROACTIVE_ALERT` payloads).
 * Returns a cleanup that closes the socket; safe to call from `useEffect`.
 */
export function startProactiveWebSocket(): () => void {
  if (typeof WebSocket === "undefined") {
    return () => undefined;
  }
  const url = twinWebSocketUrl("/ws/notifications");
  const ws = new WebSocket(url);
  ws.onmessage = (ev) => {
    try {
      const data = JSON.parse(String(ev.data)) as Record<string, unknown>;
      useTwin.getState().ingestProactiveNotification(data);
    } catch {
      /* ignore */
    }
  };
  return () => {
    try {
      ws.close();
    } catch {
      /* noop */
    }
  };
}
