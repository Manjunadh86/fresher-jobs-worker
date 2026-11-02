"""
Public Streamlit app for the daily fresher-jobs digest.

Reads the SQLite DB the worker writes (committed daily by GitHub Actions, or produced by `Scrape now`
from the admin panel). Deterministic: no LLMs, just the worker's filters.

Run locally:   streamlit run app.py
Streamlit Cloud: main file = worker/app.py ; secrets: ADMIN_TOKEN (optional), ADZUNA_* (optional)
"""
from __future__ import annotations

import datetime as dt
import io
import os
import sys
import threading
from pathlib import Path

import streamlit as st

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("JOBS_DATA_DIR", str(HERE / "data"))
# Streamlit secrets → env so jobs_worker.config picks them up
try:
    for k, v in st.secrets.items():
        if isinstance(v, str) and k.isupper():
            os.environ.setdefault(k, v)
except Exception:  # noqa: BLE001  (no secrets file locally)
    pass

from jobs_worker import config as C  # noqa: E402
from jobs_worker import pipeline, store  # noqa: E402
from jobs_worker.web import post_text  # noqa: E402

st.set_page_config(page_title="Fresher tech jobs · daily", page_icon="🧑‍💻", layout="wide")

RUN = st.session_state.setdefault("run", {"thread": None, "result": None, "error": None})


def _load(day: str):
    con = store.connect()
    try:
        return store.day_rows(con, day), store.days(con)
    finally:
        con.close()


def _today() -> str:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=5, minutes=30))).date().isoformat()


def _start_scrape(day: dt.date):
    def body():
        try:
            RUN["result"] = pipeline.run_once(day, notify=False)
        except Exception as e:  # noqa: BLE001
            RUN["error"] = f"{type(e).__name__}: {e}"

    RUN["result"], RUN["error"] = None, None
    t = threading.Thread(target=body, daemon=True)
    RUN["thread"] = t
    t.start()


# ----------------------------------------------------------------------------- sidebar
with st.sidebar:
    st.title("Fresher tech jobs")
    st.caption("India · MNC + startups · verified links · no reposts")
    try:
        _, all_days = _load(_today())
    except Exception as e:  # noqa: BLE001
        st.error(f"DB unavailable: {e}")
        all_days = []
    if _today() not in all_days:
        all_days = [_today()] + all_days
    day = st.selectbox("Day", all_days, index=0)
    q = st.text_input("Search", placeholder="python, bangalore, qa …")
    tiers = st.multiselect("Tier", ["mnc", "startup"], default=["mnc", "startup"])
    only_salary = st.checkbox("Only with salary", value=False)

    st.divider()
    st.subheader("Admin")
    token = st.text_input("Admin token", type="password") if C.ADMIN_TOKEN else ""
    is_admin = (not C.ADMIN_TOKEN) or (token == C.ADMIN_TOKEN)
    running = RUN["thread"] is not None and RUN["thread"].is_alive()
    if st.button("Scrape now", disabled=(not is_admin) or running, use_container_width=True):
        _start_scrape(dt.date.fromisoformat(day))
        st.rerun()
    if running:
        st.info("Scraping… 2–4 min. This page refreshes automatically.")
        st.markdown("<meta http-equiv='refresh' content='15'>", unsafe_allow_html=True)
    elif RUN["error"]:
        st.error(RUN["error"])
    elif RUN["result"]:
        r = RUN["result"]
        st.success(f"+{len(r['payload']['mnc'])} MNC, +{len(r['payload']['startups'])} startups, {len(r['errors'])} source errors")
    if C.ADMIN_TOKEN and not is_admin and token:
        st.warning("Wrong token")

# ----------------------------------------------------------------------------- main
rows, _ = _load(day)
rows = [r for r in rows if r["tier"] in tiers]
if q:
    ql = q.lower()
    rows = [r for r in rows if ql in " ".join(str(r.get(k) or "") for k in ("company", "title", "location", "snippet", "source")).lower()]
if only_salary:
    rows = [r for r in rows if r.get("salary")]

mnc = [r for r in rows if r["tier"] == "mnc"]
startups = [r for r in rows if r["tier"] == "startup"]

st.header(f"{dt.date.fromisoformat(day).strftime('%d %b %Y')}")
c1, c2, c3 = st.columns(3)
c1.metric("MNC", len(mnc))
c2.metric("Startups", len(startups))
c3.metric("Sources", "ATS portals · Talentd · LinkedIn · Unstop · Internshala")

if not rows:
    st.info("No jobs for this day yet. The daily run lands at 08:30 IST; admins can press **Scrape now**.")


def render(items, label):
    st.subheader(f"{label} ({len(items)})")
    for r in items:
        bits = [r.get("location") or "India"]
        if r.get("posted"):
            bits.append(f"posted {r['posted'].strftime('%d %b')}")
        if r.get("salary"):
            bits.append(r["salary"].replace(" (as listed)", ""))
        if r.get("batch"):
            bits.append(f"batch {r['batch']}")
        if r.get("kind") == "intern":
            bits.append("internship")
        with st.container(border=True):
            st.markdown(f"**{r['company']}** — [{r['title']}]({r['url']})  \n"
                        f"<span style='color:#666;font-size:0.9em'>{' · '.join(bits)} · via {r.get('source')}</span>",
                        unsafe_allow_html=True)
            if r.get("snippet"):
                st.caption(r["snippet"])
            if is_admin:
                if st.button("Hide from post", key=f"hide-{r['url_key']}"):
                    con = store.connect()
                    store.set_hidden(con, r["url_key"], True)
                    con.close()
                    st.rerun()


left, right = st.columns(2)
with left:
    render(mnc, "MNC")
with right:
    render(startups, "Startups")

st.divider()
st.subheader("Post text")
txt = post_text(rows, dt.date.fromisoformat(day))
st.code(txt, language=None)
buf = io.StringIO()
import csv  # noqa: E402

w = csv.writer(buf)
w.writerow(["tier", "company", "title", "location", "posted", "salary", "batch", "url", "source"])
for r in rows:
    w.writerow([r["tier"], r["company"], r["title"], r.get("location"), r["posted"].isoformat() if r.get("posted") else "",
                r.get("salary"), r.get("batch"), r["url"], r.get("source")])
st.download_button("Download CSV", buf.getvalue(), file_name=f"fresher-jobs-{day}.csv", mime="text/csv")
st.caption("Pipeline: employer career portals (Workday, Greenhouse, Ashby, Lever, Workable, SmartRecruiters, Oracle HCM, "
           "SuccessFactors) + Talentd, Unstop, Internshala, LinkedIn → regex filters → dedupe → never repost. No LLMs.")
