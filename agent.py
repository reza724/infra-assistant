"""
Phase 3: the agent brain (LangGraph).

Graph:
    START -> agent -> (no tool call)  -> END
                   -> (tool calls)    -> approval -> tools -> agent

- agent    : the LLM decides the next step (answer, or call tools).
- approval : if a HIGH risk tool is called, the graph stops (interrupt) and
             asks the user. LOW risk tools pass without a question.
- tools    : runs the tools, writes every action to audit_log.jsonl.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Annotated, Any, TypedDict

import requests
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import interrupt

import liara_tools as lt

MAX_AGENT_STEPS = 12          # Upper limit of LLM turns for one user message.
AUDIT_LOG = "audit_log.jsonl"
BLOCKED_CHECK_PATHS = {"/leak", "/cpu"}  # check_url must not make the problem worse.

_client: lt.LiaraClient | None = None


def client() -> lt.LiaraClient:
    """Make the Liara client one time (lazy), from .env values."""
    global _client
    if _client is None:
        _client = lt.LiaraClient.from_env()
    return _client


def default_app() -> str:
    return os.environ.get("LIARA_APP_ID", "")


def _safe(func, *args, **kwargs) -> str:
    """Run a tool function. Return JSON text. Return the error as data, not as a crash."""
    try:
        return json.dumps(func(*args, **kwargs), ensure_ascii=False)
    except lt.LiaraAPIError as exc:
        hint = ""
        if exc.status == 404:
            hint = "The endpoint or the app was not found. This operation may not be supported by the Liara API."
        return json.dumps({"ok": False, "error": exc.message, "status": exc.status, "hint": hint},
                          ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001 - the agent must see every error
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)


# --------------------------------------------------------------------------
# Tools that the LLM can call
# --------------------------------------------------------------------------

@tool
def get_app_status(app: str) -> str:
    """Get the status of a Liara app: running or not, plan ID, scale and environment variable NAMES.
    Use it first for any question about the app."""
    return _safe(lt.get_app_status, client(), app)


@tool
def get_logs(app: str, minutes: int = 30, errors_only: bool = False) -> str:
    """Get recent logs of a Liara app.
    current_errors = errors AFTER the last app start: these are real, current problems.
    errors_before_last_start = older errors: a restart, env change or deploy may have fixed them.
    Each error shows how many times it happened and where in the code.
    Use it when the user reports an error, a crash or strange behavior."""
    return _safe(lt.get_logs, client(), app, minutes=minutes, errors_only=errors_only, max_lines=30)


@tool
def get_metrics(app: str) -> str:
    """Get current CPU and RAM use of a Liara app, with percent of the plan limit.
    Use it when the user reports slowness, or to check memory or CPU problems."""
    return _safe(lt.get_metrics, client(), app)


@tool
def list_plans() -> str:
    """List the available Liara app plans with RAM, CPU, disk and monthly price in toman.
    Use it before you suggest a plan change, to compare prices."""
    return _safe(lt.list_plans, client())


@tool
def list_releases(app: str) -> str:
    """List the last deploys (releases) of the app and their state (READY, FAILED, ...)."""
    return _safe(lt.list_releases, client(), app, count=5)


@tool
def list_domains(app: str) -> str:
    """List the custom domains connected to the app on Liara and their status.
    Use it for any question about domains before you say anything about them."""
    return _safe(lt.list_domains, client(), app)


@tool
def check_url(app: str, path: str = "/") -> str:
    """Send one HTTP GET to the public address of the app (https://APP.liara.run + path).
    Return the HTTP status code, the response time and the start of the body.
    Use it to see the problem and to verify a fix. Do not use /leak or /cpu."""
    if path in BLOCKED_CHECK_PATHS:
        return json.dumps({"ok": False, "error": f"{path} is blocked because it makes the problem worse."})
    url = f"https://{app}.liara.run{path if path.startswith('/') else '/' + path}"
    try:
        start = time.time()
        resp = requests.get(url, timeout=15)
        return json.dumps({"url": url, "status_code": resp.status_code,
                           "response_ms": round((time.time() - start) * 1000),
                           "body_start": resp.text[:200]}, ensure_ascii=False)
    except requests.RequestException as exc:
        return json.dumps({"url": url, "ok": False, "error": str(exc)})


@tool
def wait_seconds(seconds: int = 30) -> str:
    """Wait some seconds (5 to 90). Use it after a restart, an env change or a deploy,
    before you check the result again."""
    seconds = max(5, min(int(seconds), 90))
    time.sleep(seconds)
    return json.dumps({"waited_seconds": seconds})


@tool
def restart_app(app: str, reason: str) -> str:
    """HIGH RISK. Restart the app. The site can be down for a few seconds.
    It frees memory, so it is a quick fix for a memory leak.
    'reason' must explain to the user in simple Persian why this is necessary."""
    return _safe(lt.restart_app, client(), app)


@tool
def set_env(app: str, key: str, value: str, reason: str) -> str:
    """HIGH RISK. Set one environment variable on the app. Liara restarts the app after it.
    Use it when the logs show that a variable is missing or wrong.
    'reason' must explain to the user in simple Persian why this is necessary."""
    return _safe(lt.set_env, client(), app, key, value)


@tool
def resize_app(app: str, plan_id: str, reason: str) -> str:
    """HIGH RISK. Change the plan of the app (more or less RAM and CPU). This changes the monthly cost.
    Call list_plans first and choose the next plan, not a very large one.
    'reason' must explain to the user in simple Persian why this is necessary."""
    return _safe(lt.resize_app, client(), app, plan_id)


@tool
def deploy_new_version(app: str, reason: str) -> str:
    """HIGH RISK. Upload the local source code folder and deploy it as a new release.
    Use it after the user fixed the code. It waits until the release is READY or FAILED.
    'reason' must explain to the user in simple Persian why this is necessary."""
    source_dir = os.environ.get("TARGET_APP_DIR", "target-app")
    return _safe(lt.deploy_source, client(), app, source_dir, port=3000, platform="node")


ALL_TOOLS = [get_app_status, get_logs, get_metrics, list_plans, list_releases, list_domains, check_url,
             wait_seconds, restart_app, set_env, resize_app, deploy_new_version]
TOOLS_BY_NAME = {t.name: t for t in ALL_TOOLS}
HIGH_RISK = {"restart_app", "set_env", "resize_app", "deploy_new_version"}


# --------------------------------------------------------------------------
# Approval text (what the user sees before a HIGH risk action)
# --------------------------------------------------------------------------

ACTION_TITLES = {
    "restart_app": "ری‌استارت برنامه",
    "set_env": "تغییر متغیر محیطی",
    "resize_app": "تغییر پلن",
    "deploy_new_version": "دیپلوی نسخه‌ی جدید",
}
ACTION_IMPACT = {
    "restart_app": "برنامه چند ثانیه در دسترس نیست.",
    "set_env": "برنامه بعد از تغییر ری‌استارت می‌شود.",
    "resize_app": "هزینه‌ی ماهانه تغییر می‌کند.",
    "deploy_new_version": "کد جدید جایگزین نسخه‌ی فعلی می‌شود.",
}


def describe_action(call: dict) -> dict:
    """Make a clear approval card for one HIGH risk tool call."""
    name, args = call["name"], dict(call.get("args", {}))
    card = {
        "tool_call_id": call["id"],
        "tool": name,
        "action": ACTION_TITLES.get(name, name),
        "app": args.get("app"),
        "reason": args.get("reason", ""),
        "impact": ACTION_IMPACT.get(name, ""),
        "details": {k: v for k, v in args.items() if k not in ("app", "reason")},
    }
    if name == "resize_app":
        try:
            plans = {p["plan_id"]: p for p in lt.list_plans(client())}
            current = lt.get_app_status(client(), args["app"])["plan_id"]
            old, new = plans.get(current), plans.get(args.get("plan_id"))
            if old and new:
                card["details"] = {
                    "from": f"{current} ({old['ram_gb']} GB RAM, {old['cpu_cores']} CPU) - {old['price_per_month_toman']:,} تومان در ماه",
                    "to": f"{new['plan_id']} ({new['ram_gb']} GB RAM, {new['cpu_cores']} CPU) - {new['price_per_month_toman']:,} تومان در ماه",
                    "monthly_difference_toman": f"{new['price_per_month_toman'] - old['price_per_month_toman']:+,}",
                }
        except lt.LiaraAPIError:
            pass
    return card


def audit(entry: dict) -> None:
    """Append one action to the audit log file. Environment values are masked."""
    if entry.get("tool") == "set_env" and "value" in entry.get("args", {}):
        entry["args"] = {**entry["args"], "value": "***"}
    entry["time"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with open(AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------
# Graph
# --------------------------------------------------------------------------

class State(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    steps: int                 # LLM turns since the last user message
    approved_ids: list[str]    # tool_call ids that the user approved


def system_prompt() -> str:
    limits = "\n".join(f"- {x}" for x in lt.API_LIMITS)
    return f"""You are "Liara Assistant", a technical teammate for website owners on the Liara cloud.
The user has little technical knowledge. Always answer in simple, short Persian. Explain technical words.
Write every sentence in Persian; keep only technical names (GREETING, RAM, /greet) in English.
Keep each answer short: at most about 8 lines. Use this order: what I found, the cause, what I suggest or did.
If you give options, give at most 2 and make the count in the text match the list.
The user's main app ID is "{default_app()}". Use it when the user does not name an app.

How you work:
1. Collect evidence first with LOW risk tools (get_app_status, get_logs, get_metrics, check_url). Never guess.
2. Find the probable causes. Rank them by the evidence. Say which evidence supports each cause.
3. Suggest the best fix in simple words.
4. To fix, call the HIGH risk tool with a clear "reason". The system asks the user for approval
   automatically. Do not ask for approval in text, and do not say that you did an action before it is done.
5. After a fix, call wait_seconds, then verify with check_url, get_logs or get_metrics. Report the result.
6. If the user rejects an action, accept it and suggest another way, or stop.

Rules:
- A bug in the program code (for example TypeError with a file and a line) cannot be fixed with the Liara API.
  Show the file and the line from current_errors, explain the bug simply, and suggest the code change.
  After the user fixes the code, offer deploy_new_version.
- A missing environment variable can be fixed with set_env. If you do not know the correct value, ask the user.
- High memory that grows over time is a memory leak: restart_app is a quick fix; a larger plan only delays it.
  Suggest resize_app only when normal use is near the plan limit. Show the price difference.
- Never show values of environment variables. They can be secrets.
- Use only current_errors as current problems. errors_before_last_start are history:
  do not report them as a cause and do not suggest a fix for them, unless check_url shows the problem again.
- Talk only about the problem that the user asked about. Do not add other problems unless they are serious now.
- Metrics can lag a few minutes. Say the time of the metric value if it matters. If new log warnings show
  a higher value, trust the logs.
- Domains: never state the DNS or domain status without a tool result (list_domains, check_url).
  IRNIC is only the registrar: in the IRNIC panel the user sets the domain's DNS servers (nameservers).
  DNS records and connecting the domain to the app are done on the Liara side (DNS and Domains sections).
  Say clearly that this assistant cannot change IRNIC or add a domain, and give these steps.
- Never show internal tool names (restart_app, set_env, ...) to the user. Say the action in Persian.
- If a tool returns an error, explain it simply. If the Liara API cannot do something, say it clearly.
- When an action was done in this conversation (the tool result has "action_done": true), your next answer
  must start with: what was done, and the verification result with numbers BEFORE and AFTER
  (for example: "RAM from 368 MB to 30 MB", "/greet from 500 to 200").
  Never offer or ask about an action that is already done. Then give the long-term advice.
Known limits of the Liara API:
{limits}
"""


def make_graph(llm: Any | None = None):
    """Build the LangGraph agent. 'llm' can be replaced in tests."""
    if llm is None:
        llm = ChatOpenAI(model=os.environ["BOXAPI_MODEL"],
                         base_url=os.environ["BOXAPI_BASE_URL"],
                         api_key=os.environ["BOXAPI_API_KEY"],
                         timeout=90)
    llm_with_tools = llm.bind_tools(ALL_TOOLS)

    def agent_node(state: State) -> dict:
        steps = state.get("steps", 0)
        if steps >= MAX_AGENT_STEPS:
            msg = AIMessage(content="برای این درخواست مراحل زیادی طی شد و برای ایمنی متوقف شدم. "
                                    "لطفاً درخواست را دقیق‌تر بگویید.")
            return {"messages": [msg], "steps": steps + 1}
        reply = llm_with_tools.invoke([SystemMessage(content=system_prompt())] + state["messages"])
        return {"messages": [reply], "steps": steps + 1}

    def route_after_agent(state: State) -> str:
        last = state["messages"][-1]
        return "approval" if getattr(last, "tool_calls", None) else END

    def approval_node(state: State) -> dict:
        last = state["messages"][-1]
        risky = [c for c in last.tool_calls if c["name"] in HIGH_RISK]
        if not risky:
            return {"approved_ids": []}
        # The graph stops here. The runner shows the cards and resumes with the answer.
        decision = interrupt({"type": "approval", "actions": [describe_action(c) for c in risky]})
        approved = [c["id"] for c in risky if decision.get(c["id"], decision.get("all", False))]
        return {"approved_ids": approved}

    def tools_node(state: State) -> dict:
        last = state["messages"][-1]
        approved = set(state.get("approved_ids", []))
        results = []
        for call in last.tool_calls:
            name, args = call["name"], call.get("args", {})
            risky = name in HIGH_RISK
            if risky and call["id"] not in approved:
                content = json.dumps({"ok": False, "status": "rejected_by_user",
                                      "note": "The user did not approve this action. It was not done."})
                audit({"tool": name, "args": args, "risk": lt.HIGH, "approved": False})
            elif name not in TOOLS_BY_NAME:
                content = json.dumps({"ok": False, "error": f"Unknown tool {name}"})
            else:
                content = TOOLS_BY_NAME[name].invoke(args)
                audit({"tool": name, "args": args, "risk": lt.HIGH if risky else lt.LOW,
                       "approved": True if risky else None, "result": str(content)[:500]})
                if risky:
                    # Tell the LLM clearly that the action is done and what to do next.
                    try:
                        data = json.loads(content)
                    except ValueError:
                        data = {"raw": content}
                    if data.get("ok", True):
                        data.update(action_done=True, approved_by_user=True,
                                    next_steps="Call wait_seconds, verify with tools, then report "
                                               "BEFORE and AFTER numbers. Do not offer this action again.")
                    content = json.dumps(data, ensure_ascii=False)
            results.append(ToolMessage(content=content, tool_call_id=call["id"], name=name))
        return {"messages": results, "approved_ids": []}

    graph = StateGraph(State)
    graph.add_node("agent", agent_node)
    graph.add_node("approval", approval_node)
    graph.add_node("tools", tools_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route_after_agent, {"approval": "approval", END: END})
    graph.add_edge("approval", "tools")
    graph.add_edge("tools", "agent")
    return graph.compile(checkpointer=MemorySaver())
