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
  let ws: WebSocket | null = null;
  let reconnectTimer: number | null = null;
  let heartbeatTimer: number | null = null;
  let retry = 0;
  let closedByUser = false;

  const stopHeartbeat = () => {
    if (heartbeatTimer !== null) {
      window.clearInterval(heartbeatTimer);
      heartbeatTimer = null;
    }
  };

  const startHeartbeat = () => {
    stopHeartbeat();
    heartbeatTimer = window.setInterval(() => {
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      try {
        // Keep idle links alive through proxies/NAT; backend ignores payload content.
        ws.send("ping");
      } catch {
        /* ignore */
      }
    }, 25000);
  };

  const scheduleReconnect = () => {
    if (closedByUser || reconnectTimer !== null) return;
    const backoff = Math.min(10000, 500 * 2 ** retry);
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null;
      retry += 1;
      connect();
    }, backoff);
  };

  const connect = () => {
    ws = new WebSocket(url);
    ws.onopen = () => {
      retry = 0;
      startHeartbeat();
    };
    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(String(ev.data)) as Record<string, unknown>;
        useTwin.getState().ingestProactiveNotification(data);
      } catch {
        /* ignore */
      }
    };
    ws.onclose = () => {
      stopHeartbeat();
      scheduleReconnect();
    };
    ws.onerror = () => {
      // Ensure we eventually reconnect on transport errors.
      try {
        ws?.close();
      } catch {
        /* ignore */
      }
    };
  };

  connect();

  return () => {
    closedByUser = true;
    stopHeartbeat();
    if (reconnectTimer !== null) {
      window.clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    try {
      ws?.close();
    } catch {
      /* noop */
    }
  };
}
