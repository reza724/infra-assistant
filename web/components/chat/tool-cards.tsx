"use client";

// Generative UI: each tool result is shown with its own component (static level:
// the components are written here, the agent decides when they appear).

import {
  Activity, AlertTriangle, CheckCircle2, Clock, Cpu, FileWarning, Globe, Layers,
  Loader2, MemoryStick, Rocket, Server, ShieldAlert, XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { cn, fmt } from "@/lib/utils";

export type ToolItem = {
  kind: "tool";
  id: string;
  name: string;
  label: string;
  risk: "LOW" | "HIGH";
  status: "running" | "waiting" | "done" | "failed";
  data?: any;
};

const ICONS: Record<string, any> = {
  get_app_status: Server, get_logs: FileWarning, get_metrics: Activity, list_plans: Layers,
  list_releases: Rocket, list_domains: Globe, check_url: Globe, wait_seconds: Clock,
  restart_app: Rocket, set_env: Server, resize_app: Layers, deploy_new_version: Rocket,
};

function Row({ k, v, mono }: { k: string; v: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3 py-1 text-sm">
      <span className="text-muted-foreground">{k}</span>
      <span className={cn("font-medium", mono && "ltr font-mono text-xs")}>{v}</span>
    </div>
  );
}

function StatusCard({ d }: { d: any }) {
  return (
    <div>
      <Row k="وضعیت" v={d.running ? <Badge variant="success">در حال اجرا</Badge> : <Badge variant="destructive">خاموش</Badge>} />
      <Row k="پلن" v={d.plan_id} mono />
      <Row k="پلتفرم" v={d.platform} mono />
      <div className="mt-2 flex flex-wrap items-center gap-1">
        <span className="text-xs text-muted-foreground">متغیرهای محیطی (فقط نام):</span>
        {(d.env_names || []).map((n: string) => (
          <Badge key={n} variant="outline" className="ltr font-mono">{n}</Badge>
        ))}
      </div>
    </div>
  );
}

function MetricsCard({ d }: { d: any }) {
  return (
    <div className="space-y-3">
      <div>
        <div className="mb-1 flex items-center justify-between text-sm">
          <span className="flex items-center gap-1"><MemoryStick className="h-4 w-4" /> حافظه (RAM)</span>
          <span className="font-medium">{fmt(d.memory_mb, 1)} از {fmt(d.memory_limit_mb)} مگابایت</span>
        </div>
        <Progress value={d.memory_percent} />
      </div>
      <div>
        <div className="mb-1 flex items-center justify-between text-sm">
          <span className="flex items-center gap-1"><Cpu className="h-4 w-4" /> پردازنده (CPU)</span>
          <span className="font-medium">{fmt(d.cpu_percent, 1)}٪</span>
        </div>
        <Progress value={d.cpu_percent} />
      </div>
      {d.time && <p className="text-xs text-muted-foreground">زمان اندازه‌گیری: <span className="ltr">{String(d.time).replace("T", " ").slice(0, 19)}</span></p>}
    </div>
  );
}

function LogsCard({ d }: { d: any }) {
  const current = d.current_errors || [];
  const older = d.errors_before_last_start || [];
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        <Badge variant={d.error_count ? "destructive" : "success"}>{fmt(d.error_count)} خطای فعلی</Badge>
        <Badge variant={d.warning_count ? "warning" : "secondary"}>{fmt(d.warning_count)} هشدار</Badge>
        <Badge variant="secondary">{fmt(d.total_lines)} خط در {fmt(d.period_minutes)} دقیقه‌ی اخیر</Badge>
      </div>
      {current.map((e: any, i: number) => (
        <div key={i} className="rounded-md border border-destructive/30 bg-destructive/5 p-2">
          <p className="ltr break-words font-mono text-xs">{e.message}</p>
          <div className="mt-1 flex flex-wrap gap-2 text-xs text-muted-foreground">
            <span>{fmt(e.count)} بار</span>
            {e.where && <span className="ltr font-mono text-destructive">{e.where}</span>}
          </div>
        </div>
      ))}
      {d.last_warning && (
        <p className="ltr rounded-md bg-warning/5 p-2 font-mono text-xs text-warning">{d.last_warning}</p>
      )}
      {older.length > 0 && (
        <details className="text-xs text-muted-foreground">
          <summary className="cursor-pointer">{fmt(older.length)} نوع خطای قدیمی (قبل از آخرین راه‌اندازی؛ احتمالاً رفع شده)</summary>
          {older.map((e: any, i: number) => (
            <p key={i} className="ltr mt-1 font-mono">{e.message} ×{e.count}</p>
          ))}
        </details>
      )}
    </div>
  );
}

function UrlCard({ d }: { d: any }) {
  const good = d.status_code && d.status_code < 400;
  return (
    <div>
      <Row k="آدرس" v={d.url} mono />
      <Row k="کد پاسخ" v={<Badge variant={good ? "success" : "destructive"} className="ltr">{d.status_code ?? "—"}</Badge>} />
      <Row k="زمان پاسخ" v={`${fmt(d.response_ms)} میلی‌ثانیه`} />
      {d.body_start && <p className="ltr mt-1 truncate rounded bg-muted p-1.5 font-mono text-xs">{d.body_start}</p>}
    </div>
  );
}

function PlansCard({ d, currentPlan }: { d: any[]; currentPlan?: string }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-xs text-muted-foreground">
          <tr><th className="p-1 text-right">پلن</th><th className="p-1">RAM</th><th className="p-1">CPU</th><th className="p-1 text-left">قیمت ماهانه (تومان)</th></tr>
        </thead>
        <tbody>
          {d.slice(0, 5).map((p) => (
            <tr key={p.plan_id} className={cn("border-t", p.plan_id === currentPlan && "bg-accent font-semibold")}>
              <td className="ltr p-1 text-right font-mono text-xs">{p.plan_id}{p.plan_id === currentPlan && " ◂"}</td>
              <td className="p-1 text-center">{fmt(p.ram_gb, 1)} GB</td>
              <td className="p-1 text-center">{fmt(p.cpu_cores, 1)}</td>
              <td className="p-1 text-left">{fmt(p.price_per_month_toman)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ReleasesCard({ d }: { d: any[] }) {
  return (
    <div className="space-y-1">
      {d.map((r) => (
        <div key={r.release_id} className="flex items-center justify-between text-sm">
          <span className="ltr font-mono text-xs">{r.tag}</span>
          <Badge variant={r.state === "READY" ? "success" : r.state === "FAILED" ? "destructive" : "secondary"}>{r.state}</Badge>
        </div>
      ))}
    </div>
  );
}

function DomainsCard({ d }: { d: any }) {
  return (
    <div>
      <Row k="آدرس پیش‌فرض" v={d.default_address} mono />
      {(d.domains || []).length === 0 ? (
        <p className="text-sm text-muted-foreground">هیچ دامنه‌ی اختصاصی به این برنامه وصل نیست.</p>
      ) : (
        d.domains.map((x: any) => <Row key={x.name} k={x.name} v={x.status || x.certificate || "—"} />)
      )}
    </div>
  );
}

function ActionResultCard({ d, ok }: { d: any; ok: boolean }) {
  if (!ok) {
    return (
      <div className="text-sm">
        {d.status === "rejected_by_user" ? (
          <p className="flex items-center gap-1 text-muted-foreground"><XCircle className="h-4 w-4" /> شما این اقدام را رد کردید؛ کاری انجام نشد.</p>
        ) : (
          <>
            <p className="flex items-center gap-1 text-destructive"><AlertTriangle className="h-4 w-4" /> اقدام ناموفق بود: <span className="ltr">{d.error}</span></p>
            {d.hint && <p className="mt-1 text-xs text-muted-foreground">{d.hint}</p>}
          </>
        )}
      </div>
    );
  }
  return (
    <p className="flex items-center gap-1 text-sm text-success">
      <CheckCircle2 className="h-4 w-4" /> با موفقیت انجام شد{d.state ? ` (وضعیت: ${d.state})` : ""}.
    </p>
  );
}

function ToolBody({ item, currentPlan }: { item: ToolItem; currentPlan?: string }) {
  const d = item.data;
  if (d && d.ok === false && item.risk !== "HIGH") {
    return <p className="ltr text-sm text-destructive">{d.error}{d.hint ? ` — ${d.hint}` : ""}</p>;
  }
  switch (item.name) {
    case "get_app_status": return <StatusCard d={d} />;
    case "get_metrics": return <MetricsCard d={d} />;
    case "get_logs": return <LogsCard d={d} />;
    case "check_url": return <UrlCard d={d} />;
    case "list_plans": return Array.isArray(d) ? <PlansCard d={d} currentPlan={currentPlan} /> : null;
    case "list_releases": return Array.isArray(d) ? <ReleasesCard d={d} /> : null;
    case "list_domains": return <DomainsCard d={d} />;
    case "wait_seconds": return null;
    default:
      if (item.risk === "HIGH") return <ActionResultCard d={d} ok={item.status === "done"} />;
      return <pre className="ltr overflow-x-auto text-xs">{JSON.stringify(d, null, 2)}</pre>;
  }
}

/** One tool step: a small running row, then a card with the result. */
export function ToolCard({ item, currentPlan }: { item: ToolItem; currentPlan?: string }) {
  const Icon = ICONS[item.name] || Server;
  if (item.status === "running") {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin text-primary" /> {item.label}...
      </div>
    );
  }
  if (item.status === "waiting") {
    return (
      <div className="flex items-center gap-2 text-sm text-warning">
        <ShieldAlert className="h-4 w-4" /> {item.label}: منتظر تأیید شما
      </div>
    );
  }
  if (item.name === "wait_seconds") {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Clock className="h-3.5 w-3.5" /> {fmt(item.data?.waited_seconds)} ثانیه صبر برای اعمال تغییر
      </div>
    );
  }
  return (
    <Card className={cn("overflow-hidden", item.risk === "HIGH" && "border-primary/40")}>
      <div className="flex items-center gap-2 border-b bg-muted/40 px-3 py-2 text-sm font-medium">
        <Icon className="h-4 w-4 text-primary" />
        {item.label}
        {item.status === "failed" ? <XCircle className="ms-auto h-4 w-4 text-destructive" /> : <CheckCircle2 className="ms-auto h-4 w-4 text-success" />}
      </div>
      <div className="p-3"><ToolBody item={item} currentPlan={currentPlan} /></div>
    </Card>
  );
}
