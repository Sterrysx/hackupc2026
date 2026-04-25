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

/** Response shape of `POST /agent/query` — matches `AgentResponse` in `app.py`. */
export interface ReasoningStep {
  kind: string;
  label: string;
  content: string;
}

export interface AgentResponse {
  grounded_text: string;
  evidence_citation: string;
  severity_indicator: string;
  recommended_actions: string[];
  priority_level: string;
  /** Ordered steps: tools, model text, retrieval bundle, validation — for UI transparency. */
  reasoning_trace: ReasoningStep[];
}

export interface AgentQueryBody {
  query: string;
  thread_id: string;
  run_identifier?: string;
}

export class AgentApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "AgentApiError";
    this.status = status;
  }
}

export async function queryAgent(body: AgentQueryBody): Promise<AgentResponse> {
  const url = twinApiUrl("/agent/query");
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query: body.query,
      thread_id: body.thread_id,
      run_identifier: body.run_identifier ?? "",
    }),
  });

  if (!res.ok) throw await readApiError(res);
  return (await res.json()) as AgentResponse;
}

/**
 * WebSocket base must mirror `twinApiUrl` (dev: same host + `/api` proxy; prod: `VITE_TWIN_API_URL` host).
 */
export function twinWebSocketUrl(path: string): string {
  const p = path.startsWith("/") ? path : `/${path}`;
  const base = getTwinApiBase();
  if (typeof window === "undefined") {
    return base ? `ws://${new URL(base).host}${p}` : p;
  }
  if (!base) {
    const { protocol, host } = window.location;
    const wsProto = protocol === "https:" ? "wss:" : "ws:";
    return `${wsProto}//${host}/api${p}`;
  }
  const u = new URL(base);
  const wsProto = u.protocol === "https:" ? "wss:" : "ws:";
  return `${wsProto}//${u.host}${p}`;
}

/**
 * Uploads a recorded audio Blob/File to `POST /stt/transcribe` (Faster Whisper)
 * and returns the transcribed text. Sent as multipart/form-data — *do not* set
 * the Content-Type header manually, the browser must compute the boundary.
 */
export async function transcribeAudio(file: File): Promise<string> {
  const url = twinApiUrl("/stt/transcribe");
  const fd = new FormData();
  fd.append("file", file, file.name);

  const res = await fetch(url, { method: "POST", body: fd });
  if (!res.ok) throw await readApiError(res);

  const j = (await res.json()) as { text?: string };
  return (j.text ?? "").trim();
}

async function readApiError(res: Response): Promise<AgentApiError> {
  let detail = res.statusText;
  try {
    const j = (await res.json()) as { detail?: unknown };
    if (typeof j.detail === "string") detail = j.detail;
    else if (Array.isArray(j.detail)) detail = JSON.stringify(j.detail);
  } catch {
    /* body wasn't JSON; keep statusText */
  }
  return new AgentApiError(detail || `HTTP ${res.status}`, res.status);
}
