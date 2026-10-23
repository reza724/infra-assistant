"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Bot, MessageSquarePlus, SendHorizontal, Sparkles, User } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { streamPost, type ApprovalAction, type StreamEvent } from "@/lib/api";
import { ApprovalCard } from "./approval-card";
import { CompareCard, type CompareItem } from "./compare-card";
import { SidePanel } from "./side-panel";
import { ToolCard, type ToolItem } from "./tool-cards";

type Item =
  | { kind: "user"; text: string }
  | { kind: "assistant"; text: string }
  | ToolItem
  | { kind: "approval"; actions: ApprovalAction[]; decided?: Record<string, boolean> }
  | CompareItem
  | { kind: "error"; text: string };

const SUGGESTIONS = [
  "سلام، وضعیت سایتم چطوره؟",
  "سایتم کند شده، چک کن ببین مشکل از کجاست",
  "صفحه‌ی greet سایتم خطا میده. مشکل چیه؟",
  "پلن فعلی برای سایتم مناسبه؟",
];

function newThread() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : String(Date.now());
}

export function Chat() {
  const [items, setItems] = useState<Item[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [thread, setThread] = useState(newThread);
  const [refreshKey, setRefreshKey] = useState(0);
  const [currentPlan, setCurrentPlan] = useState<string | undefined>();
  const list = useRef<HTMLDivElement>(null);

  // Values before an approved action, to build the before/after card.
  const before = useRef<{ memory?: number; urls: Record<string, number> }>({ urls: {} });
  const actionDone = useRef(false);

  useEffect(() => {
    const el = list.current;
    if (el && items.length > 0) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [items]);

  const onEvent = useCallback((e: StreamEvent) => {
    setItems((prev) => {
      const next = [...prev];
      switch (e.type) {
        case "tool_start":
          next.push({ kind: "tool", id: e.id, name: e.name, label: e.label, risk: e.risk, status: "running" });
          break;
        case "tool_result": {
          const i = next.findIndex((x) => x.kind === "tool" && x.id === e.id);
          const failed = !e.ok;
          if (i >= 0) next[i] = { ...(next[i] as ToolItem), status: failed ? "failed" : "done", data: e.data };
          const tool = i >= 0 ? (next[i] as ToolItem) : null;
          if (tool?.risk === "HIGH" && e.ok) actionDone.current = true;
          // Before/after for memory and for URL status codes.
          if (e.name === "get_metrics" && typeof e.data?.memory_mb === "number") {
            if (actionDone.current && before.current.memory !== undefined) {
              next.push({ kind: "compare", title: "مصرف حافظه (RAM)", before: before.current.memory, after: e.data.memory_mb, unit: "MB", betterWhenLower: true });
              before.current.memory = undefined;
            } else if (!actionDone.current) before.current.memory = e.data.memory_mb;
          }
          if (e.name === "check_url" && e.data?.url && e.data?.status_code) {
            const path = new URL(e.data.url).pathname;
            const old = before.current.urls[path];
            if (actionDone.current && old !== undefined && old !== e.data.status_code) {
              next.push({ kind: "compare", title: `کد پاسخ ${path}`, before: old, after: e.data.status_code, unit: "", betterWhenLower: true });
              delete before.current.urls[path];
            } else if (!actionDone.current) before.current.urls[path] = e.data.status_code;
          }
          break;
        }
        case "assistant":
          next.push({ kind: "assistant", text: e.text });
          break;
        case "approval": {
          const ids = new Set(e.actions.map((a) => a.tool_call_id));
          for (let k = 0; k < next.length; k++) {
            const x = next[k];
            if (x.kind === "tool" && ids.has(x.id) && x.status === "running") next[k] = { ...x, status: "waiting" };
          }
          next.push({ kind: "approval", actions: e.actions });
          break;
        }
        case "error":
          next.push({ kind: "error", text: e.message });
          break;
      }
      return next;
    });
    if (e.type === "done") {
      setBusy(false);
      setRefreshKey((k) => k + 1);
    }
  }, []);

  async function send(text: string) {
    const msg = text.trim();
    if (!msg || busy || items.some((x) => x.kind === "approval" && !x.decided)) return;
    setInput("");
    setBusy(true);
    actionDone.current = false;
    before.current = { urls: {} };
    setItems((p) => [...p, { kind: "user", text: msg }]);
    await streamPost("/api/chat", { thread_id: thread, message: msg }, onEvent);
  }

  async function decide(index: number, decisions: Record<string, boolean>) {
    setItems((p) => p.map((x, i) => (i === index && x.kind === "approval" ? { ...x, decided: decisions } : x)));
    setBusy(true);
    await streamPost("/api/approve", { thread_id: thread, decisions }, onEvent);
  }

  const pending = items.some((x) => x.kind === "approval" && !x.decided);

  function reset() {
    setItems([]);
    setThread(newThread());
  }

  return (
    <div className="mx-auto grid max-w-7xl gap-4 p-4 lg:grid-cols-[1fr_320px]">
      <Card className="flex h-[calc(100vh-7rem)] min-h-[520px] flex-col">
        <div className="flex items-center justify-between border-b px-4 py-3">
          <div className="flex items-center gap-2">
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-accent"><Bot className="h-5 w-5 text-primary" /></div>
            <div>
              <p className="font-semibold">دستیار زیرساخت</p>
              <p className="text-xs text-muted-foreground">دیپلوی، پایش و عیب‌یابی سایت شما روی لیارا</p>
            </div>
          </div>
          <Button variant="outline" size="sm" onClick={reset} disabled={busy}><MessageSquarePlus className="h-4 w-4" /> گفت‌وگوی جدید</Button>
        </div>

        <div ref={list} className="flex-1 space-y-3 overflow-y-auto p-4">
          {items.length === 0 && (
            <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
              <Sparkles className="h-10 w-10 text-primary" />
              <div>
                <p className="text-lg font-semibold">سلام! مشکل سایتتان را به زبان ساده بگویید.</p>
                <p className="text-sm text-muted-foreground">من لاگ و منابع را بررسی می‌کنم، علت را پیدا می‌کنم و قبل از هر تغییر از شما اجازه می‌گیرم.</p>
              </div>
              <div className="flex max-w-xl flex-wrap justify-center gap-2">
                {SUGGESTIONS.map((s) => (
                  <Button key={s} variant="outline" size="sm" onClick={() => send(s)}>{s}</Button>
                ))}
              </div>
            </div>
          )}
          {items.map((it, i) => {
            if (it.kind === "user")
              return (
                <div key={i} className="flex justify-start gap-2">
                  <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-secondary"><User className="h-4 w-4" /></div>
                  <div className="max-w-[85%] rounded-2xl rounded-tr-sm bg-primary px-4 py-2 text-sm text-primary-foreground">{it.text}</div>
                </div>
              );
            if (it.kind === "assistant")
              return (
                <div key={i} className="flex gap-2">
                  <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent"><Bot className="h-4 w-4 text-primary" /></div>
                  <div dir="auto" className="max-w-[90%] whitespace-pre-wrap rounded-2xl rounded-tr-sm border bg-card px-4 py-2 text-sm leading-7">{it.text}</div>
                </div>
              );
            if (it.kind === "tool") return <div key={i} className="ms-9"><ToolCard item={it} currentPlan={currentPlan} /></div>;
            if (it.kind === "approval")
              return <div key={i} className="ms-9"><ApprovalCard actions={it.actions} decided={it.decided} onSubmit={(d) => decide(i, d)} /></div>;
            if (it.kind === "compare") return <div key={i} className="ms-9"><CompareCard item={it} /></div>;
            return <p key={i} className="ms-9 rounded-md bg-destructive/10 p-2 text-sm text-destructive">{it.text}</p>;
          })}
        </div>

        <form
          className="flex items-end gap-2 border-t p-3"
          onSubmit={(e) => { e.preventDefault(); send(input); }}
        >
          <Textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } }}
            placeholder={pending ? "ابتدا به کارت تأیید پاسخ دهید" : busy ? "دستیار در حال کار است..." : "مثلاً: سایتم کند شده"}
            disabled={busy || pending}
            rows={1}
            className="resize-none"
          />
          <Button type="submit" size="icon" disabled={busy || pending || !input.trim()} aria-label="ارسال">
            <SendHorizontal className="h-4 w-4 rotate-180" />
          </Button>
        </form>
      </Card>

      <SidePanel refreshKey={refreshKey} onPlan={setCurrentPlan} />
    </div>
  );
}
