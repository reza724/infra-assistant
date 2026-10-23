"""
Phase 3 runner: chat with the agent in the terminal.

Run from the project root:  python3 run_cli.py
Type 'exit' to stop.
"""

import uuid

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from check_tools import load_env

# Short Persian labels that show the user what the agent is doing now.
TOOL_LABELS = {
    "get_app_status": "بررسی وضعیت برنامه",
    "get_logs": "خواندن لاگ‌ها",
    "get_metrics": "بررسی مصرف CPU و RAM",
    "list_plans": "دریافت فهرست پلن‌ها",
    "list_releases": "بررسی دیپلوی‌های اخیر",
    "list_domains": "بررسی دامنه‌ها",
    "check_url": "تست آدرس سایت",
    "wait_seconds": "صبر برای اعمال تغییر",
    "restart_app": "ری‌استارت برنامه",
    "set_env": "تغییر متغیر محیطی",
    "resize_app": "تغییر پلن",
    "deploy_new_version": "دیپلوی نسخه‌ی جدید",
}


def show_card(card: dict, out=print) -> None:
    """Print one approval card."""
    out("\n" + "─" * 60)
    out(f"🙋 نیاز به تأیید شما: {card['action']}  (برنامه: {card['app']})")
    if card["reason"]:
        out(f"   دلیل: {card['reason']}")
    out(f"   اثر: {card['impact']}")
    for key, value in card["details"].items():
        out(f"   {key}: {value}")


def ask_approval(payload: dict, out=print) -> dict:
    """Show the approval cards and return the user's decision for each action."""
    decision = {}
    for card in payload["actions"]:
        show_card(card, out)
        answer = input("   تأیید می‌کنید؟ (y = بله / n = خیر): ").strip().lower()
        decision[card["tool_call_id"]] = answer in ("y", "yes", "بله", "ب")
        out("   ✅ تأیید شد." if decision[card["tool_call_id"]] else "   ❌ رد شد.")
    out("─" * 60)
    return decision


def run_turn(graph, config: dict, graph_input, out=print, approve=ask_approval) -> str:
    """Run the graph until it ends. Show progress. Return the last assistant answer.

    'out' prints a line; 'approve' returns the approval decision. Both can be replaced (scenario tests).
    """
    last_answer = ""
    while True:
        interrupted = None
        for update in graph.stream(graph_input, config, stream_mode="updates"):
            if "__interrupt__" in update:
                interrupted = update["__interrupt__"][0].value
                continue
            for node, data in update.items():
                if not data:
                    continue
                for msg in data.get("messages", []):
                    if node == "agent" and getattr(msg, "tool_calls", None):
                        for call in msg.tool_calls:
                            out(f"  ⏳ {TOOL_LABELS.get(call['name'], call['name'])}...")
                    elif node == "tools":
                        status = "❌" if '"ok": false' in str(msg.content).lower() else "✔"
                        out(f"  {status} {TOOL_LABELS.get(msg.name, msg.name)}")
                    elif node == "agent" and msg.content:
                        last_answer = msg.content
                        out(f"\n🤖 دستیار:\n{msg.content}\n")
        if interrupted is None:
            return last_answer
        graph_input = Command(resume=approve(interrupted, out))


def main() -> None:
    load_env()
    from agent import make_graph  # import after .env is loaded

    graph = make_graph()
    config = {"configurable": {"thread_id": str(uuid.uuid4())}, "recursion_limit": 60}
    print("دستیار لیارا آماده است. درخواست خود را بنویسید (برای خروج: exit)\n")
    while True:
        text = input("👤 شما: ").strip()
        if text.lower() in ("exit", "quit", "خروج"):
            break
        if text:
            run_turn(graph, config, {"messages": [HumanMessage(content=text)], "steps": 0})


if __name__ == "__main__":
    main()
