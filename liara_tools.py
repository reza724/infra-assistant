"""
Liara tool layer for the infrastructure assistant.

Each public function is one operation on the Liara API.
Each function has a risk level:
  - LOW  : read-only. The agent can run it automatically.
  - HIGH : changes the service. The agent must get user approval first.

Endpoints come from the official Liara CLI source (github.com/liara-cloud/cli),
except where a function says "UNVERIFIED".
"""

from __future__ import annotations

import io
import json
import os
import tarfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests

LOW = "LOW"
HIGH = "HIGH"

DEFAULT_BASE_URL = "https://api.liara.ir"
REQUEST_TIMEOUT = 20  # seconds

# Words in a log line that show an error or a warning.
ERROR_MARKERS = ("[error]", "error:", "exception", "typeerror", "referenceerror",
                 "unhandled", "fatal", "econnrefused", "out of memory", "killed")
WARN_MARKERS = ("[warn]", "warning", "deprecated")

# Lines that show that the app process started (again). Errors before the last
# start can be already fixed by the restart, an env change or a new deploy.
START_MARKERS = ("listening on", "server running", "server started", "started server",
                 "uvicorn running", "booting worker", "application startup complete",
                 "ready on", "[start]")


# --------------------------------------------------------------------------
# HTTP client
# --------------------------------------------------------------------------

class LiaraAPIError(Exception):
    """An error from the Liara API, with the HTTP status code."""

    def __init__(self, status: int, message: str, path: str):
        super().__init__(f"Liara API error {status} on {path}: {message}")
        self.status = status
        self.message = message
        self.path = path


class LiaraClient:
    """Small HTTP client for the Liara API. It adds the token and the team ID."""

    def __init__(self, token: str, team_id: str = "", base_url: str = DEFAULT_BASE_URL):
        if not token:
            raise ValueError("LIARA_API_TOKEN is empty.")
        self.base_url = base_url.rstrip("/")
        self.team_id = team_id
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    @classmethod
    def from_env(cls) -> "LiaraClient":
        """Make a client from the environment variables in .env."""
        return cls(
            token=os.environ.get("LIARA_API_TOKEN", ""),
            team_id=os.environ.get("LIARA_TEAM_ID", ""),
            base_url=DEFAULT_BASE_URL,  # Same base URL as the official CLI.
        )

    def request(self, method: str, path: str, params: dict | None = None,
                json_body: dict | None = None, files: dict | None = None,
                timeout: int | None = REQUEST_TIMEOUT) -> Any:
        """Send one request. Return the JSON body, or raise LiaraAPIError."""
        params = dict(params or {})
        params["teamID"] = self.team_id  # The CLI sends teamID on every request.
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            resp = self.session.request(method, url, params=params, json=json_body,
                                        files=files, timeout=timeout)
        except requests.RequestException as exc:
            raise LiaraAPIError(0, f"network error: {exc}", path) from exc

        if resp.status_code >= 400:
            try:
                msg = resp.json().get("error") or resp.json().get("message") or resp.text
            except ValueError:
                msg = resp.text
            raise LiaraAPIError(resp.status_code, str(msg)[:300], path)

        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            return {"raw": resp.text[:1000]}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _ns_to_iso(ns: str | int) -> str:
    """Convert a nanosecond timestamp to an ISO time string (UTC)."""
    return datetime.fromtimestamp(int(ns) / 1e9, tz=timezone.utc).isoformat(timespec="seconds")


def _classify_line(text: str, stream: str) -> str:
    """Return 'error', 'warn' or 'info' for one log line.

    Text markers come first, because Node.js writes console.warn to stderr too.
    """
    low = text.lower()
    if any(m in low for m in WARN_MARKERS):
        return "warn"
    if any(m in low for m in ERROR_MARKERS) or stream == "stderr":
        return "error"
    return "info"


def _is_stack_line(text: str) -> bool:
    """True for a stack trace line, for example '    at /app/index.js:27:11'."""
    stripped = text.lstrip()
    return text[:1].isspace() and (stripped.startswith("at ") or stripped.startswith("..."))


def group_stack_traces(lines: list[dict]) -> list[dict]:
    """Join stack trace lines to the error line above them, so one error = one event."""
    events: list[dict] = []
    for line in lines:
        if events and _is_stack_line(line["text"]):
            events[-1].setdefault("stack", []).append(line["text"].strip())
            continue
        events.append(dict(line))
    return events


def summarize_errors(events: list[dict]) -> list[dict]:
    """Count each different error message (numbers removed), most frequent first."""
    import re
    counts: dict[str, dict] = {}
    for e in events:
        if e["level"] != "error":
            continue
        key = re.sub(r"\d+", "N", e["text"])[:200]
        item = counts.setdefault(key, {"message": e["text"][:300], "count": 0,
                                       "first_seen": e["time"], "where": None})
        item["count"] += 1
        item["last_seen"] = e["time"]
        if e.get("stack") and not item["where"]:
            item["where"] = e["stack"][0]  # First stack line shows the file and line.
    now = datetime.now(timezone.utc)
    for item in counts.values():
        last = datetime.fromisoformat(item["last_seen"])
        item["minutes_ago"] = round((now - last).total_seconds() / 60, 1)
    return sorted(counts.values(), key=lambda x: -x["count"])


def parse_logs(raw: dict) -> list[dict]:
    """Turn the raw /v2/projects/{app}/logs response into a sorted list of lines."""
    lines: list[dict] = []
    for group in raw.get("data", []) or []:
        release_id = (group.get("metaData") or {}).get("releaseId", "")
        for ts, payload in group.get("values", []) or []:
            try:
                entry = json.loads(payload)
                text = entry.get("_entry", "")
                stream = entry.get("type", "stdout")
            except (ValueError, TypeError):
                text, stream = str(payload), "stdout"
            if not text.strip():
                continue
            lines.append({
                "ts_ns": int(ts),
                "time": _ns_to_iso(ts),
                "stream": stream,
                "level": _classify_line(text, stream),
                "text": text,
                "release_id": release_id,
            })
    lines.sort(key=lambda x: x["ts_ns"])
    return lines


def parse_metrics(raw: dict) -> dict:
    """Turn the raw metrics/summary response into simple numbers."""
    def latest(series: list) -> tuple[int | None, float | None]:
        if not series:
            return None, None
        point = max(series, key=lambda s: s["value"][0])
        return int(point["value"][0]), float(point["value"][1])

    cpu_ts, cpu_cores = latest(raw.get("cpuUsage", []))
    mem_ts, mem_bytes = latest(raw.get("memoryUsage", []))
    return {
        "time": datetime.fromtimestamp(cpu_ts or mem_ts or 0, tz=timezone.utc).isoformat(timespec="seconds"),
        "cpu_cores_used": round(cpu_cores, 4) if cpu_cores is not None else None,
        "memory_mb": round(mem_bytes / 1024 / 1024, 1) if mem_bytes is not None else None,
        "instances": len(raw.get("memoryUsage", [])),
    }


# --------------------------------------------------------------------------
# LOW risk tools (read-only)
# --------------------------------------------------------------------------

def get_app_status(client: LiaraClient, app: str) -> dict:
    """Get the status, plan, scale and environment variable NAMES of an app."""
    project = client.request("GET", f"v1/projects/{app}").get("project", {})
    return {
        "app": project.get("project_id", app),
        "status": project.get("status"),
        "running": project.get("scale", 0) > 0,
        "scale": project.get("scale"),
        "platform": project.get("type"),
        "plan_id": project.get("planID"),
        "bundle_plan": project.get("bundlePlanID"),
        "zero_downtime": project.get("zeroDowntime"),
        "deployed": project.get("isDeployed", True),
        # Only names. Values can be secrets, so we do not send them to the LLM.
        "env_names": [e.get("key") for e in project.get("envs", [])],
        "created_at": project.get("created_at"),
    }


def fetch_all_logs(client: LiaraClient, app: str, start: int, max_pages: int = 30) -> list[dict]:
    """Read logs page by page from 'start' (unix seconds), like the Liara CLI does.

    The API returns one page at a time. The next page starts one second
    after the last line of the previous page.
    """
    lines: list[dict] = []
    seen: set[tuple[int, str]] = set()
    for _ in range(max_pages):
        raw = client.request("GET", f"v2/projects/{app}/logs",
                             params={"start": start, "direction": "forward"})
        raw_ts = [int(ts) for g in raw.get("data", []) or [] for ts, _ in g.get("values", []) or []]
        if not raw_ts:
            break
        page = [l for l in parse_logs(raw) if (l["ts_ns"], l["text"]) not in seen]
        for line in page:
            seen.add((line["ts_ns"], line["text"]))
        lines.extend(page)
        next_start = int(str(max(raw_ts))[:10]) + 1
        if next_start <= start or next_start > time.time() + 1:
            break
        start = next_start
    lines.sort(key=lambda x: x["ts_ns"])
    return lines


def _last_start(lines: list[dict]) -> dict | None:
    """Return the last log line that shows an app start, or None."""
    starts = [l for l in lines if any(m in l["text"].lower() for m in START_MARKERS)]
    return starts[-1] if starts else None


def get_logs(client: LiaraClient, app: str, minutes: int = 60,
             max_lines: int = 80, errors_only: bool = False) -> dict:
    """Get recent log lines and a summary of errors and warnings.

    Errors are split in two groups:
      - current_errors: after the last app start (they are still a real problem)
      - errors_before_last_start: older; the last restart, env change or deploy may have fixed them
    """
    lines = fetch_all_logs(client, app, int(time.time()) - minutes * 60)
    events = group_stack_traces(lines)
    start = _last_start(lines)
    start_ns = start["ts_ns"] if start else 0

    current = [e for e in events if e["ts_ns"] >= start_ns]
    older = [e for e in events if e["ts_ns"] < start_ns]
    errors = [e for e in current if e["level"] == "error"]
    warns = [e for e in current if e["level"] == "warn"]
    chosen = errors if errors_only else current
    return {
        "app": app,
        "period_minutes": minutes,
        "last_app_start": start["time"] if start else "not found in this period",
        "total_lines": len(lines),
        "error_count": len(errors),
        "warning_count": len(warns),
        "last_error": errors[-1]["text"] if errors else None,
        "last_warning": warns[-1]["text"] if warns else None,
        "current_errors": summarize_errors(current),
        "errors_before_last_start": summarize_errors(older),
        "events": [{"time": e["time"], "level": e["level"], "text": e["text"][:300],
                    **({"where": e["stack"][0]} if e.get("stack") else {})}
                   for e in chosen[-max_lines:]],
    }


def get_metrics(client: LiaraClient, app: str) -> dict:
    """Get current CPU and RAM use, and compare them with the plan limits."""
    raw = client.request("GET", f"v1/projects/{app}/metrics/summary")
    metrics = parse_metrics(raw)
    metrics["app"] = app

    # Add plan limits so the agent can see "how full" the app is.
    try:
        status = get_app_status(client, app)
        plan = get_plan(client, status["plan_id"])
        if plan and metrics["memory_mb"] is not None and plan.get("ram_gb"):
            metrics["memory_limit_mb"] = plan["ram_gb"] * 1024
            metrics["memory_percent"] = round(100 * metrics["memory_mb"] / metrics["memory_limit_mb"], 1)
        if plan and metrics["cpu_cores_used"] is not None and plan.get("cpu_cores"):
            metrics["cpu_limit_cores"] = plan["cpu_cores"]
            metrics["cpu_percent"] = round(100 * metrics["cpu_cores_used"] / plan["cpu_cores"], 1)
        metrics["plan_id"] = status["plan_id"]
    except LiaraAPIError:
        metrics["note"] = "Plan limits are not available."
    return metrics


def list_plans(client: LiaraClient) -> list[dict]:
    """List the available app plans in Iran (same filter as the Liara CLI)."""
    plans = client.request("GET", "v1/me").get("plans", {})
    result = []
    for plan_id, p in (plans.get("projects") or {}).items():
        if not (plan_id == "free" or "g2" in plan_id):
            continue
        if not p.get("available") or p.get("region") != "iran":
            continue
        result.append({
            "plan_id": plan_id,
            "ram_gb": (p.get("RAM") or {}).get("amount"),
            "cpu_cores": (p.get("CPU") or {}).get("amount"),
            "disk_gb": p.get("volume"),
            "price_per_month_toman": round(p.get("price", 0) * 720),
        })
    result.sort(key=lambda x: (x["ram_gb"] or 0, x["cpu_cores"] or 0))
    return result


def get_plan(client: LiaraClient, plan_id: str) -> dict | None:
    """Get one plan by its ID."""
    return next((p for p in list_plans(client) if p["plan_id"] == plan_id), None)


def list_releases(client: LiaraClient, app: str, count: int = 5) -> list[dict]:
    """List the last releases (deploys) of an app."""
    data = client.request("GET", f"v1/projects/{app}/releases", params={"count": count})
    releases = data.get("releases", data if isinstance(data, list) else [])
    return [{
        "release_id": r.get("_id"),
        "tag": r.get("tag"),
        "state": r.get("state"),
        "created_at": r.get("created_at"),
        "fail_reason": r.get("failReason"),
    } for r in releases[:count]]


def list_domains(client: LiaraClient, app: str) -> dict:
    """List the custom domains connected to the app on Liara, with their status."""
    domains = client.request("GET", "v1/domains", params={"project": app}).get("domains", [])
    return {"app": app, "default_address": f"https://{app}.liara.run",
            "domains": [{"name": d.get("name"), "status": d.get("status"),
                         "certificate": d.get("certificatesStatus"), "type": d.get("type")}
                        for d in domains]}


def get_release(client: LiaraClient, release_id: str) -> dict:
    """Get the state of one release (BUILDING, DEPLOYING, READY, FAILED, ...)."""
    release = client.request("GET", f"v1/releases/{release_id}").get("release", {})
    return {"release_id": release_id, "state": release.get("state"),
            "status": release.get("status"), "fail_reason": release.get("failReason")}


# --------------------------------------------------------------------------
# HIGH risk tools (need user approval)
# --------------------------------------------------------------------------

def restart_app(client: LiaraClient, app: str) -> dict:
    """Restart the app. The site can be down for a short time."""
    client.request("POST", f"v1/projects/{app}/actions/restart")
    return {"app": app, "action": "restart", "ok": True}


def scale_app(client: LiaraClient, app: str, scale: int) -> dict:
    """Start (scale=1) or stop (scale=0) the app."""
    if scale not in (0, 1):
        raise ValueError("scale must be 0 or 1.")
    client.request("POST", f"v1/projects/{app}/actions/scale", json_body={"scale": scale})
    return {"app": app, "action": "start" if scale else "stop", "ok": True}


def set_env(client: LiaraClient, app: str, key: str, value: str) -> dict:
    """Set one environment variable. Liara restarts the app after this change."""
    project = client.request("GET", f"v1/projects/{app}").get("project", {})
    variables = [{"key": e["key"], "value": e["value"]}
                 for e in project.get("envs", []) if e.get("key") != key]
    variables.append({"key": key, "value": value})
    client.request("POST", "v1/projects/update-envs",
                   json_body={"project": app, "variables": variables})
    return {"app": app, "action": "set_env", "key": key, "ok": True, "note": "The app restarts."}


def unset_env(client: LiaraClient, app: str, key: str) -> dict:
    """Remove one environment variable (used by the scenario setup). The app restarts."""
    project = client.request("GET", f"v1/projects/{app}").get("project", {})
    variables = [{"key": e["key"], "value": e["value"]}
                 for e in project.get("envs", []) if e.get("key") != key]
    client.request("POST", "v1/projects/update-envs",
                   json_body={"project": app, "variables": variables})
    return {"app": app, "action": "unset_env", "key": key, "ok": True}


def resize_app(client: LiaraClient, app: str, plan_id: str) -> dict:
    """Change the app plan. This changes the cost. UNVERIFIED endpoint."""
    client.request("POST", f"v1/projects/{app}/resize", json_body={"planID": plan_id})
    return {"app": app, "action": "resize", "new_plan": plan_id, "ok": True}


def _make_tarball(source_dir: str) -> bytes:
    """Pack the source folder into a tar.gz file in memory."""
    skip = {"node_modules", ".git", "__pycache__", ".venv", ".env"}
    buf = io.BytesIO()
    root = Path(source_dir).resolve()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path in root.rglob("*"):
            if any(part in skip for part in path.relative_to(root).parts):
                continue
            tar.add(path, arcname=str(path.relative_to(root)), recursive=False)
    return buf.getvalue()


def deploy_source(client: LiaraClient, app: str, source_dir: str, port: int = 3000,
                  platform: str = "node", message: str = "Deployed by the assistant",
                  wait: bool = True, max_wait_s: int = 300) -> dict:
    """Upload the source folder and create a new release, like 'liara deploy'."""
    tarball = _make_tarball(source_dir)
    upload = client.request("POST", f"v2/projects/{app}/sources",
                            files={"file": ("source.tar.gz", tarball, "application/gzip")},
                            timeout=None)
    source_id = upload.get("sourceID")
    if not source_id:
        raise LiaraAPIError(0, f"upload gave no sourceID: {upload}", "sources")

    body = {"sourceID": source_id, "port": port, "type": platform,
            "message": message, "platformConfig": {}, "build": {}}
    release_id = client.request("POST", f"v2/projects/{app}/releases",
                                json_body=body).get("releaseID")
    result = {"app": app, "action": "deploy", "release_id": release_id, "state": "CREATED"}

    if wait and release_id:
        deadline = time.time() + max_wait_s
        while time.time() < deadline:
            info = get_release(client, release_id)
            result.update(state=info["state"], fail_reason=info["fail_reason"])
            if info["state"] in ("READY", "FAILED", "UNHEALTHY", "CANCELED"):
                break
            time.sleep(5)
    result["ok"] = result["state"] == "READY"
    return result


# --------------------------------------------------------------------------
# Tool registry (used by the agent in phase 3)
# --------------------------------------------------------------------------

@dataclass
class Tool:
    name: str
    func: Callable[..., Any]
    risk: str
    description: str


TOOLS: dict[str, Tool] = {t.name: t for t in [
    Tool("get_app_status", get_app_status, LOW, "Status, plan, scale and env names of the app."),
    Tool("get_logs", get_logs, LOW, "Recent log lines with error and warning counts."),
    Tool("get_metrics", get_metrics, LOW, "Current CPU and RAM use compared with plan limits."),
    Tool("list_plans", list_plans, LOW, "Available app plans with RAM, CPU and monthly price."),
    Tool("list_releases", list_releases, LOW, "Last deploys of the app and their state."),
    Tool("list_domains", list_domains, LOW, "Custom domains of the app and their status."),
    Tool("restart_app", restart_app, HIGH, "Restart the app. Short downtime is possible."),
    Tool("scale_app", scale_app, HIGH, "Start (1) or stop (0) the app."),
    Tool("set_env", set_env, HIGH, "Set one environment variable. The app restarts."),
    Tool("resize_app", resize_app, HIGH, "Change the app plan. This changes the cost."),
    Tool("deploy_source", deploy_source, HIGH, "Upload source code and deploy a new release."),
]}

# Operations that the Liara API does not support (the agent must tell the user).
API_LIMITS = [
    "Domain registration and DNS records in an external registrar (for example IRNIC) are outside the Liara API.",
    "Payment and adding credit to the account are not possible through the API.",
    "The metrics endpoint gives only one recent value, not a history, and the value can lag a few minutes.",
    "Connecting a new custom domain is done in the Liara console (Domains section of the app); "
    "this assistant can only read the domain status.",
]

# The same limits in Persian, for the web interface.
API_LIMITS_FA = [
    "ثبت دامنه و تنظیم DNS سرورها در ثبت‌کننده‌ی بیرونی (مثل ایرنیک) خارج از API لیاراست.",
    "پرداخت و افزایش اعتبار حساب از طریق API ممکن نیست.",
    "متریک‌ها فقط یک مقدار اخیر را نشان می‌دهند (بدون تاریخچه) و ممکن است چند دقیقه تأخیر داشته باشند.",
    "اتصال دامنه‌ی جدید به برنامه در کنسول لیارا انجام می‌شود؛ دستیار فقط وضعیت دامنه را می‌خواند.",
]
