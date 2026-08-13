"""
Alert dispatch.

Two sinks, both optional and independent:
  - GitHub step summary + issue comment   (zero setup, uses the Actions token)
  - Telegram                              (only if TELEGRAM_TOKEN/CHAT_ID set)

Silence is the default when nothing new fired: seven runs a day should not
produce seven notifications saying nothing happened.
"""
import json
import os
import sys

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LATEST = os.path.join(ROOT, "data", "latest.json")


def render(rep, edge_only=True):
    new = rep.get("new", [])
    if edge_only:
        new = [n for n in new if n.get("verdict") == "EDGE"]
    if not new:
        return None
    prov = " *(provisional — session still open)*" if rep.get("provisional") else ""
    lines = [f"### {len(new)} new signal(s) · {rep['as_of']}{prov}", ""]
    by = {}
    for n in new:
        by.setdefault(n["screen"], []).append(n)
    for screen, hits in by.items():
        e = hits[0].get("edge")
        lines.append(f"**{screen}** — measured edge {e:+.2f}% over 6 months")
        lines.append("")
        lines.append("| Symbol | Close ₹ | RSI | 1y | From 52wH | ₹cr/day | Sector |")
        lines.append("|---|--:|--:|--:|--:|--:|---|")
        for h in sorted(hits, key=lambda x: -(x["turnover_cr"] or 0)):
            lines.append(
                f"| `{h['symbol']}` | {h['close']:,} | {h['rsi']} | "
                f"{h['ret1y'] if h['ret1y'] is not None else '—'}% | "
                f"{h['from_52wh']}% | {h['turnover_cr']} | {h['sector'] or '—'} |")
        lines.append("")
    lines.append(
        "> Base rate for any liquid NSE stock: **73.9%** chance of touching "
        "+10% within 6 months, median **23 sessions**. These screens shift that "
        "to ~77%. Historical base rates, not forecasts — and measured across a "
        "period that rose in 9 of 12 years.")
    return "\n".join(lines)


def to_step_summary(md):
    p = os.environ.get("GITHUB_STEP_SUMMARY")
    if p and md:
        with open(p, "a", encoding="utf-8") as f:
            f.write(md + "\n")


def to_telegram(md):
    tok, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (tok and chat and md):
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{tok}/sendMessage",
            json={"chat_id": chat, "text": md, "parse_mode": "Markdown",
                  "disable_web_page_preview": True}, timeout=20)
        return r.status_code == 200
    except Exception as e:
        print(f"telegram failed: {type(e).__name__}")
        return False


def to_issue(md):
    """Comment on the tracking issue labelled `screener-alerts`."""
    tok = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    num = os.environ.get("ALERT_ISSUE_NUMBER")
    if not (tok and repo and num and md):
        return False
    try:
        r = requests.post(
            f"https://api.github.com/repos/{repo}/issues/{num}/comments",
            headers={"Authorization": f"Bearer {tok}",
                     "Accept": "application/vnd.github+json"},
            json={"body": md}, timeout=20)
        return r.status_code == 201
    except Exception as e:
        print(f"issue comment failed: {type(e).__name__}")
        return False


if __name__ == "__main__":
    if not os.path.exists(LATEST):
        print("no latest.json; nothing to notify")
        sys.exit(0)
    with open(LATEST) as f:
        rep = json.load(f)
    edge_only = os.environ.get("EDGE_ONLY", "1") != "0"
    md = render(rep, edge_only)
    if not md:
        print("no new signals — staying quiet")
        sys.exit(0)
    print(md)
    to_step_summary(md)
    print(f"telegram={to_telegram(md)} issue={to_issue(md)}")
