"""Push the digest to wherever the community lives. All channels optional; unset ones are skipped."""
from __future__ import annotations

import json
import logging
import urllib.request

from . import config as C

log = logging.getLogger("jobs_worker.notify")


def _post(url, body: bytes, content_type="application/json"):
    req = urllib.request.Request(url, data=body, headers={"Content-Type": content_type, "User-Agent": "jobs-worker/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status


def _chunks(text: str, limit: int):
    """Split on blank lines so a job entry never gets cut in half."""
    out, cur = [], ""
    for block in text.split("\n\n"):
        if len(cur) + len(block) + 2 > limit and cur:
            out.append(cur)
            cur = block
        else:
            cur = f"{cur}\n\n{block}" if cur else block
    if cur:
        out.append(cur)
    return out


def _plain(md: str) -> str:
    return md.replace("**", "").replace("## ", "").replace("# ", "").replace("_", "")


def telegram(md):
    if not (C.TELEGRAM_BOT_TOKEN and C.TELEGRAM_CHAT_ID):
        return
    url = f"https://api.telegram.org/bot{C.TELEGRAM_BOT_TOKEN}/sendMessage"
    for chunk in _chunks(_plain(md), 3900):
        _post(url, json.dumps({"chat_id": C.TELEGRAM_CHAT_ID, "text": chunk, "disable_web_page_preview": True}).encode())


def discord(md):
    if not C.DISCORD_WEBHOOK_URL:
        return
    for chunk in _chunks(md, 1900):
        _post(C.DISCORD_WEBHOOK_URL, json.dumps({"content": chunk}).encode())


def slack(md):
    if not C.SLACK_WEBHOOK_URL:
        return
    for chunk in _chunks(md.replace("**", "*"), 3500):
        _post(C.SLACK_WEBHOOK_URL, json.dumps({"text": chunk}).encode())


def generic(payload):
    if not C.GENERIC_WEBHOOK_URL:
        return
    _post(C.GENERIC_WEBHOOK_URL, json.dumps(payload, default=str).encode())


def send_digest(md: str, payload: dict):
    for fn, arg in ((telegram, md), (discord, md), (slack, md), (generic, payload)):
        try:
            fn(arg)
        except Exception as e:  # noqa: BLE001
            log.warning("%s delivery failed: %s", fn.__name__, e)
