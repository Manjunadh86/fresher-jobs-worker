"""
Job-platform sources (as opposed to employer portals): Unstop and Internshala.
Both expose fresher-tagged listings publicly; we still run every row through the shared
title/description classifier and the India/tech filters from the engine.
"""
from __future__ import annotations

import concurrent.futures as cf
import datetime as dt
import html
import re
import urllib.parse

from . import engine as E

PLATFORM_EXCLUDE_RE = re.compile(
    r"\b(coordinator|executive|seller|maps? analyst|market research|trainer|training|telecall|project execution|"
    r"language|translator|annotat|labell?ing|survey|promoter|freelance|commission|intern)\b", re.I)
FOREIGN_RE = re.compile(r"\((?!.*\bIndia\b)[^)]*,\s*[^)]+\)\s*$")   # "Acme (Tokyo, Japan)"


def _lpa(lo: float, hi: float) -> str:
    lo, hi = round(lo / 1e5, 2), round(hi / 1e5, 2)
    return (f"₹{lo:g} LPA" if lo == hi else f"₹{lo:g}–{hi:g} LPA") + " (as listed)"


# --------------------------------------------------------------------------- Unstop
UNSTOP_API = ("https://unstop.com/api/public/opportunity/search-result?opportunity=jobs&per_page=50"
              "&oppstatus=open&usertype=fresher&page={page}")
UNSTOP_PAGES = 6


def fetch_unstop(today, days, include_interns):
    rows, seen = [], set()
    for page in range(1, UNSTOP_PAGES + 1):
        try:
            d = E.http_json(UNSTOP_API.format(page=page), headers={"Accept": "application/json"})
        except Exception:  # noqa: BLE001
            break
        items = (d.get("data") or {}).get("data") or []
        if not items:
            break
        old = 0
        for j in items:
            jid = j.get("id")
            if not jid or jid in seen:
                continue
            seen.add(jid)
            posted = None
            ad = j.get("approved_date") or ""
            m = re.match(r"(\d{4}-\d{2}-\d{2})", ad)
            if m:
                posted = dt.date.fromisoformat(m.group(1))
            else:
                posted = E.parse_iso(((j.get("regnRequirements") or {}).get("start_regn_dt")))
            if posted and (today - posted).days > days:
                old += 1
                continue
            title = html.unescape(j.get("title") or "").strip()
            jd = j.get("jobDetail") or {}
            mx = jd.get("max_experience")
            if mx is not None and str(mx).isdigit() and int(mx) > 2:
                continue
            addr = j.get("address_with_country_logo") or {}
            loc_bits = [addr.get("city"), addr.get("state")]
            locs = j.get("locations") or j.get("jobDetail", {}).get("locations") or []
            for l in locs if isinstance(locs, list) else []:
                if isinstance(l, dict):
                    loc_bits.append(l.get("city") or l.get("name"))
            location = " / ".join(x for x in loc_bits if x) or ("Remote (India)" if j.get("region") == "online" else "India")
            country = (addr.get("country") or "").lower()
            if country and country not in ("india", "in"):
                continue
            desc = E.strip_html(j.get("details") or "")
            if PLATFORM_EXCLUDE_RE.search(title):
                continue
            kind = E.classify(title, desc + " fresher", include_interns)
            if not kind:
                continue
            org = (j.get("organisation") or {}).get("name") or ""
            if not org or E.STAFFING_RE.search(org):
                continue
            salary = ""
            if jd.get("show_salary") and jd.get("min_salary") and jd.get("max_salary") and not jd.get("not_disclosed"):
                mult = 12 if (jd.get("pay_in") or "").startswith("month") else 1
                salary = _lpa(jd["min_salary"] * mult, jd["max_salary"] * mult)
            url = j.get("seo_url") or ("https://unstop.com/" + (j.get("public_url") or "").lstrip("/"))
            rows.append(dict(company=org, title=title, location=location, posted=posted, url=url, kind=kind,
                             source="unstop", snippet=E.snippet(desc), salary=salary, batch="", via="", size=None,
                             tier="startup"))
        if old >= len(items) * 0.8:
            break
    # Unstop is overwhelmingly small companies; promote well-known MNC names.
    for r in rows:
        if is_mnc(r["company"]):
            r["tier"] = "mnc"
    return rows


# --------------------------------------------------------------------------- Internshala
INTERNSHALA_PAGES = ["https://internshala.com/fresher-jobs/"] + [f"https://internshala.com/jobs/{c}-jobs/" for c in (
    "software-development", "web-development", "data-science", "full-stack-development", "machine-learning",
    "backend-development", "front-end-development", "software-testing", "android-app-development", "computer-science")]
INTERNSHALA_MAX_DETAIL = 60


def _internshala_cards(body):
    for c in re.split(r'(?=<div class="[^"]*\bindividual_internship\b)', body)[1:]:
        title = re.search(r'class="job-title-href"[^>]*>\s*(.*?)\s*</a>', c, re.S)
        link = re.search(r'class="job-title-href"[^>]*href="([^"]+)"', c) or re.search(r'href="(/job/detail/[^"]+)"', c)
        comp = re.search(r'class="company-name"[^>]*>\s*(.*?)\s*</p>', c, re.S)
        loc = re.search(r'class="row-1-item\s+locations"[^>]*>(.*?)</p>', c, re.S)
        exp = re.search(r'(\d+)(?:\s*-\s*(\d+))?\s*years?(?:\(s\))?', c)
        when = re.search(r'(Just now|Today|\d+ (day|hour|minute|week)s? ago|Few hours ago)', c, re.I)
        sal = re.search(r'₹\s*([\d,]+)\s*(?:-\s*([\d,]+))?\s*(?:/year|per annum|LPA)', c)
        if not (title and link):
            continue
        yield dict(title=E.strip_html(title.group(1)), path=link.group(1), company=E.strip_html(comp.group(1)) if comp else "",
                   location=E.strip_html(loc.group(1)) if loc else "", exp=exp, when=when.group(1) if when else "",
                   salary=sal)


def fetch_internshala(today, days, include_interns):
    def page(url):
        try:
            return list(_internshala_cards(E.http(url, headers={"Accept": "text/html"})[2]))
        except Exception:  # noqa: BLE001
            return []

    cards = []
    with cf.ThreadPoolExecutor(max_workers=5) as ex:
        for cs in ex.map(page, INTERNSHALA_PAGES):
            cards.extend(cs)
    rows, seen = [], set()
    for c in cards:
        if c["path"] in seen:
            continue
        seen.add(c["path"])
        w = c["when"].lower()
        posted = today if ("hour" in w or "minute" in w or "just" in w or "today" in w) else E.parse_relative(w, today)
        if "week" in w:
            m = re.search(r"(\d+)", w)
            posted = today - dt.timedelta(weeks=int(m.group(1))) if m else None
        if posted and (today - posted).days > days:
            continue
        if c["exp"] and c["exp"].group(1) and int(c["exp"].group(1)) > 1:
            continue
        title = c["title"]
        if E.NON_TECH_RE.search(title) or not E.TECH_RE.search(title) or E.SENIOR_TITLE_RE.search(title):
            continue
        if PLATFORM_EXCLUDE_RE.search(title) or FOREIGN_RE.search(c["company"]) or " " not in c["company"].strip() and len(c["company"]) < 6:
            continue
        if E.INTERN_RE.search(title) and not include_interns:
            continue
        if not c["company"] or E.STAFFING_RE.search(c["company"]):
            continue
        rows.append(dict(c=c, posted=posted, title=title))

    def detail(item):
        c = item["c"]
        url = urllib.parse.urljoin("https://internshala.com/", c["path"])
        desc = ""
        try:
            _, _, body = E.http(url, headers={"Accept": "text/html"})
            dm = re.search(r'class="text-container"[^>]*>(.*?)</div>\s*</div>', body, re.S) or \
                re.search(r'class="internship_details"[^>]*>(.*?)<div class="additional_detail', body, re.S)
            desc = E.strip_html(dm.group(1)) if dm else E.strip_html(body)[:4000]
        except Exception:  # noqa: BLE001
            pass
        kind = E.classify(item["title"], desc + " fresher", include_interns)
        if not kind:
            return None
        salary = ""
        if c["salary"]:
            lo = int(c["salary"].group(1).replace(",", ""))
            hi = int(c["salary"].group(2).replace(",", "")) if c["salary"].group(2) else lo
            if lo >= 100000:
                salary = _lpa(lo, hi)
        return dict(company=c["company"], title=item["title"], location=re.sub(r"\s*,\s*", ", ", c["location"]).strip(", ") or "India", posted=item["posted"],
                    url=url, kind=kind, source="internshala", snippet=E.snippet(desc), salary=salary, batch="", via="",
                    size=None, tier="mnc" if is_mnc(c["company"]) else "startup")

    out = []
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        for r in ex.map(detail, rows[:INTERNSHALA_MAX_DETAIL]):
            if r:
                out.append(r)
    return out


_ATS_MNC = {n.lower() for n, _k, _s, t in E.SOURCES if t == "mnc"}


def is_mnc(company: str) -> bool:
    c = (company or "").lower().strip()
    return c in _ATS_MNC or bool(MNC_NAME_RE.search(c))


# --------------------------------------------------------------------------- Adzuna (optional, needs free API key)
ADZUNA_QUERIES = ["fresher software engineer", "graduate engineer trainee software", "junior developer", "entry level data analyst",
                  "associate software engineer", "trainee software developer", "fresher python", "fresher java developer"]


def fetch_adzuna(today, days, include_interns, app_id, app_key):
    rows, seen = [], set()
    for q in ADZUNA_QUERIES:
        for page in (1, 2):
            url = (f"https://api.adzuna.com/v1/api/jobs/in/search/{page}?app_id={app_id}&app_key={app_key}&results_per_page=50"
                   f"&what={urllib.parse.quote(q)}&max_days_old={days}&sort_by=date&content-type=application/json")
            try:
                d = E.http_json(url)
            except Exception:  # noqa: BLE001
                break
            res = d.get("results") or []
            for j in res:
                jid = j.get("id")
                if not jid or jid in seen:
                    continue
                seen.add(jid)
                title = html.unescape(j.get("title") or "").replace("<strong>", "").replace("</strong>", "")
                company = ((j.get("company") or {}).get("display_name") or "").strip()
                if not company or E.STAFFING_RE.search(company) or PLATFORM_EXCLUDE_RE.search(title):
                    continue
                desc = E.strip_html(j.get("description") or "")
                kind = E.classify(title, desc, include_interns)
                if not kind:
                    continue
                posted = E.parse_iso(j.get("created"))
                sal = ""
                if j.get("salary_min") and j.get("salary_max"):
                    sal = _lpa(float(j["salary_min"]), float(j["salary_max"]))
                rows.append(dict(company=company, title=title, location=(j.get("location") or {}).get("display_name") or "India",
                                 posted=posted, url=j.get("redirect_url"), kind=kind, source="adzuna", snippet=E.snippet(desc),
                                 salary=sal, batch="", via="", size=None, tier="mnc" if is_mnc(company) else "startup"))
            if len(res) < 50:
                break
    return rows


MNC_NAME_RE = re.compile(
    r"\b(emerson|rubrik|cme group|iqvia|gitlab|github|nutanix|cohesity|pure storage|netapp|commvault|veritas|"
    r"palo alto|fortinet|zscaler|crowdstrike|okta|splunk|datadog|snowflake|databricks|mongodb|elastic|confluent|"
    r"twilio|zendesk|hubspot|intuit|autodesk|ansys|mathworks|epam|globallogic|nagarro|ust\b|cyient|kpit|tata elxsi|"
    r"tcs|tata consultancy|infosys|wipro|hcl|hcltech|tech mahindra|cognizant|accenture|capgemini|ibm|oracle|"
    r"microsoft|google|amazon|aws|meta|apple|cisco|intel|nvidia|qualcomm|samsung|dell|hp\b|hpe|lenovo|sap\b|"
    r"salesforce|adobe|vmware|broadcom|deloitte|ey\b|ernst|kpmg|pwc|genpact|mphasis|ltimindtree|l&t|larsen|"
    r"persistent|hexaware|zensar|birlasoft|coforge|ntt data|dxc|unisys|atos|virtusa|mindtree|cgi\b|sopra|"
    r"jpmorgan|jp morgan|goldman|morgan stanley|barclays|hsbc|citi|wells fargo|bank of america|deutsche|ubs|"
    r"standard chartered|american express|mastercard|visa\b|paypal|fidelity|blackrock|state street|nasdaq|lseg|"
    r"bosch|siemens|honeywell|ge\b|philips|schneider|abb\b|ericsson|nokia|juniper|arista|motorola|texas instruments|"
    r"micron|amd\b|applied materials|kla\b|lam research|nxp|infineon|stmicro|analog devices|synopsys|cadence|"
    r"walmart|target|lowe'?s|tesco|uber|airbnb|netflix|linkedin|twitter|x corp|stripe|atlassian|servicenow|"
    r"workday|zoho|freshworks|optum|unitedhealth|cvs|pfizer|novartis|amgen|roche|gsk|astrazeneca|j&j|johnson|"
    r"medtronic|abbott|3m|solventum|caterpillar|deere|boeing|airbus|rolls|ford|gm\b|general motors|toyota|"
    r"thomson reuters|s&p|moody|bloomberg|nielsen|gartner|verizon|at&t|comcast|rockwell|hitachi|toshiba|fujitsu|"
    r"nec\b|canon|sony|panasonic|lg\b|hyundai|volvo|daimler|mercedes|bmw|continental|zf\b|valeo|renault|nissan)\b",
    re.I,
)
