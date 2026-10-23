"""
Record the demo video of the real product (real Liara app, real agent).

Each scene is recorded as a separate clip. The setup work (creating the problem)
runs between scenes and is NOT recorded. At the end, ffmpeg joins the clips into
one compressed MP4 with Persian captions burned in by the browser overlay.

Before you run it:
  1. ./start_web.sh is running (API on :8000, web on :3000)
  2. pip install playwright && playwright install chromium
  3. sudo apt install ffmpeg

Run from the project root:
  python3 demo/record_demo.py              # all scenes
  python3 demo/record_demo.py --only 3     # one scene (for a retake)
  python3 demo/record_demo.py --join-only  # only join the existing clips
Output: demo/output/demo.mp4
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.chdir(Path(__file__).resolve().parent.parent)

from playwright.sync_api import Page, sync_playwright  # noqa: E402

from check_tools import load_env  # noqa: E402

WEB = os.environ.get("DEMO_WEB_URL", "http://localhost:3000")
OUT = Path("demo/output")
CLIPS = OUT / "clips"
SIZE = {"width": 1280, "height": 800}

# --------------------------------------------------------------------------
# Overlay: captions at the bottom and full-screen title slides
# --------------------------------------------------------------------------

OVERLAY_JS = """
() => {
  if (window.__cap) return;
  const cap = document.createElement('div');
  cap.style.cssText = 'position:fixed;bottom:18px;left:50%;transform:translateX(-50%);max-width:88%;' +
    'background:rgba(15,23,42,.88);color:#fff;font:500 19px Vazirmatn,sans-serif;padding:10px 22px;' +
    'border-radius:12px;z-index:99999;direction:rtl;text-align:center;line-height:1.9;display:none';
  document.body.appendChild(cap);
  const slide = document.createElement('div');
  slide.style.cssText = 'position:fixed;inset:0;background:linear-gradient(135deg,#0f766e,#0f172a);color:#fff;' +
    'z-index:99998;display:none;align-items:center;justify-content:center;direction:rtl;font-family:Vazirmatn,sans-serif';
  document.body.appendChild(slide);
  window.__cap = (t) => { cap.textContent = t; cap.style.display = t ? 'block' : 'none'; };
  window.__slide = (h) => { slide.innerHTML = h; slide.style.display = h ? 'flex' : 'none'; };
}
"""


def caption(page: Page, text: str, hold_ms: int = 0) -> None:
    page.evaluate("t => window.__cap(t)", text)
    if hold_ms:
        page.wait_for_timeout(hold_ms)


def slide(page: Page, title: str, lines: list[str], hold_ms: int) -> None:
    items = "".join(f"<li style='margin:10px 0'>{x}</li>" for x in lines)
    html = (f"<div style='max-width:900px;padding:40px'><h1 style='font-size:40px;margin:0 0 24px'>{title}</h1>"
            f"<ul style='font-size:24px;line-height:1.8;padding-right:24px'>{items}</ul></div>")
    page.evaluate("h => window.__slide(h)", html)
    page.wait_for_timeout(hold_ms)
    page.evaluate("() => window.__slide('')")


IDLE_JS = """() => {
  const t = document.querySelector('textarea');
  const card = [...document.querySelectorAll('button')].some(b => b.textContent.includes('تأیید و اجرا'));
  return (t && !t.disabled) || card;
}"""


def wait_idle(page: Page) -> None:
    """Wait until the agent finished, or until it waits for an approval."""
    page.wait_for_timeout(800)
    page.wait_for_function(IDLE_JS, timeout=420_000)
    page.wait_for_timeout(1500)


def approval_pending(page: Page) -> bool:
    return page.get_by_role("button", name="تأیید و اجرا").count() > 0


def ask(page: Page, text: str, cap: str = "") -> None:
    """Type a message like a user, send it, and wait until the agent is idle."""
    if cap:
        caption(page, cap)
    box = page.locator("textarea")
    box.click()
    box.type(text, delay=35)
    page.keyboard.press("Enter")
    wait_idle(page)


def answer_approval(page: Page, approve: bool, cap: str) -> None:
    """Wait for the approval card, show it for a moment, then click approve or reject."""
    page.get_by_role("button", name="تأیید و اجرا").last.wait_for(timeout=300_000)
    caption(page, cap, 4500)
    page.get_by_role("button", name="تأیید و اجرا" if approve else "رد").last.click()
    wait_idle(page)


def open_app(page: Page) -> None:
    page.goto(WEB, wait_until="networkidle")
    page.evaluate(OVERLAY_JS)
    page.wait_for_timeout(1200)


# --------------------------------------------------------------------------
# Scenes. Each scene: (setup function or None, play function, speed)
# --------------------------------------------------------------------------

def scene_intro(page: Page) -> None:
    open_app(page)
    slide(page, "دستیار هوشمند زیرساخت لیارا", [
        "همکار فنی صاحب سایت: دیپلوی، پایش و عیب‌یابی روی لیارا",
        "کاربر مشکل را به زبان ساده می‌گوید؛ دستیار با API واقعی لیارا شواهد جمع می‌کند",
        "علت را پیدا می‌کند، راه رفع را پیشنهاد می‌دهد و فقط با تأیید کاربر اقدام می‌کند",
        "بعد از هر اقدام، نتیجه را با عدد قبل و بعد بررسی می‌کند",
    ], 9000)
    slide(page, "چه چیزی می‌بینید؟", [
        "۱. بررسی وضعیت و پیشنهاد پلن با قیمت",
        "۲. خطای ۵۰۰ به‌خاطر متغیر محیطی ← رفع با تأیید",
        "۳. کندی سایت و نشت حافظه ← رد و تأیید اقدام حساس",
        "۴. باگ کد ← تشخیص فایل و خط ← دیپلوی نسخه‌ی جدید",
        "۵. درخواست خارج از توان API ← اعلام صادقانه‌ی محدودیت",
    ], 9000)
    caption(page, "رابط وب: چت در وسط، وضعیت زنده‌ی برنامه و تاریخچه‌ی اقدامات در کنار", 5000)
    caption(page, "کارهای خواندنی خودکار هستند؛ کارهای حساس فقط با تأیید شما", 4500)


def scene_status(page: Page) -> None:
    open_app(page)
    ask(page, "سلام، وضعیت سایتم چطوره؟",
        "سناریو ۱: کاربر با کمترین دانش فنی می‌پرسد. دستیار خودکار وضعیت، لاگ، متریک و آدرس سایت را بررسی می‌کند")
    caption(page, "هر ابزار یک کارت اختصاصی دارد (Generative UI): وضعیت، مصرف RAM و CPU، لاگ‌ها و تست آدرس", 5000)
    ask(page, "به نظرت پلن فعلی برای سایتم مناسبه یا باید عوضش کنم؟",
        "پیشنهاد پلن بر اساس مصرف واقعی و فهرست پلن‌های لیارا، همراه با اختلاف قیمت ماهانه")
    caption(page, "دستیار تغییر بی‌دلیل پلن را پیشنهاد نمی‌دهد و هزینه را شفاف نشان می‌دهد", 4500)


def setup_env(out=print) -> None:
    from run_scenarios import remove_greeting
    remove_greeting(out)


def scene_env(page: Page) -> None:
    open_app(page)
    ask(page, "سلام، صفحه‌ی greet سایتم خطا میده. مشکل چیه؟",
        "سناریو ۲: خطای ۵۰۰. دستیار لاگ را می‌خواند و آدرس را تست می‌کند تا علت را با شواهد پیدا کند")
    caption(page, "علت: متغیر محیطی GREETING تعریف نشده است. دستیار مقدار را از کاربر می‌پرسد و حدس نمی‌زند", 5000)
    if not approval_pending(page):
        ask(page, "متن «سلام، به سایت من خوش آمدید» را بگذار")
    answer_approval(page, True, "تغییر متغیر محیطی برنامه را ری‌استارت می‌کند، پس کار حساس است: کارت تأیید با دلیل و اثر")
    caption(page, "بعد از تأیید: اجرا، صبر، تست دوباره‌ی آدرس. نتیجه: کد پاسخ از ۵۰۰ به ۲۰۰", 6000)


def setup_leak(out=print) -> None:
    from run_scenarios import fill_memory
    fill_memory(17)(out)


def scene_leak(page: Page) -> None:
    open_app(page)
    ask(page, "سایتم کند شده، چک کن ببین مشکل از کجاست",
        "سناریو ۳: کندی سایت. دستیار مصرف حافظه و هشدارهای لاگ را کنار هم می‌گذارد")
    caption(page, "تشخیص: نشت حافظه. ری‌استارت راه سریع است؛ ارتقای پلن فقط مشکل را عقب می‌اندازد", 5000)
    if not approval_pending(page):
        ask(page, "ری‌استارت کن")
    answer_approval(page, False, "این بار کاربر اقدام حساس را رد می‌کند تا ببینیم دستیار چه می‌کند")
    caption(page, "دستیار رد شدن را می‌پذیرد، کاری انجام نمی‌دهد و راه دیگری پیشنهاد می‌کند", 4500)
    if not approval_pending(page):
        ask(page, "باشه، حالا ری‌استارت کن")
    answer_approval(page, True, "حالا کاربر تأیید می‌کند")
    caption(page, "کارت قبل و بعد: RAM با عدد واقعی بررسی می‌شود. همه‌ی اقدامات در تاریخچه‌ی کنار صفحه ثبت شده‌اند", 7000)


def setup_bug(out=print) -> None:
    """Deploy the buggy version (off camera), then create the errors."""
    import liara_tools as lt
    from run_scenarios import make_errors
    client = lt.LiaraClient.from_env()
    out("  [setup] deploying the buggy version (about 2 minutes)...")
    print(lt.deploy_source(client, os.environ["LIARA_APP_ID"], "target-app"))
    make_errors(out)


def scene_bug(page: Page) -> None:
    from run_scenarios import fix_code_locally, restore_buggy_code
    open_app(page)
    try:
        ask(page, "صفحه‌ی error سایتم خطای ۵۰۰ میده، علتش چیه؟",
            "سناریو ۴: باگ در کد. دستیار از stack trace لاگ، فایل و خط خطا را پیدا می‌کند")
        caption(page, "باگ کد با API لیارا رفع نمی‌شود؛ دستیار علت و تغییر لازم را ساده توضیح می‌دهد", 5000)
        fix_code_locally(print)
        caption(page, "توسعه‌دهنده کد را اصلاح کرد. حالا دیپلوی نسخه‌ی جدید با API لیارا", 3000)
        ask(page, "کد رو طبق پیشنهادت درست کردم. نسخه‌ی جدید رو دیپلوی کن و نتیجه رو چک کن.")
        answer_approval(page, True, "دیپلوی هم کار حساس است: کد جدید جایگزین نسخه‌ی فعلی می‌شود")
        caption(page, "آپلود سورس، ساخت نسخه، صبر تا READY و تست دوباره. نتیجه: /error از ۵۰۰ به ۲۰۰ (⏩ با سرعت بیشتر)", 6000)
    finally:
        restore_buggy_code(print)


def scene_limits(page: Page) -> None:
    open_app(page)
    ask(page, "دامنه‌ی mysite.ir رو که از ایرنیک خریدم برام روی سایت تنظیم کن",
        "سناریو ۵: درخواستی که از API لیارا برنمی‌آید")
    caption(page, "دستیار اول وضعیت دامنه را با API می‌خواند، حدس نمی‌زند و محدودیت را روشن می‌گوید", 5500)
    page.get_by_text("محدودیت‌های API لیارا").click()
    caption(page, "فهرست محدودیت‌های API در رابط هم نمایش داده می‌شود", 4000)


def scene_outro(page: Page) -> None:
    open_app(page)
    slide(page, "خلاصه", [
        "اتصال واقعی به API لیارا: وضعیت، لاگ، متریک، پلن، env، ری‌استارت، دیپلوی",
        "عیب‌یابی با شواهد: علت‌ها رتبه‌بندی می‌شوند و نتیجه‌ی رفع بررسی می‌شود",
        "Human-in-the-Loop: کارهای حساس با کارت تأیید؛ کارهای خواندنی خودکار",
        "امنیت: لاگ همه‌ی اقدامات، مخفی ماندن مقدار env، سقف دور برای ایجنت",
        "کد و مستندات (معماری، اتصال API، محدودیت‌ها): در مخزن گیت‌هاب",
    ], 11000)


SCENES = [
    # (number, name, setup, play, speed)
    (1, "intro", None, scene_intro, 1.0),
    (2, "status", None, scene_status, 1.3),
    (3, "env", setup_env, scene_env, 1.3),
    (4, "leak", setup_leak, scene_leak, 1.3),
    (5, "bug", setup_bug, scene_bug, 1.8),
    (6, "limits", None, scene_limits, 1.3),
    (7, "outro", None, scene_outro, 1.0),
]


# --------------------------------------------------------------------------
# Recording and joining
# --------------------------------------------------------------------------

def record(number: int, name: str, play) -> Path:
    tmp = CLIPS / f"tmp_{number}"
    shutil.rmtree(tmp, ignore_errors=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport=SIZE, record_video_dir=str(tmp), record_video_size=SIZE)
        page = context.new_page()
        try:
            play(page)
        finally:
            video = page.video
            context.close()
            browser.close()
        src = Path(video.path())
    dst = CLIPS / f"{number:02d}_{name}.webm"
    shutil.move(src, dst)
    shutil.rmtree(tmp, ignore_errors=True)
    return dst


def join(speeds: dict[str, float]) -> Path:
    """Speed up and encode each clip, then join them into one MP4."""
    parts = []
    for clip in sorted(CLIPS.glob("*.webm")):
        name = clip.stem.split("_", 1)[1]
        speed = speeds.get(name, 1.0)
        mp4 = clip.with_suffix(".mp4")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(clip),
                        "-vf", f"setpts=PTS/{speed},fps=25,scale=1280:-2", "-an",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p",
                        str(mp4)], check=True)
        parts.append(mp4)
    listing = CLIPS / "list.txt"
    listing.write_text("".join(f"file '{p.resolve()}'\n" for p in parts), encoding="utf-8")
    final = OUT / "demo.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                    "-c", "copy", "-movflags", "+faststart", str(final)], check=True)
    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(final)],
                         capture_output=True, text=True).stdout.strip()
    size_mb = final.stat().st_size / 1024 / 1024
    print(f"\nVideo: {final}  duration: {float(dur or 0) / 60:.1f} min  size: {size_mb:.1f} MB")
    return final


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", type=int, help="record only this scene number")
    parser.add_argument("--join-only", action="store_true", help="only join the existing clips")
    args = parser.parse_args()
    load_env()
    CLIPS.mkdir(parents=True, exist_ok=True)
    speeds = {name: speed for _, name, _, _, speed in SCENES}

    if not args.join_only:
        for number, name, setup, play, _ in SCENES:
            if args.only and number != args.only:
                continue
            print(f"\n=== Scene {number}: {name} ===")
            if setup:
                print("  setup (not recorded)...")
                setup()
            print("  recording...")
            print("  saved:", record(number, name, play))
    if shutil.which("ffmpeg"):
        join(speeds)
    else:
        print("ffmpeg is not installed: sudo apt install ffmpeg, then run with --join-only")
    return 0


if __name__ == "__main__":
    sys.exit(main())
