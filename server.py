"""
Phase 5: HTTP API for the web interface.

Endpoints:
  POST /api/chat      {thread_id, message}    -> event stream (SSE)
  POST /api/approve   {thread_id, decisions}  -> event stream (SSE), continues after approval
  GET  /api/overview                          -> app status + metrics (side panel)
  GET  /api/audit                             -> last actions from audit_log.jsonl

Event types in the stream (one JSON object per "data:" line):
  tool_start  {id, name, label, risk}
  tool_result {id, name, ok, data}
  assistant   {text}
  approval    {actions: [...]}
  error       {message}
  done        {}

Run:  uvicorn server:app --port 8000
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Iterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from langgraph.types import Command
from pydantic import BaseModel

from check_tools import load_env

load_env()

import agent  # noqa: E402  (import after .env is loaded)
import liara_tools as lt  # noqa: E402
from run_cli import TOOL_LABELS  # noqa: E402

app = FastAPI(title="Liara Assistant API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("WEB_ORIGINS", "http://localhost:3000").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

GRAPH = agent.make_graph()
_locks: dict[str, threading.Lock] = {}  # One run at a time for each conversation.


class ChatIn(BaseModel):
    thread_id: str
    message: str


class ApproveIn(BaseModel):
    thread_id: str
    decisions: dict[str, bool]


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _parse(content: str):
    try:
        return json.loads(content)
    except (TypeError, ValueError):
        return {"raw": str(content)}


def stream_graph(thread_id: str, graph_input) -> Iterator[str]:
    """Run the graph and turn its updates into UI events."""
    lock = _locks.setdefault(thread_id, threading.Lock())
    if not lock.acquire(blocking=False):
        yield _sse({"type": "error", "message": "یک درخواست دیگر در همین گفت‌وگو در حال اجراست."})
        yield _sse({"type": "done"})
        return
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 60}
    try:
        for update in GRAPH.stream(graph_input, config, stream_mode="updates"):
            if "__interrupt__" in update:
                payload = update["__interrupt__"][0].value
                yield _sse({"type": "approval", "actions": payload["actions"]})
                continue
            for node, data in update.items():
                if not data:
                    continue
                for msg in data.get("messages", []):
                    if node == "agent" and getattr(msg, "tool_calls", None):
                        if msg.content:
                            yield _sse({"type": "assistant", "text": msg.content})
                        for call in msg.tool_calls:
                            yield _sse({"type": "tool_start", "id": call["id"], "name": call["name"],
                                        "label": TOOL_LABELS.get(call["name"], call["name"]),
                                        "risk": "HIGH" if call["name"] in agent.HIGH_RISK else "LOW"})
                    elif node == "tools":
                        data_obj = _parse(msg.content)
                        ok = not (isinstance(data_obj, dict) and data_obj.get("ok") is False)
                        yield _sse({"type": "tool_result", "id": msg.tool_call_id, "name": msg.name,
                                    "ok": ok, "data": data_obj})
                    elif node == "agent" and msg.content:
                        yield _sse({"type": "assistant", "text": msg.content})
    except Exception as exc:  # noqa: BLE001 - show every error in the UI
        yield _sse({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
    finally:
        lock.release()
    yield _sse({"type": "done"})


@app.post("/api/chat")
def chat(body: ChatIn) -> StreamingResponse:
    graph_input = {"messages": [HumanMessage(content=body.message)], "steps": 0}
    return StreamingResponse(stream_graph(body.thread_id, graph_input), media_type="text/event-stream")


@app.post("/api/approve")
def approve(body: ApproveIn) -> StreamingResponse:
    return StreamingResponse(stream_graph(body.thread_id, Command(resume=body.decisions)),
                             media_type="text/event-stream")


@app.get("/api/overview")
def overview() -> dict:
    """Data for the side panel. Read-only calls only."""
    app_id = agent.default_app()
    result: dict = {"app": app_id, "url": f"https://{app_id}.liara.run"}
    for key, func in (("status", lt.get_app_status), ("metrics", lt.get_metrics)):
        try:
            result[key] = func(agent.client(), app_id)
        except lt.LiaraAPIError as exc:
            result[key] = {"error": exc.message}
    return result


@app.get("/api/audit")
def audit(limit: int = 15) -> list[dict]:
    path = Path(agent.AUDIT_LOG)
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()[-limit:]
    entries = [json.loads(line) for line in lines if line.strip()]
    for e in entries:
        e["label"] = TOOL_LABELS.get(e.get("tool", ""), e.get("tool", ""))
        e.pop("result", None)
    return list(reversed(entries))


@app.get("/api/limits")
def limits() -> list[str]:
    return lt.API_LIMITS_FA
