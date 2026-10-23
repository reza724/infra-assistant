// Client for the Python API server (server.py).

export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type ApprovalAction = {
  tool_call_id: string;
  tool: string;
  action: string;
  app: string;
  reason: string;
  impact: string;
  details: Record<string, string | number>;
};

export type StreamEvent =
  | { type: "tool_start"; id: string; name: string; label: string; risk: "LOW" | "HIGH" }
  | { type: "tool_result"; id: string; name: string; ok: boolean; data: any }
  | { type: "assistant"; text: string }
  | { type: "approval"; actions: ApprovalAction[] }
  | { type: "error"; message: string }
  | { type: "done" };

/** POST a JSON body and read the server-sent events one by one. */
export async function streamPost(path: string, body: unknown, onEvent: (e: StreamEvent) => void) {
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) {
    onEvent({ type: "error", message: `خطای سرور: ${res.status}` });
    onEvent({ type: "done" });
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() || "";
    for (const chunk of chunks) {
      const line = chunk.split("\n").find((l) => l.startsWith("data: "));
      if (line) onEvent(JSON.parse(line.slice(6)) as StreamEvent);
    }
  }
}

export async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}
