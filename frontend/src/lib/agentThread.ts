/** Stable LangGraph `thread_id` for multi-turn agent memory (mirrors `app.AgentRequest.thread_id`). */

const STORAGE_KEY = "aether-agent-thread";

export function getOrCreateAgentThreadId(): string {
  try {
    if (typeof window === "undefined" || !window.localStorage) {
      return `ssr-${Date.now()}`;
    }
    let v = localStorage.getItem(STORAGE_KEY);
    if (!v) {
      v = crypto.randomUUID();
      localStorage.setItem(STORAGE_KEY, v);
    }
    return v;
  } catch {
    return `session-${Date.now()}`;
  }
}
