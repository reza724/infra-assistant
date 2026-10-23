"""
Run all demo scenarios automatically and save one transcript file for each.

Usage (from the project root, with the venv active):
    python3 run_scenarios.py                 # all scenarios except the plan change
    python3 run_scenarios.py --only S3       # one scenario
    python3 run_scenarios.py --with-resize   # also S7 (plan change, then back)

Output: scenario_outputs/<id>.txt and scenario_outputs/ALL.txt

Approvals are answered by this script (one fixed answer for each tool and scenario).
Unknown actions are REJECTED, for safety.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import requests
from langchain_core.messages import HumanMessage

from check_tools import load_env

OUT_DIR = Path("scenario_outputs")
TARGET_DIR = Path(os.environ.get("TARGET_APP_DIR", "target-app"))

BUGGY_CODE = """    const order = undefined;
    order.total; // This line throws a TypeError on purpose."""
FIXED_CODE = """    const order = { total: 0 }; // Fixed: the order object is defined now.
    return res.send(`Order total: ${order.total}`);"""


# --------------------------------------------------------------------------
# Scenario model
# --------------------------------------------------------------------------

@dataclass
class Step:
    """One step: the user says something, or the script does a setup action."""
    say: str = ""
    do: Callable[[Callable], None] | None = None
    label: str = ""


@dataclass
class Scenario:
    sid: str
    title: str
    steps: list[Step]
    approvals: dict[str, bool] = field(default_factory=dict)  # tool name -> approve?
    setup: Callable[[Callable], None] | None = None
    cleanup: Callable[[Callable], None] | None = None
    optional: bool = False


# --------------------------------------------------------------------------
# Setup helpers (they create the problem before the user asks)
# --------------------------------------------------------------------------

def app_url() -> str:
    return f"https://{os.environ['LIARA_APP_ID']}.liara.run"


def hit(path: str, times: int, out) -> None:
    """Call one path of the target app several times."""
    for i in range(times):
        try:
            r = requests.get(app_url() + path, timeout=30)
            if i == times - 1:
                out(f"  [setup] {path} x{times} -> last: {r.status_code} {r.text[:60]}")
        except requests.RequestException as exc:
            out(f"  [setup] {path} failed: {exc}")


def wait(seconds: int, out) -> None:
    out(f"  [setup] waiting {seconds}s for logs and metrics to update...")
    time.sleep(seconds)


def remove_greeting(out) -> None:
    """Make scenario S2 possible: remove GREETING so /greet gives 500."""
    import liara_tools as lt
    client = lt.LiaraClient.from_env()
    status = lt.get_app_status(client, os.environ["LIARA_APP_ID"])
    if "GREETING" in status["env_names"]:
        lt.unset_env(client, os.environ["LIARA_APP_ID"], "GREETING")
        out("  [setup] GREETING removed (app restarts)")
        wait(60, out)
    hit("/greet", 2, out)
    wait(20, out)


def fill_memory(times: int):
    def _do(out):
        hit("/leak", times, out)
        wait(40, out)
    return _do


def make_errors(out) -> None:
    hit("/error", 3, out)
    wait(30, out)


def fix_code_locally(out) -> None:
    """Simulate the developer: fix the bug in target-app/index.js (a backup is kept)."""
    index = TARGET_DIR / "index.js"
    code = index.read_text(encoding="utf-8")
    if BUGGY_CODE not in code:
        out("  [setup] index.js does not contain the bug (already fixed?)")
        return
    shutil.copy(index, TARGET_DIR / "index.js.buggy")
    index.write_text(code.replace(BUGGY_CODE, FIXED_CODE), encoding="utf-8")
    out("  [setup] The developer fixed index.js (line 27). Backup: index.js.buggy")


def restore_buggy_code(out) -> None:
    """Put the bug back in the LOCAL file, so the demo can run again later."""
    backup = TARGET_DIR / "index.js.buggy"
    if backup.exists():
        shutil.move(backup, TARGET_DIR / "index.js")
        out("  [cleanup] Local index.js has the bug again (the live app stays fixed).")


def resize_back(out) -> None:
    """After S7, go back to the small plan to save credit (direct API call, not the agent)."""
    import liara_tools as lt
    client = lt.LiaraClient.from_env()
    app = os.environ["LIARA_APP_ID"]
    if lt.get_app_status(client, app)["plan_id"] != "small-g2":
        try:
            lt.resize_app(client, app, "small-g2")
            out("  [cleanup] Plan changed back to small-g2.")
        except lt.LiaraAPIError as exc:
            out(f"  [cleanup] Could not change the plan back: {exc}. Do it in the console.")


# --------------------------------------------------------------------------
# The scenarios
# --------------------------------------------------------------------------

SCENARIOS = [
    Scenario("S1", "وضعیت کلی و پیشنهاد پلن (فقط خواندنی)", [
        Step(say="سلام، وضعیت سایتم چطوره؟"),
        Step(say="به نظرت پلن فعلی برای سایتم مناسبه یا باید عوضش کنم؟"),
    ]),
    Scenario("S2", "خطای ۵۰۰ به‌خاطر نبود متغیر محیطی (تنظیم env با تأیید)", [
        Step(say="سلام، صفحه‌ی greet سایتم خطا میده. مشکل چیه؟"),
        Step(say="متن «سلام، به سایت من خوش آمدید» را بگذار"),
    ], approvals={"set_env": True}, setup=remove_greeting),
    Scenario("S4", "کاربر اقدام حساس را رد می‌کند", [
        Step(say="سایتم کند شده، چک کن ببین مشکل از کجاست"),
        Step(say="ری‌استارت رو انجام بده"),
    ], approvals={"restart_app": False}, setup=fill_memory(12)),
    Scenario("S3", "کندی سایت و نشت حافظه (ری‌استارت با تأیید و بررسی قبل/بعد)", [
        Step(say="سایتم هنوز کنده، مشکل رو حل کن"),
        Step(say="باشه، ری‌استارت کن"),
    ], approvals={"restart_app": True}, setup=fill_memory(5)),
    Scenario("S5", "باگ کد (تشخیص فایل و خط، رفع توسط توسعه‌دهنده، دیپلوی با تأیید)", [
        Step(say="صفحه‌ی error سایتم خطای ۵۰۰ میده، علتش چیه؟"),
        Step(do=fix_code_locally, label="developer fixes the code"),
        Step(say="کد رو طبق پیشنهادت درست کردم. نسخه‌ی جدید رو دیپلوی کن و نتیجه رو چک کن."),
    ], approvals={"deploy_new_version": True}, setup=make_errors, cleanup=restore_buggy_code),
    Scenario("S6", "درخواست خارج از توان API (دامنه در ایرنیک)", [
        Step(say="دامنه‌ی mysite.ir رو که از ایرنیک خریدم برام روی سایت تنظیم کن"),
    ]),
    Scenario("S7", "ارتقای پلن با نمایش اختلاف قیمت (و برگشت به پلن قبلی)", [
        Step(say="قراره ترافیک سایتم دو برابر بشه، پلن رو یک پله ارتقا بده"),
    ], approvals={"resize_app": True}, cleanup=resize_back, optional=True),
]


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------

def run_scenario(graph, sc: Scenario, all_file) -> None:
    from run_cli import run_turn, show_card

    path = OUT_DIR / f"{sc.sid}.txt"
    with open(path, "w", encoding="utf-8") as f:
        def out(line: str = "") -> None:
            print(line)
            f.write(line + "\n")
            all_file.write(line + "\n")
            f.flush()
            all_file.flush()

        def auto_approve(payload: dict, out_fn) -> dict:
            decision = {}
            for card in payload["actions"]:
                show_card(card, out_fn)
                ok = sc.approvals.get(card.get("tool", ""), False)
                decision[card["tool_call_id"]] = ok
                out_fn(f"   [scenario script answer] {'y ✅ تأیید شد.' if ok else 'n ❌ رد شد.'}")
            out_fn("─" * 60)
            return decision

        out("=" * 70)
        out(f"{sc.sid}: {sc.title}")
        out(f"time: {datetime.now().isoformat(timespec='seconds')}")
        out("=" * 70)
        try:
            if sc.setup:
                sc.setup(out)
            config = {"configurable": {"thread_id": str(uuid.uuid4())}, "recursion_limit": 60}
            for step in sc.steps:
                if step.do:
                    step.do(out)
                    continue
                out(f"\n👤 شما: {step.say}")
                start = time.time()
                run_turn(graph, config, {"messages": [HumanMessage(content=step.say)], "steps": 0},
                         out=out, approve=auto_approve)
                out(f"  [time] {round(time.time() - start)}s")
        except Exception as exc:  # noqa: BLE001 - save the error in the transcript
            out(f"\n!!! SCENARIO ERROR: {type(exc).__name__}: {exc}")
        finally:
            if sc.cleanup:
                try:
                    sc.cleanup(out)
                except Exception as exc:  # noqa: BLE001
                    out(f"  [cleanup] failed: {exc}")
        out("")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Liara assistant demo scenarios.")
    parser.add_argument("--only", help="run only this scenario ID, for example S3")
    parser.add_argument("--with-resize", action="store_true", help="also run S7 (plan change)")
    args = parser.parse_args()

    load_env()
    from agent import make_graph  # import after .env is loaded

    chosen = [s for s in SCENARIOS
              if (args.only and s.sid == args.only.upper())
              or (not args.only and (not s.optional or args.with_resize))]
    if not chosen:
        print("No scenario selected.")
        return 1

    OUT_DIR.mkdir(exist_ok=True)
    graph = make_graph()
    mode = "a" if args.only else "w"
    with open(OUT_DIR / "ALL.txt", mode, encoding="utf-8") as all_file:
        for sc in chosen:
            run_scenario(graph, sc, all_file)
    print(f"\nDone. Transcripts are in {OUT_DIR}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
