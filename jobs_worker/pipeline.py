"""
collect()  -> gather candidate rows from every enabled source, dedupe, score.
select()   -> pick N MNC + N startup rows, never re-publishing a URL the store has published.
render()   -> markdown + JSON payload.
run_once() -> the whole thing, persisted. This is what cron / the scheduler call.
"""
from __future__ import annotations

import concurrent.futures as cf
import csv
import datetime as dt
import logging
import re
import urllib.error

from . import config as C
from . import engine as E
from . import platforms as P
from . import store

log = logging.getLogger("jobs_worker")


def collect(today: dt.date, *, mnc_days=None, startup_days=None, include_interns=None, verify=None,
            enable_ats=None, enable_talentd=None, enable_linkedin=None, enable_unstop=None, enable_internshala=None):
    mnc_days = C.MNC_DAYS if mnc_days is None else mnc_days
    startup_days = C.STARTUP_DAYS if startup_days is None else startup_days
    include_interns = C.INCLUDE_INTERNS if include_interns is None else include_interns
    verify = C.VERIFY_LINKS if verify is None else verify
    flags = dict(ats=C.ENABLE_ATS if enable_ats is None else enable_ats,
                 talentd=C.ENABLE_TALENTD if enable_talentd is None else enable_talentd,
                 linkedin=C.ENABLE_LINKEDIN if enable_linkedin is None else enable_linkedin,
                 unstop=C.ENABLE_UNSTOP if enable_unstop is None else enable_unstop,
                 internshala=C.ENABLE_INTERNSHALA if enable_internshala is None else enable_internshala)
    window = {"mnc": mnc_days, "startup": startup_days}
    widest = max(window.values())
    results, errors, health = [], [], []

    def run_ats(src):
        name, kind, slug, tier = src
        try:
            rows = E.FETCHERS[kind](name, slug, today, window[tier], include_interns)
            for r in rows:
                r.update(tier=tier, source=kind, salary="", batch="", via="", size=None)
            return name, kind, slug, rows, None
        except urllib.error.HTTPError as e:
            return name, kind, slug, [], f"HTTP {e.code}"
        except Exception as e:  # noqa: BLE001
            return name, kind, slug, [], f"{type(e).__name__}: {str(e)[:80]}"

    def guarded(label, fn, *a):
        try:
            return label, fn(*a), None
        except Exception as e:  # noqa: BLE001
            return label, [], f"{type(e).__name__}: {str(e)[:80]}"

    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        ats_futures = [ex.submit(run_ats, s) for s in E.SOURCES] if flags["ats"] else []
        platform_futures = []
        if flags["talentd"]:
            platform_futures.append(ex.submit(guarded, "talentd", lambda: E.fetch_talentd(today, widest, include_interns, verify)[0]))
        if flags["linkedin"]:
            platform_futures.append(ex.submit(guarded, "linkedin", lambda: E.fetch_linkedin(today, widest, include_interns, verify)[0]))
        if flags["unstop"]:
            platform_futures.append(ex.submit(guarded, "unstop", P.fetch_unstop, today, widest, include_interns))
        if flags["internshala"]:
            platform_futures.append(ex.submit(guarded, "internshala", P.fetch_internshala, today, widest, include_interns))
        if C.ADZUNA_APP_ID and C.ADZUNA_APP_KEY:
            platform_futures.append(ex.submit(guarded, "adzuna", P.fetch_adzuna, today, widest, include_interns,
                                              C.ADZUNA_APP_ID, C.ADZUNA_APP_KEY))

        for f in cf.as_completed(ats_futures):
            name, kind, slug, rows, err = f.result()
            health.append((name, kind, slug, len(rows), err))
            if err:
                errors.append(f"{name} ({kind}:{slug}): {err}")
            else:
                results.extend(rows)
        for f in cf.as_completed(platform_futures):
            label, rows, err = f.result()
            health.append((label.title(), label, "platform", len(rows), err))
            if err:
                errors.append(f"{label}: {err}")
                continue
            rows = [r for r in rows if not r.get("posted") or (today - r["posted"]).days <= window.get(r.get("tier", "startup"), widest)]
            results.extend(rows)

    # dedupe: employer-portal rows win, then platform rows
    rank = {"talentd": 1, "unstop": 2, "internshala": 2, "adzuna": 2, "linkedin": 3}
    by_url, by_sig = {}, {}
    for r in sorted(results, key=lambda r: rank.get(r["source"], 0)):
        k = E.norm_url(r["url"])
        sig = (re.sub(r"\W+", "", r["company"].lower())[:12], re.sub(r"\W+", "", r["title"].lower()),
               re.sub(r"\W+", "", (r.get("location") or "").lower())[:10])
        if not k or k in by_url or sig in by_sig:
            continue
        r["url_key"] = k
        by_url[k] = r
        by_sig[sig] = r
    rows = list(by_url.values())
    # platform aggregators carry mostly tiny employers; employer portals, Talentd and LinkedIn rank first
    penalty = {"unstop": 2, "internshala": 3, "adzuna": 2}
    for r in rows:
        r["quality"] = E.quality(r) - penalty.get(r["source"], 0)
    return rows, errors, health


def select(rows, published: set[str], *, mnc_count=None, startup_max=None, per_company_cap=2):
    mnc_count = C.MNC_COUNT if mnc_count is None else mnc_count
    startup_max = C.STARTUP_MAX if startup_max is None else startup_max
    for r in rows:
        r["new"] = r["url_key"] not in published
    rows = sorted(rows, key=lambda r: (not r["new"], -r["quality"], -(r["posted"].toordinal() if r.get("posted") else 0), r["company"]))

    def pick(tier, n_max):
        chosen, per_company = [], {}
        for r in (r for r in rows if r.get("tier") == tier and r["new"]):
            if per_company.get(r["company"], 0) >= per_company_cap:
                continue
            chosen.append(r)
            per_company[r["company"]] = per_company.get(r["company"], 0) + 1
            if len(chosen) >= n_max:
                break
        return chosen

    return pick("mnc", mnc_count), pick("startup", startup_max)


def render(today, mnc, startups, n_candidates, n_sources_ok, mnc_days, startup_days):
    md = [f"# Fresher tech openings — {today.strftime('%d %b %Y')}", ""]

    def section(title, items):
        md.append(f"## {title} ({len(items)})")
        md.append("")
        for i, r in enumerate(items, 1):
            when = r["posted"].strftime("%d %b") if r.get("posted") else "date n/a"
            extras = []
            if r.get("batch"):
                extras.append(f"batch {r['batch']}")
            if r.get("salary"):
                extras.append(r["salary"])
            if r.get("kind") == "intern":
                extras.append("Internship")
            tail = (" · " + " · ".join(extras)) if extras else ""
            md.append(f"{i}. **{r['company']} – {r['title']}** · {r.get('location') or 'India'} · posted {when}{tail}")
            md.append(f"   {r['url']}")
            if r.get("source") == "linkedin" and "linkedin.com" not in r["url"] and r.get("via"):
                md.append(f"   (LinkedIn post: {r['via']})")
            if r.get("snippet"):
                md.append(f"   _{r['snippet']}_")
        md.append("")

    section("MNC", mnc)
    section("Startups", startups)
    md.append(f"_Window: MNC last {mnc_days} days, startups last {startup_days} days. {n_candidates} candidates after dedupe "
              f"from {n_sources_ok} sources (employer career portals, Talentd, Unstop, Internshala, LinkedIn). "
              f"Only postings never published before are listed; links were checked live before inclusion._")
    cols = ["tier", "company", "title", "location", "posted", "kind", "salary", "batch", "url", "source"]
    payload = {"date": today.isoformat(), "mnc": [{k: (r[k].isoformat() if k == "posted" and r.get(k) else r.get(k, "")) for k in cols} for r in mnc],
               "startups": [{k: (r[k].isoformat() if k == "posted" and r.get(k) else r.get(k, "")) for k in cols} for r in startups]}
    return "\n".join(md), payload


def run_once(today: dt.date | None = None, *, dry_run=False, notify=True, **collect_kwargs):
    today = today or dt.date.today()
    stamp = today.isoformat()
    con = store.connect()
    run_id = store.start_run(con)
    try:
        rows, errors, health = collect(today, **collect_kwargs)
        store.upsert_candidates(con, rows, stamp)
        mnc, startups = select(rows, store.published_keys(con))
        n_ok = sum(1 for h in health if not h[4])
        md, payload = render(today, mnc, startups, len(rows), n_ok,
                             collect_kwargs.get("mnc_days") or C.MNC_DAYS, collect_kwargs.get("startup_days") or C.STARTUP_DAYS)
        (C.DATA_DIR / f"{stamp}.md").write_text(md)
        with (C.DATA_DIR / f"{stamp}.csv").open("w", newline="") as f:
            cols = ["tier", "company", "title", "location", "posted", "kind", "salary", "batch", "url", "source"]
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in payload["mnc"] + payload["startups"]:
                w.writerow(r)
        if not dry_run:
            store.mark_published(con, mnc + startups, stamp)
            store.save_digest(con, stamp, md, payload)
        short = len(mnc) < C.MNC_COUNT or len(startups) < C.STARTUP_MIN
        note = f"short: mnc {len(mnc)}/{C.MNC_COUNT} startups {len(startups)}/{C.STARTUP_MIN}" if short else ""
        store.finish_run(con, run_id, True, len(rows), len(mnc), len(startups), errors, note)
        if notify and not dry_run:
            from . import notify as N
            N.send_digest(md, payload)
        log.info("run %s done: %d candidates, %d mnc, %d startups, %d source errors%s", stamp, len(rows), len(mnc), len(startups),
                 len(errors), f" ({note})" if note else "")
        return dict(markdown=md, payload=payload, errors=errors, health=health, short=short)
    except Exception as e:
        store.finish_run(con, run_id, False, errors=[f"{type(e).__name__}: {e}"])
        log.exception("run failed")
        raise
    finally:
        con.close()
