"""
python -m jobs_worker run       one shot (for cron / launchd / GitHub Actions)
python -m jobs_worker serve     long-running daily scheduler (for Docker / systemd)
python -m jobs_worker probe     per-source health, no writes
python -m jobs_worker show      print latest digest from the DB
python -m jobs_worker stats     run history
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys

from . import config as C


def _logging():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout)])


def cmd_run(a):
    from . import pipeline
    today = dt.date.fromisoformat(a.date) if a.date else dt.date.today()
    kw = {}
    if a.mnc_days is not None:
        kw["mnc_days"] = a.mnc_days
    if a.startup_days is not None:
        kw["startup_days"] = a.startup_days
    if a.include_interns:
        kw["include_interns"] = True
    if a.no_verify:
        kw["verify"] = False
    res = pipeline.run_once(today, dry_run=a.dry_run, notify=not a.no_notify, **kw)
    print(res["markdown"])
    if res["short"]:
        print("\nWARNING: short digest. Consider MNC_DAYS/STARTUP_DAYS higher or INCLUDE_INTERNS=1.", file=sys.stderr)
    if res["errors"]:
        print(f"\n{len(res['errors'])} source errors (see `probe`).", file=sys.stderr)


def cmd_probe(a):
    from . import pipeline
    rows, errors, health = pipeline.collect(dt.date.today(), verify=False)
    for name, kind, slug, n, err in sorted(health, key=lambda h: (bool(h[4]), h[0])):
        print(f"{'ERR ' if err else 'ok  '} {name:22s} {kind:11s} {slug:55s} {err or f'{n} hits'}")
    print(f"\n{sum(1 for h in health if not h[4])}/{len(health)} sources ok; {len(rows)} candidates after dedupe")


def cmd_serve(_a):
    from . import scheduler
    scheduler.serve()


def cmd_show(a):
    from . import store
    con = store.connect()
    row = con.execute("SELECT day, markdown FROM digests WHERE day=? OR ? IS NULL ORDER BY day DESC LIMIT 1",
                      (a.date, a.date)).fetchone()
    print(row["markdown"] if row else "no digest yet")


def cmd_stats(_a):
    from . import store
    con = store.connect()
    print(f"db: {C.DB_PATH}")
    n_jobs, n_pub = con.execute("SELECT COUNT(*), SUM(published) FROM jobs").fetchone()
    print(f"jobs seen: {n_jobs}, published: {n_pub or 0}")
    for r in con.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 15"):
        print(f"  #{r['id']:<4} {r['started_at']}  ok={r['ok']}  cand={r['candidates']}  mnc={r['mnc']}  startups={r['startups']}  "
              f"{r['note'] or ''}")


def main(argv=None):
    _logging()
    ap = argparse.ArgumentParser(prog="jobs_worker")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--date")
    r.add_argument("--mnc-days", type=int)
    r.add_argument("--startup-days", type=int)
    r.add_argument("--include-interns", action="store_true")
    r.add_argument("--no-verify", action="store_true")
    r.add_argument("--dry-run", action="store_true", help="write digest files but do not mark jobs published / notify")
    r.add_argument("--no-notify", action="store_true")
    r.set_defaults(fn=cmd_run)
    sub.add_parser("serve").set_defaults(fn=cmd_serve)
    sub.add_parser("probe").set_defaults(fn=cmd_probe)
    s = sub.add_parser("show")
    s.add_argument("--date")
    s.set_defaults(fn=cmd_show)
    sub.add_parser("stats").set_defaults(fn=cmd_stats)
    w = sub.add_parser("web", help="local control panel with Scrape / Hide / Copy-post buttons")
    w.add_argument("--host", default="127.0.0.1")
    w.add_argument("--port", type=int, default=8787)
    w.set_defaults(fn=lambda a: __import__("jobs_worker.web", fromlist=["serve_web"]).serve_web(a.host, a.port))
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
