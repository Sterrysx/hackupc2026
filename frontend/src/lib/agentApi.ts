/**
 * Calls the FastAPI `POST /agent/query` (see repo root `app.py`).
 *
 * - Si defines `VITE_TWIN_API_URL`, se usa esa URL absoluta (build / prod).
 * - Si no, en el navegador se usa el prefijo `/api` (proxy de Vite → :8000), así
 *   evitamos CORS y funciona con `host: true` y acceso por IP de la red local.
 */

export function getTwinApiBase(): string {
  const raw = import.meta.env.VITE_TWIN_API_URL as string | undefined;
  if (raw?.trim()) return raw.trim().replace(/\/$/, "");
  // Solo `vite dev` inyecta el proxy `/api` → :8000. En `dist/` sin proxy, usa URL directa.
  if (import.meta.env.DEV) return "";
  return "http://127.0.0.1:8000";
}

/** URL absoluta o ruta relativa bajo `/api/...` para `fetch`. */
export function twinApiUrl(path: string): string {
  const p = path.startsWith("/") ? path : `/${path}`;
  const base = getTwinApiBase();
  if (!base) return `/api${p}`;
  return `${base}${p}`;
}

export async function probeTwinApiHealth(): Promise<boolean> {
  try {
    const r = await fetch(twinApiUrl("/health"), { method: "GET" });
    return r.ok;
  } catch {
    return false;
  }
}

export interface AgentChatTurn {
  role: "user" | "assistant";
  content: string;
}

export interface AgentQueryBody {
  query: string;
  chat_history: AgentChatTurn[];
  run_identifier?: string;
}

export interface AgentQueryResponse {
  final_report: string;
}

export class AgentApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "AgentApiError";
    this.status = status;
  }
}

export async function queryAgent(body: AgentQueryBody): Promise<AgentQueryResponse> {
  const url = twinApiUrl("/agent/query");
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query: body.query,
      chat_history: body.chat_history,
      run_identifier: body.run_identifier ?? "",
    }),
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = (await res.json()) as { detail?: unknown };
      if (typeof j.detail === "string") detail = j.detail;
      else if (Array.isArray(j.detail)) detail = JSON.stringify(j.detail);
    } catch {
      /* ignore */
    }
    throw new AgentApiError(detail || `HTTP ${res.status}`, res.status);
  }

  return (await res.json()) as AgentQueryResponse;
}
