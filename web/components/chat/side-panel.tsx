"use client";

// "Chat plus" layout: this panel shows the live state of the app next to the chat.

import { useCallback, useEffect, useState } from "react";
import { Activity, ExternalLink, History, Info, RefreshCw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { getJSON } from "@/lib/api";
import { fmt } from "@/lib/utils";

type Overview = { app: string; url: string; status?: any; metrics?: any };
type AuditEntry = { time: string; tool: string; label: string; risk: string; approved: boolean | null };

export function SidePanel({ refreshKey, onPlan }: { refreshKey: number; onPlan: (p?: string) => void }) {
  const [ov, setOv] = useState<Overview | null>(null);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [limits, setLimits] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [o, a] = await Promise.all([getJSON<Overview>("/api/overview"), getJSON<AuditEntry[]>("/api/audit")]);
      setOv(o);
      setAudit(a);
      onPlan(o.status?.plan_id);
      setError("");
    } catch {
      setError("اتصال به سرور دستیار برقرار نیست. server.py را اجرا کنید.");
    } finally {
      setLoading(false);
    }
  }, [onPlan]);

  useEffect(() => { load(); }, [load, refreshKey]);
  useEffect(() => { getJSON<string[]>("/api/limits").then(setLimits).catch(() => {}); }, []);
  useEffect(() => { const t = setInterval(load, 60000); return () => clearInterval(t); }, [load]);

  const s = ov?.status;
  const m = ov?.metrics;
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="flex items-center gap-2 text-base"><Activity className="h-4 w-4 text-primary" /> وضعیت زنده</CardTitle>
          <Button variant="ghost" size="icon" onClick={load} aria-label="به‌روزرسانی">
            <RefreshCw className={loading ? "h-4 w-4 animate-spin" : "h-4 w-4"} />
          </Button>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          {error && <p className="text-destructive">{error}</p>}
          {ov && (
            <>
              <div className="flex items-center justify-between">
                <span className="ltr font-mono text-xs">{ov.app}</span>
                {s?.running ? <Badge variant="success">در حال اجرا</Badge> : <Badge variant="destructive">نامشخص</Badge>}
              </div>
              <a href={ov.url} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-xs text-primary hover:underline">
                <ExternalLink className="h-3 w-3" /> <span className="ltr">{ov.url.replace("https://", "")}</span>
              </a>
              <div className="flex justify-between"><span className="text-muted-foreground">پلن</span><span className="ltr font-mono text-xs">{s?.plan_id ?? "—"}</span></div>
              <div>
                <div className="mb-1 flex justify-between"><span className="text-muted-foreground">RAM</span><span>{fmt(m?.memory_mb, 1)} / {fmt(m?.memory_limit_mb)} MB</span></div>
                <Progress value={m?.memory_percent} />
              </div>
              <div>
                <div className="mb-1 flex justify-between"><span className="text-muted-foreground">CPU</span><span>{fmt(m?.cpu_percent, 1)}٪</span></div>
                <Progress value={m?.cpu_percent} />
              </div>
              <p className="text-xs text-muted-foreground">متریک‌های لیارا ممکن است چند دقیقه تأخیر داشته باشند.</p>
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2"><CardTitle className="flex items-center gap-2 text-base"><History className="h-4 w-4 text-primary" /> تاریخچه‌ی اقدامات</CardTitle></CardHeader>
        <CardContent className="space-y-1.5 text-sm">
          {audit.length === 0 && <p className="text-muted-foreground">هنوز اقدامی ثبت نشده است.</p>}
          {audit.slice(0, 8).map((e, i) => (
            <div key={i} className="flex items-center justify-between gap-2">
              <span className="truncate">{e.label}</span>
              {e.risk === "HIGH" ? (
                <Badge variant={e.approved ? "success" : "secondary"}>{e.approved ? "تأیید و اجرا" : "رد شد"}</Badge>
              ) : (
                <Badge variant="outline">خودکار</Badge>
              )}
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2"><CardTitle className="flex items-center gap-2 text-base"><Info className="h-4 w-4 text-primary" /> چه کارهایی خودکار است؟</CardTitle></CardHeader>
        <CardContent className="space-y-2 text-xs text-muted-foreground">
          <p><Badge variant="outline">خودکار</Badge> خواندن وضعیت، لاگ، متریک، پلن‌ها و تست آدرس سایت.</p>
          <p><Badge variant="warning">با تأیید شما</Badge> ری‌استارت، تغییر متغیر محیطی، تغییر پلن، دیپلوی.</p>
          {limits.length > 0 && (
            <details>
              <summary className="cursor-pointer">محدودیت‌های API لیارا</summary>
              <ul className="mt-1 list-disc space-y-1 ps-4">
                {limits.map((l) => <li key={l}>{l}</li>)}
              </ul>
            </details>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
