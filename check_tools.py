"""
Phase 2 test: run all READ-ONLY (LOW risk) tools against the real Liara app.
This script does not change anything on Liara.

Run from the project root:  python3 check_tools.py
"""

import json
import os
import sys
from pathlib import Path

from liara_tools import (LiaraAPIError, LiaraClient, get_app_status, get_logs,
                         get_metrics, list_plans, list_releases)


def load_env(path: str = ".env") -> None:
    """Load KEY=VALUE lines from .env into os.environ (no extra package needed)."""
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip().replace("\r", "")
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def show(title: str, func, *args, **kwargs) -> None:
    """Run one tool and print its result as short JSON."""
    print(f"\n=== {title} ===")
    try:
        result = func(*args, **kwargs)
        text = json.dumps(result, ensure_ascii=False, indent=2)
        print(text[:1500] + ("\n... (cut)" if len(text) > 1500 else ""))
    except LiaraAPIError as exc:
        print(f"FAILED: {exc}")


def main() -> int:
    load_env()
    app = os.environ.get("LIARA_APP_ID", "")
    if not app:
        print("LIARA_APP_ID is missing in .env")
        return 1

    client = LiaraClient.from_env()
    show("1. App status", get_app_status, client, app)
    show("2. Logs: errors only, last 3 hours", get_logs, client, app, minutes=180, errors_only=True)
    show("3. Metrics", get_metrics, client, app)
    show("4. Plans", list_plans, client)
    show("5. Releases", list_releases, client, app, count=3)
    return 0


if __name__ == "__main__":
    sys.exit(main())
