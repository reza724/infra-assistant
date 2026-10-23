"use client";

// Human-in-the-loop: the agent stopped and waits for the user's decision.

import { useState } from "react";
import { ArrowLeftRight, Check, ShieldAlert, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { ApprovalAction } from "@/lib/api";

const DETAIL_LABELS: Record<string, string> = {
  key: "نام متغیر",
  value: "مقدار",
  plan_id: "پلن جدید",
  from: "از",
  to: "به",
  monthly_difference_toman: "اختلاف هزینه‌ی ماهانه (تومان)",
};

export function ApprovalCard({
  actions,
  decided,
  onSubmit,
}: {
  actions: ApprovalAction[];
  decided?: Record<string, boolean>;
  onSubmit: (decisions: Record<string, boolean>) => void;
}) {
  const [choice, setChoice] = useState<Record<string, boolean>>({});
  const final = decided || null;

  function pick(id: string, ok: boolean) {
    const next = { ...choice, [id]: ok };
    setChoice(next);
    if (actions.every((a) => a.tool_call_id in next)) onSubmit(next);
  }

  return (
    <Card className="border-warning/50 bg-warning/5">
      <div className="flex items-center gap-2 border-b border-warning/30 px-3 py-2 text-sm font-semibold text-warning">
        <ShieldAlert className="h-4 w-4" /> نیاز به تأیید شما
      </div>
      <div className="space-y-4 p-3">
        {actions.map((a) => {
          const result = final ? final[a.tool_call_id] : choice[a.tool_call_id];
          return (
            <div key={a.tool_call_id} className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold">{a.action}</span>
                <Badge variant="outline" className="ltr font-mono">{a.app}</Badge>
              </div>
              {a.reason && <p className="text-sm"><span className="text-muted-foreground">دلیل: </span>{a.reason}</p>}
              <p className="text-sm"><span className="text-muted-foreground">اثر: </span>{a.impact}</p>
              {Object.keys(a.details || {}).length > 0 && (
                <div className="rounded-md border bg-background p-2 text-sm">
                  {Object.entries(a.details).map(([k, v]) => (
                    <div key={k} className="flex flex-wrap items-center justify-between gap-2 py-0.5">
                      <span className="text-muted-foreground">{DETAIL_LABELS[k] || k}</span>
                      <span className={k === "monthly_difference_toman" ? "font-bold text-warning" : "font-medium"}>
                        {k === "from" || k === "to" ? <span className="flex items-center gap-1"><ArrowLeftRight className="h-3 w-3" />{String(v)}</span> : String(v)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
              {result === undefined ? (
                <div className="flex gap-2">
                  <Button size="sm" onClick={() => pick(a.tool_call_id, true)}><Check className="h-4 w-4" /> تأیید و اجرا</Button>
                  <Button size="sm" variant="outline" onClick={() => pick(a.tool_call_id, false)}><X className="h-4 w-4" /> رد</Button>
                </div>
              ) : (
                <Badge variant={result ? "success" : "secondary"}>{result ? "✓ تأیید کردید" : "✕ رد کردید"}</Badge>
              )}
            </div>
          );
        })}
      </div>
    </Card>
  );
}
