"""
Built-in daily scheduler for environments without cron (Docker `restart: always`, Railway, Fly, a bare VPS).
Sleeps until DIGEST_TIME in TZ, runs, repeats. Catches up if the process was down at the scheduled time
and today's digest is missing.
"""
from __future__ import annotations

import datetime as dt
import logging
import signal
import time
import zoneinfo

from . import config as C
from . import pipeline, store

log = logging.getLogger("jobs_worker.scheduler")
_stop = False


def _handle(sig, _frame):
    global _stop
    _stop = True
    log.info("signal %s received, stopping after current sleep", sig)


def _next_fire(now: dt.datetime) -> dt.datetime:
    hh, mm = (int(x) for x in C.DIGEST_TIME.split(":"))
    fire = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return fire if fire > now else fire + dt.timedelta(days=1)


def _today_done(tz) -> bool:
    con = store.connect()
    try:
        return store.last_digest_day(con) == dt.datetime.now(tz).date().isoformat()
    finally:
        con.close()


def serve():
    tz = zoneinfo.ZoneInfo(C.TZ)
    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)
    now = dt.datetime.now(tz)
    hh, mm = (int(x) for x in C.DIGEST_TIME.split(":"))
    missed = now.time() >= dt.time(hh, mm) and not _today_done(tz)
    if C.RUN_ON_START or missed:
        log.info("running at startup (%s)", "RUN_ON_START" if C.RUN_ON_START else "missed today's slot")
        _safe_run(dt.datetime.now(tz).date())
    while not _stop:
        now = dt.datetime.now(tz)
        fire = _next_fire(now)
        log.info("next run at %s", fire.isoformat(timespec="minutes"))
        while not _stop and dt.datetime.now(tz) < fire:
            time.sleep(min(5, max(0.5, (fire - dt.datetime.now(tz)).total_seconds())))
        if _stop:
            break
        _safe_run(fire.date())


def _safe_run(day):
    for attempt in range(3):
        try:
            pipeline.run_once(day)
            return
        except Exception:  # noqa: BLE001
            log.exception("attempt %d failed", attempt + 1)
            time.sleep(300 * (attempt + 1))
