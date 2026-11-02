"""
Scraping engine: employer ATS APIs (Workday / Greenhouse / Ashby / Lever / Workable /
SmartRecruiters), Talentd discovery layer, LinkedIn guest layer, plus shared filters.

`collect()` is the single entry point used by the worker. No CLI here; see jobs_worker.__main__.
"""
from __future__ import annotations

import concurrent.futures as cf
import csv
import datetime as dt
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .config import DATA_DIR

OUT_DIR = DATA_DIR
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
TIMEOUT = 25

# --------------------------------------------------------------------------- ATS sources
# (display name, kind, slug, tier). Workday slug = "tenant.wdN/site". Only sources that
# answered correctly in the last probe are kept; run --probe after adding new ones.
SOURCES = [
    # MNC — Oracle HCM Cloud (host/CX_site)
    ("Honeywell", "oraclecloud", "ibqbjb.fa.ocs.oraclecloud.com/CX_1", "mnc"),
    ("EXL", "oraclecloud", "fa-ewjt-saasfaprod1.fa.ocs.oraclecloud.com/CX_2", "mnc"),
    ("KPMG India", "oraclecloud", "ejgk.fa.em2.oraclecloud.com/CX_3", "mnc"),
    ("Oracle", "oraclecloud", "eeho.fa.us2.oraclecloud.com/CX_1", "mnc"),
    ("Zensar", "oraclecloud", "fa-etvl-saasfaprod1.fa.ocs.oraclecloud.com/CX_1", "mnc"),
    # MNC — SAP SuccessFactors career sites
    ("EY", "successfactors", "careers.ey.com", "mnc"),
    ("Capgemini", "successfactors", "careers.capgemini.com", "mnc"),
    ("NTT Data", "successfactors", "careers-inc.nttdata.com", "mnc"),
    ("Firstsource", "successfactors", "careers.firstsource.com", "mnc"),
    ("Iris Software", "successfactors", "careers.irissoftware.com", "mnc"),
    # MNC — Workday
    ("Cisco", "workday", "cisco.wd5/Cisco_Careers", "mnc"),
    ("NVIDIA", "workday", "nvidia.wd5/NVIDIAExternalCareerSite", "mnc"),
    ("Adobe", "workday", "adobe.wd5/external_experienced", "mnc"),
    ("Salesforce", "workday", "salesforce.wd12/External_Career_Site", "mnc"),
    ("Intel", "workday", "intel.wd1/External", "mnc"),
    ("Autodesk", "workday", "autodesk.wd1/Ext", "mnc"),
    ("PayPal", "workday", "paypal.wd1/jobs", "mnc"),
    ("Target", "workday", "target.wd5/targetcareers", "mnc"),
    ("Philips", "workday", "philips.wd3/jobs-and-careers", "mnc"),
    ("Broadcom", "workday", "broadcom.wd1/External_Career", "mnc"),
    ("Micron", "workday", "micron.wd1/External", "mnc"),
    ("Cadence", "workday", "cadence.wd1/External_Careers", "mnc"),
    ("Mastercard", "workday", "mastercard.wd1/CorporateCareers", "mnc"),
    ("S&P Global", "workday", "spgi.wd5/SPGI_Careers", "mnc"),
    ("Boeing", "workday", "boeing.wd1/EXTERNAL_CAREERS", "mnc"),
    ("Thomson Reuters", "workday", "thomsonreuters.wd5/External_Career_Site", "mnc"),
    ("Trellix / Skyhigh", "workday", "trellix.wd1/EnterpriseCareers", "mnc"),
    ("Rockwell Automation", "workday", "rockwellautomation.wd1/External-Rockwell-Automation-Early-Careers", "mnc"),
    ("Ciena", "workday", "ciena.wd5/Careers", "mnc"),
    ("KLA", "workday", "kla.wd1/Search", "mnc"),
    ("Applied Materials", "workday", "amat.wd1/External", "mnc"),
    ("NXP", "workday", "nxp.wd3/careers", "mnc"),
    ("Caterpillar", "workday", "cat.wd5/CaterpillarCareers", "mnc"),
    ("General Motors", "workday", "generalmotors.wd5/Careers_GM", "mnc"),
    ("3M", "workday", "3m.wd1/Search", "mnc"),
    ("Pfizer", "workday", "pfizer.wd1/PfizerCareers", "mnc"),
    ("CVS Health", "workday", "cvshealth.wd1/CVS_Health_Careers", "mnc"),
    ("HP", "workday", "hp.wd5/ExternalCareerSite", "mnc"),
    ("HPE", "workday", "hpe.wd5/Jobsathpe", "mnc"),
    ("Motorola Solutions", "workday", "motorolasolutions.wd5/Careers", "mnc"),
    ("State Street", "workday", "statestreet.wd1/Global", "mnc"),
    ("BlackRock", "workday", "blackrock.wd1/BlackRock_Professional", "mnc"),
    ("FIS", "workday", "fis.wd5/SearchJobs", "mnc"),
    ("Nasdaq", "workday", "nasdaq.wd1/Global_External_Site", "mnc"),
    ("Amgen", "workday", "amgen.wd1/Careers", "mnc"),
    ("LSEG", "workday", "lseg.wd3/Careers", "mnc"),
    # MNC — Greenhouse / Lever / Ashby
    ("Stripe", "greenhouse", "stripe", "mnc"),
    ("Databricks", "greenhouse", "databricks", "mnc"),
    ("Rubrik", "greenhouse", "rubrik", "mnc"),
    ("Coinbase", "greenhouse", "coinbase", "mnc"),
    ("Twilio", "greenhouse", "twilio", "mnc"),
    ("Cloudflare", "greenhouse", "cloudflare", "mnc"),
    ("Datadog", "greenhouse", "datadog", "mnc"),
    ("Elastic", "greenhouse", "elastic", "mnc"),
    ("MongoDB", "greenhouse", "mongodb", "mnc"),
    ("GitLab", "greenhouse", "gitlab", "mnc"),
    ("Okta", "greenhouse", "okta", "mnc"),
    ("Zscaler", "greenhouse", "zscaler", "mnc"),
    ("Figma", "greenhouse", "figma", "mnc"),
    ("Samsara", "greenhouse", "samsara", "mnc"),
    ("Robinhood", "greenhouse", "robinhood", "mnc"),
    ("Reddit", "greenhouse", "reddit", "mnc"),
    ("Pinterest", "greenhouse", "pinterest", "mnc"),
    ("Lyft", "greenhouse", "lyft", "mnc"),
    ("Dropbox", "greenhouse", "dropbox", "mnc"),
    ("Intercom", "greenhouse", "intercom", "mnc"),
    ("Asana", "greenhouse", "asana", "mnc"),
    ("PagerDuty", "greenhouse", "pagerduty", "mnc"),
    ("New Relic", "greenhouse", "newrelic", "mnc"),
    ("Pure Storage", "greenhouse", "purestorage", "mnc"),
    ("Agoda", "greenhouse", "agoda", "mnc"),
    ("DevRev", "greenhouse", "devrev", "mnc"),
    ("Druva", "greenhouse", "druva", "mnc"),
    ("Deliveroo", "greenhouse", "deliveroo", "mnc"),
    ("Anthropic", "greenhouse", "anthropic", "mnc"),
    ("Scale AI", "greenhouse", "scaleai", "mnc"),
    ("Instacart", "greenhouse", "instacart", "mnc"),
    ("OpenAI", "ashby", "openai", "mnc"),
    ("Notion", "ashby", "notion", "mnc"),
    ("Cohere", "ashby", "cohere", "mnc"),
    ("Deel", "ashby", "deel", "mnc"),
    ("Cerebras", "ashby", "cerebras", "mnc"),
    # Startups (Indian + India-office). Slugs verified with a live probe on 31 Oct 2026.
    ("Swiggy", "smartrecruiters", "swiggy", "startup"),
    ("Paytm", "lever", "paytm", "startup"),
    ("Meesho", "lever", "meesho", "startup"),
    ("Freshworks", "smartrecruiters", "freshworks", "startup"),
    ("InMobi", "greenhouse", "inmobi", "startup"),
    ("Glance", "greenhouse", "glance", "startup"),
    ("Groww", "greenhouse", "groww", "startup"),
    ("slice", "greenhouse", "slice", "startup"),
    ("Zeta", "lever", "zeta", "startup"),
    ("CRED", "lever", "cred", "startup"),
    ("Razorpay", "greenhouse", "razorpaysoftwareprivatelimited", "startup"),
    ("Fi (epiFi)", "lever", "fi", "startup"),
    ("Fi (epiFi)", "lever", "epifi", "startup"),
    ("FamPay", "lever", "fampay", "startup"),
    ("Hevo Data", "lever", "hevodata", "startup"),
    ("Mindtickle", "lever", "mindtickle", "startup"),
    ("Pocket FM", "lever", "pocketfm", "startup"),
    ("Porter", "lever", "porter", "startup"),
    ("Porter", "greenhouse", "porter", "startup"),
    ("Apna", "workable", "apna", "startup"),
    ("Atlan", "ashby", "atlan", "startup"),
    ("Navi", "ashby", "navi", "startup"),
    ("HackerRank", "greenhouse", "hackerrank", "startup"),
    ("Turing", "greenhouse", "turing", "startup"),
    ("Toptal", "lever", "toptal", "startup"),
    ("ixigo", "smartrecruiters", "ixigo", "startup"),
    ("Unacademy", "smartrecruiters", "unacademy", "startup"),
    ("Cars24", "smartrecruiters", "cars24", "startup"),
    ("NoBroker", "smartrecruiters", "nobroker", "startup"),
    ("Lendingkart", "smartrecruiters", "lendingkart", "startup"),
    ("Upstox", "smartrecruiters", "upstox", "startup"),
    ("Whatfix", "smartrecruiters", "whatfix", "startup"),
    ("Newton School", "smartrecruiters", "newtonschool", "startup"),
    ("Rebel Foods", "smartrecruiters", "rebelfoods", "startup"),
    ("Sarvam AI", "ashby", "sarvam", "startup"),
    ("Refold AI", "ashby", "refoldai", "startup"),
    ("Sentient", "ashby", "sentient", "startup"),
    ("Ema", "ashby", "ema", "startup"),
    ("Supabase", "ashby", "supabase", "startup"),
    ("Perplexity", "ashby", "perplexity", "startup"),
    ("ElevenLabs", "ashby", "elevenlabs", "startup"),
    ("Replit", "ashby", "replit", "startup"),
    ("Linear", "ashby", "linear", "startup"),
    ("Ramp", "ashby", "ramp", "startup"),
    ("Vanta", "ashby", "vanta", "startup"),
    ("Drata", "ashby", "drata", "startup"),
    ("Snowflake", "ashby", "snowflake", "mnc"),
    ("Fivetran", "greenhouse", "fivetran", "startup"),
    ("Kong", "ashby", "kong", "startup"),
    ("Cursor (Anysphere)", "ashby", "cursor", "startup"),
    ("Lovable", "ashby", "lovable", "startup"),
    ("Render", "ashby", "render", "startup"),
    ("Amplitude", "ashby", "amplitude", "startup"),
    ("ClickUp", "ashby", "clickup", "startup"),
    ("Mixpanel", "greenhouse", "mixpanel", "startup"),
    ("Airbyte", "ashby", "airbyte", "startup"),
    ("PostHog", "ashby", "posthog", "startup"),
    ("Sentry", "ashby", "sentry", "startup"),
    ("Canva", "smartrecruiters", "canva", "startup"),
    ("xAI", "greenhouse", "xai", "startup"),
    ("Andela", "ashby", "andela", "startup"),
    ("incident.io", "ashby", "incident", "startup"),
    ("Webflow", "ashby", "webflow", "startup"),
    ("Synthesia", "ashby", "synthesia", "startup"),
    ("HeyGen", "greenhouse", "heygen", "startup"),
    ("Labelbox", "greenhouse", "labelbox", "startup"),
    ("Honeycomb", "greenhouse", "honeycomb", "startup"),
    ("PlanetScale", "greenhouse", "planetscale", "startup"),
    ("Neon", "lever", "neon", "startup"),
    ("Kore.ai", "smartrecruiters", "koreai", "startup"),
    ("GeeksforGeeks", "smartrecruiters", "gfg", "startup"),
    ("Stable Money", "ashby", "stable", "startup"),
    ("Observe.AI", "greenhouse", "observeai", "startup"),
    ("Zenoti", "greenhouse", "zenoti", "startup"),
    ("Netradyne", "greenhouse", "netradyne", "startup"),
    ("Vercel", "greenhouse", "vercel", "startup"),
    ("Mistral AI", "lever", "mistral", "startup"),
    ("Brex", "greenhouse", "brex", "startup"),
]

# Companies Talentd marks as 1,000+ people that the community still thinks of as startups.
STARTUP_NAMES = {
    "razorpay", "zepto", "meesho", "cred", "swiggy", "zomato", "phonepe", "groww", "paytm", "ola", "ola electric",
    "flipkart", "myntra", "nykaa", "lenskart", "dream11", "games24x7", "mpl", "unacademy", "physicswallah",
    "physics wallah", "upgrad", "byju's", "byjus", "vedantu", "cars24", "spinny", "porter", "rapido", "udaan",
    "delhivery", "blinkit", "zepto", "dunzo", "urban company", "oyo", "makemytrip", "ixigo", "cleartrip",
    "navi", "slice", "jupiter", "fi", "fi money", "juspay", "pine labs", "bharatpe", "mobikwik", "khatabook",
    "setu", "perfios", "signzy", "zeta", "cult.fit", "curefit", "healthifyme", "practo", "pharmeasy", "tata 1mg",
    "1mg", "medibuddy", "apna", "scaler", "cuemath", "newton school", "masai", "coding ninjas", "zoho",
    "freshworks", "chargebee", "postman", "hasura", "atlan", "whatfix", "moengage", "clevertap", "innovaccer",
    "yellow.ai", "gupshup", "haptik", "sarvam", "sarvam ai", "krutrim", "zetwerk", "moglix", "ofbusiness",
    "infra.market", "darwinbox", "leadsquared", "zluri", "amagi", "sharechat", "glance", "inmobi", "nanonets",
    "observe.ai", "uniphore", "druva", "browserstack", "zenoti", "icertis", "mindtickle", "capillary",
    "nutanix", "acko", "digit", "go digit", "policybazaar", "zerodha", "upstox", "smallcase", "indmoney",
    "kuku fm", "pocket fm", "dailyhunt", "josh", "meesho", "licious", "country delight", "boat", "mamaearth",
    "sugar", "purplle", "firstcry", "pepperfry", "wakefit", "nobroker", "housing.com", "square yards",
    "cashfree", "razorpayx", "open", "niyo", "kreditbee", "moneyview", "money view", "lendingkart", "axio",
    "refold ai", "sentient", "ema", "supabase", "perplexity", "elevenlabs", "replit", "linear", "ramp",
    "vercel", "mistral ai", "brex", "cohere", "notion", "netradyne", "epifi", "porter",
}

TALENTD_LIST = "https://www.talentd.in/jobs/freshers?role_category=IT%2FSoftware&page={page}"
TALENTD_MAX_PAGES = 8
APPLY_HOST_BLOCKLIST = ("talentd.in", "google", "clarity.ms", "doubleclick", "facebook", "linkedin.com/company",
                        "fleetcode", "naukri.com", "instahyre", "indeed", "glassdoor", "unstop", "internshala")

# --------------------------------------------------------------------------- filters
INDIA_RE = re.compile(
    r"\b(India|IND|Bengaluru|Bangalore|Hyderabad|Chennai|Pune|Mumbai|Gurugram|Gurgaon|Noida|"
    r"New Delhi|Delhi|NCR|Kolkata|Ahmedabad|Kochi|Cochin|Trivandrum|Thiruvananthapuram|Coimbatore|"
    r"Indore|Jaipur|Chandigarh|Mohali|Mysuru|Mysore|Bhubaneswar|Visakhapatnam|Vizag|Nagpur|Vadodara|"
    r"Mangaluru|Mangalore|Hubli|Madurai|Lucknow|Bhopal|Surat|Karnataka|Telangana|Maharashtra|Tamil Nadu|"
    r"Haryana|Uttar Pradesh|Kerala|Gujarat)\b",
    re.I,
)
TECH_RE = re.compile(
    r"\b(software|engineer|developer|development|sde|programmer|data|machine learning|ml|ai|"
    r"analytics|analyst|devops|sre|cloud|platform|backend|back-end|frontend|front-end|full ?stack|"
    r"android|ios|mobile|qa|quality|test|automation|security|firmware|embedded|network|systems?|"
    r"infrastructure|database|dba|technical|technology|information technology|research|scientist|"
    r"computer vision|nlp|llm|genai|generative|administrator|support engineer|application|java|python|"
    r"salesforce|sap|servicenow|power bi|tableau|etl|bi\b|programmer analyst|graduate engineer|get\b)\b",
    re.I,
)
NON_TECH_RE = re.compile(
    r"\b(sales|account executive|account manager|marketing|recruit|recruiter|talent acquisition|hr\b|"
    r"human resources|finance|accountant|accounting|accounts payable|accounts receivable|payroll|legal|counsel|"
    r"paralegal|customer success|customer support|customer service|customer care|procurement|supply chain|"
    r"logistics|warehouse|facilities|administrative assistant|executive assistant|receptionist|nurse|clinical|clin|coord(inator)?|actuar\w*|controllers?|chartered|ca freshers?|product order|order management|"
    r"pharmac|copywriter|content writer|business development|partnerships|category|merchandis|brand|"
    r"community manager|operations associate|ops associate|field (sales|executive)|delivery associate|store|"
    r"retail associate|telecaller|tele-caller|collections|underwrit|insurance|audit|tax|voice process|"
    r"non-voice|chat process|bpo|back office|data entry|production agent|process associate|"
    r"transaction processing|claims|kyc|relationship manager|teacher|tutor|faculty|counsellor|counselor|"
    r"mechanical|civil|electrical engineer|field engineer|project engineer|design engineer|diploma|site engineer|"
    r"service engineer|maintenance|production engineer|quality engineer|process engineer|piping|hvac|cad|"
    r"instrumentation|plant|lab technician|technician)\b",
    re.I,
)
FRESHER_TITLE_RE = re.compile(
    r"\b(new ?grad(uate)?s?|graduate|grad\b|trainee|apprentice|junior|jr\.?|entry[- ]level|early[- ]career|"
    r"early talent|campus|fresher|university|associate|"
    r"sde[- ]?(1|i)\b|engineer[- ]?(1|i)\b|developer[- ]?(1|i)\b|level[- ]?(1|i)\b|analyst[- ]?(1|i)\b|"
    r"(software|data|ml|machine learning|backend|frontend|full ?stack|qa|test|devops|cloud|security|"
    r"platform|systems|firmware|embedded|product) (engineer|developer|scientist|analyst)( i|\b1)?$)",
    re.I,
)
SENIOR_TITLE_RE = re.compile(
    r"\b(senior|sr\.?|staff|lead|principal|manager|director|head|architect|vp|vice president|chief|intermediate|mid[- ]level|executive|advanced|"
    r"distinguished|fellow|specialist|consultant|expert|ii\b|iii\b|iv\b|[2-9]\b|[2-9]\+|"
    r"supervisor|team lead|tech lead|technical lead|mentor|professor|postdoc|phd)\b",
    re.I,
)
INTERN_RE = re.compile(r"\b(intern|interns|internship|co-op|coop|summer analyst)\b", re.I)
DESC_FRESHER_RE = re.compile(
    r"(\b0\s*[-–]\s*[1-3]\s*(\+\s*)?(years?|yrs?)|\b0\s*to\s*[1-3]\s*(years?|yrs?)|\b0\s*\+\s*(years?|yrs?)|"
    r"\bzero to (one|two|three)\b|fresh(ers?| graduates?)|recent graduates?|new graduates?|new college grad|"
    r"graduating in 20(25|26|27)|20(25|26|27) (batch|graduates?|pass[- ]?outs?)|batch of 20(25|26|27)|"
    r"class of 20(25|26|27)|final[- ]year|no (prior|previous|professional) (work )?experience( required| needed| necessary)?|"
    r"entry[- ]level|early[- ]career|campus (hire|hiring|recruit)|university (hire|hiring|recruit|talent)|"
    r"up to (1|2|one|two) years?|less than (2|two) years?|\b(1|one)\s*[-–]\s*(2|two) years?|"
    r"bachelor'?s degree with (0|no)\b|no experience (required|needed|necessary)|experience: ?freshers?)",
    re.I,
)
DESC_SENIOR_RE = re.compile(
    r"\b(minimum|min\.?|at least|requires?|required|must have|with)\s*(of\s*)?([3-9]|1[0-9])\s*\+?\s*(years?|yrs?)|"
    r"\b([3-9]|1[0-9])\s*\+\s*(years?|yrs?)|\b([3-9]|1[0-9])\s*[-–]\s*([4-9]|1[0-9])\s*(years?|yrs?)",
    re.I,
)
MAX_WORKDAY_DETAIL = 30


# --------------------------------------------------------------------------- helpers
def http(url: str, data: dict | None = None, headers: dict | None = None, method: str | None = None):
    h = {"User-Agent": UA, "Accept": "application/json, text/html;q=0.9, */*;q=0.8", "Accept-Language": "en-US,en;q=0.9"}
    if headers:
        h.update(headers)
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.status, r.geturl(), r.read().decode("utf-8", "replace")


def http_json(url, data=None, headers=None):
    return json.loads(http(url, data, headers)[2])


def strip_html(s: str) -> str:
    s = html.unescape(s or "")
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def parse_relative(s: str, today: dt.date) -> dt.date | None:
    s = (s or "").lower()
    if "today" in s or "just now" in s or "hour" in s or "minute" in s:
        return today
    if "yesterday" in s:
        return today - dt.timedelta(days=1)
    m = re.search(r"(\d+)\+?\s*days?", s)
    if m:
        return today - dt.timedelta(days=int(m.group(1)) + (1 if "+" in s else 0))
    return None


def parse_iso(s: str | None) -> dt.date | None:
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


AMBIGUOUS_TITLE_RE = re.compile(
    r"\s*(junior |associate |trainee |graduate |fresher |entry[- ]level )?(analyst|associate|analyst fts|analyst i|analyst 1|trainee|graduate trainee|"
    r"graduate engineer trainee|get|engineer trainee|engineer i|engineer 1|engineer|technology analyst|associate analyst|research analyst|"
    r"operations analyst|business analyst|support analyst)\s*(-|–|\||,)?\s*[\w &/]{0,30}", re.I)
DESC_TECH_RE = re.compile(
    r"\b(python|java\b|javascript|typescript|c\+\+|c#|golang|\.net|sql|nosql|react|angular|node|spring|django|aws|azure|gcp|docker|"
    r"kubernetes|linux|git\b|api|rest\b|microservices|machine learning|deep learning|data science|data engineering|etl|spark|hadoop|"
    r"tableau|power bi|software (development|engineering|testing)|programming|coding|algorithms|data structures|selenium|automation testing|"
    r"devops|ci/cd|cloud|computer science|b\.?tech|b\.?e\b|mca|information technology|html|css|sap\b|servicenow|salesforce|oracle|"
    r"networking|cybersecurity|debugging|unit test|scripting|bash|powershell|excel vba|statistics|modelling|modeling|analytics)\b", re.I)


def classify(title: str, desc: str, include_interns: bool) -> str | None:
    """Return 'fresher' / 'intern' / None."""
    t = title.strip()
    if NON_TECH_RE.search(t) or not TECH_RE.search(t):
        return None
    # generic titles ("Analyst", "Associate - Technology", "Graduate Trainee") must show tech content in the description
    if AMBIGUOUS_TITLE_RE.fullmatch(t) and desc and not DESC_TECH_RE.search(desc):
        return None
    if INTERN_RE.search(t):
        return "intern" if include_interns else None
    if SENIOR_TITLE_RE.search(t):
        return None
    d = desc or ""
    desc_senior = bool(DESC_SENIOR_RE.search(d))
    if desc_senior:
        return None
    if FRESHER_TITLE_RE.search(t) or DESC_FRESHER_RE.search(d):
        return "fresher"
    return None


def snippet(desc: str) -> str:
    m = DESC_FRESHER_RE.search(desc or "")
    if not m:
        return ""
    s, e = max(0, m.start() - 70), min(len(desc), m.end() + 70)
    return ("…" if s else "") + desc[s:e].strip() + ("…" if e < len(desc) else "")


def url_alive(url: str) -> bool:
    """Best-effort liveness check. Bot-walls (403/406) count as alive; 404/410 do not."""
    for method in ("HEAD", "GET"):
        try:
            status, final, body = http(url, method=method, headers={"Accept": "text/html,*/*"})
            if method == "GET" and re.search(r"(job (is )?no longer (available|open)|position (has been )?filled|"
                                             r"this job is closed|no longer accepting applications|job not found)",
                                             body[:200000], re.I):
                return False
            return status < 400
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return False
            if e.code in (403, 405, 406, 429, 503):
                if method == "HEAD" and e.code == 405:
                    continue
                return True
            if method == "HEAD":
                continue
            return False
        except Exception:  # noqa: BLE001
            if method == "HEAD":
                continue
            return True  # network hiccup: don't drop the job for it
    return True


def norm_url(u: str) -> str:
    p = urllib.parse.urlsplit(u.strip())
    q = [kv for kv in urllib.parse.parse_qsl(p.query) if not kv[0].lower().startswith(("utm_", "src", "source", "ref"))]
    return urllib.parse.urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), urllib.parse.urlencode(q), ""))


# --------------------------------------------------------------------------- ATS fetchers
def fetch_workday(name, slug, today, days, include_interns):
    tenant_host, site = slug.split("/", 1)
    tenant = tenant_host.split(".")[0]
    base = f"https://{tenant_host}.myworkdayjobs.com"
    api = f"{base}/wday/cxs/{tenant}/{site}"
    rows, offset, candidates, seen_paths = [], 0, [], set()
    while offset < 200:
        try:
            d = http_json(f"{api}/jobs", {"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": "India"})
        except Exception:  # noqa: BLE001
            if offset == 0:
                raise
            break
        posts = d.get("jobPostings") or []
        if not posts:
            break
        new_paths = 0
        stale = 0
        for p in posts:
            path = p.get("externalPath", "")
            if path in seen_paths:
                continue
            seen_paths.add(path)
            new_paths += 1
            title = p.get("title") or ""
            loc = p.get("locationsText") or ""
            posted = parse_relative(p.get("postedOn", ""), today)
            if posted and (today - posted).days > days:
                stale += 1
                continue
            if not INDIA_RE.search(loc):
                continue
            if NON_TECH_RE.search(title) or not TECH_RE.search(title) or SENIOR_TITLE_RE.search(title):
                continue
            if INTERN_RE.search(title) and not include_interns:
                continue
            candidates.append((title, loc, posted, path))
        if new_paths == 0 or (stale >= len(posts) * 0.8 and offset >= 40):
            break
        offset += 20
    for title, loc, posted, path in candidates[:MAX_WORKDAY_DETAIL]:
        desc, url = "", f"{base}/{site}{path}"
        try:
            info = http_json(f"{api}{path}")["jobPostingInfo"]
            desc = strip_html(info.get("jobDescription", ""))
            loc = info.get("location") or loc
            if info.get("additionalLocations"):
                loc += " / " + " / ".join(info["additionalLocations"])
            posted = parse_iso(info.get("startDate")) or posted
            url = info.get("externalUrl") or url
        except Exception:  # noqa: BLE001
            pass
        kind = classify(title, desc, include_interns)
        if kind:
            rows.append(dict(company=name, title=title, location=loc, posted=posted, url=url, kind=kind,
                             snippet=snippet(desc)))
    return rows


def fetch_greenhouse(name, slug, today, days, include_interns):
    d = http_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    rows = []
    for j in d.get("jobs", []):
        loc = (j.get("location") or {}).get("name", "") or ""
        offices = " / ".join(o.get("name", "") for o in j.get("offices", []) if o.get("name"))
        full_loc = loc or offices
        if not (INDIA_RE.search(full_loc) or INDIA_RE.search(offices)):
            continue
        posted = parse_iso(j.get("first_published")) or parse_iso(j.get("updated_at"))
        if posted and (today - posted).days > days:
            continue
        title = j.get("title", "")
        desc = strip_html(j.get("content", ""))
        kind = classify(title, desc, include_interns)
        if kind:
            rows.append(dict(company=name, title=title, location=full_loc, posted=posted,
                             url=j.get("absolute_url", ""), kind=kind, snippet=snippet(desc)))
    return rows


def fetch_ashby(name, slug, today, days, include_interns):
    d = http_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    rows = []
    for j in d.get("jobs", []):
        locs = [j.get("location", "")] + [s.get("location", "") for s in j.get("secondaryLocations", [])]
        full_loc = " / ".join(x for x in locs if x)
        if not INDIA_RE.search(full_loc):
            continue
        posted = parse_iso(j.get("publishedAt"))
        if posted and (today - posted).days > days:
            continue
        title = j.get("title", "")
        desc = j.get("descriptionPlain") or strip_html(j.get("descriptionHtml", ""))
        kind = classify(title, desc, include_interns)
        if kind:
            rows.append(dict(company=name, title=title, location=full_loc, posted=posted,
                             url=j.get("jobUrl", ""), kind=kind, snippet=snippet(desc)))
    return rows


def fetch_lever(name, slug, today, days, include_interns):
    d = http_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    rows = []
    for j in d if isinstance(d, list) else []:
        cats = j.get("categories") or {}
        full_loc = " / ".join(x for x in [cats.get("location", "")] + (cats.get("allLocations") or []) if x)
        if not INDIA_RE.search(full_loc):
            continue
        posted = dt.datetime.fromtimestamp(j["createdAt"] / 1000, dt.UTC).date() if j.get("createdAt") else None
        if posted and (today - posted).days > days:
            continue
        title = j.get("text", "")
        desc = j.get("descriptionPlain") or strip_html(j.get("description", ""))
        kind = classify(title, desc, include_interns)
        if kind:
            rows.append(dict(company=name, title=title, location=full_loc, posted=posted,
                             url=j.get("hostedUrl", ""), kind=kind, snippet=snippet(desc)))
    return rows


def fetch_workable(name, slug, today, days, include_interns):
    api = f"https://apply.workable.com/api/v3/accounts/{slug}/jobs"
    rows, token, cands = [], None, []
    for _ in range(5):
        body = {"query": "", "location": [], "department": [], "worktype": [], "remote": []}
        if token:
            body["token"] = token
        d = http_json(api, body)
        for j in d.get("results", []):
            loc = " / ".join(x for x in [(j.get("location") or {}).get("city", ""), (j.get("location") or {}).get("country", "")] +
                             [f"{l.get('city', '')} {l.get('country', '')}" for l in j.get("locations", [])] if x and x.strip())
            if not INDIA_RE.search(loc):
                continue
            posted = parse_iso(j.get("published"))
            if posted and (today - posted).days > days:
                continue
            title = j.get("title", "")
            if NON_TECH_RE.search(title) or not TECH_RE.search(title) or SENIOR_TITLE_RE.search(title):
                continue
            if INTERN_RE.search(title) and not include_interns:
                continue
            cands.append((title, loc, posted, j.get("shortcode")))
        token = d.get("nextPage")
        if not token:
            break
    for title, loc, posted, code in cands[:MAX_WORKDAY_DETAIL]:
        desc = ""
        try:
            dd = http_json(f"https://apply.workable.com/api/v2/accounts/{slug}/jobs/{code}")
            desc = strip_html((dd.get("description") or "") + " " + (dd.get("requirements") or ""))
        except Exception:  # noqa: BLE001
            pass
        kind = classify(title, desc, include_interns)
        if kind:
            rows.append(dict(company=name, title=title, location=loc, posted=posted,
                             url=f"https://apply.workable.com/{slug}/j/{code}/", kind=kind, snippet=snippet(desc)))
    return rows


def fetch_smartrecruiters(name, slug, today, days, include_interns):
    rows, cands = [], []
    for offset in range(0, 400, 100):
        d = http_json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100&offset={offset}")
        content = d.get("content", [])
        for j in content:
            loc = " / ".join(x for x in [(j.get("location") or {}).get("city", ""), (j.get("location") or {}).get("country", "")] if x)
            if not INDIA_RE.search(loc) and (j.get("location") or {}).get("country", "").lower() != "in":
                continue
            posted = parse_iso(j.get("releasedDate"))
            if posted and (today - posted).days > days:
                continue
            title = j.get("name", "")
            level = ((j.get("experienceLevel") or {}).get("id") or "").lower()
            if level in ("mid_senior_level", "director", "executive"):
                continue
            if level == "internship" and not include_interns:
                continue
            if NON_TECH_RE.search(title) or not TECH_RE.search(title) or SENIOR_TITLE_RE.search(title):
                continue
            cands.append((title, loc, posted, j.get("id"), level))
        if len(content) < 100:
            break
    for title, loc, posted, jid, level in cands[:MAX_WORKDAY_DETAIL]:
        desc, url = "", f"https://jobs.smartrecruiters.com/{slug}/{jid}"
        try:
            dd = http_json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{jid}")
            secs = (dd.get("jobAd") or {}).get("sections") or {}
            desc = strip_html(" ".join((secs.get(k) or {}).get("text", "") for k in ("jobDescription", "qualifications", "additionalInformation")))
            url = dd.get("applyUrl") or url
        except Exception:  # noqa: BLE001
            pass
        kind = classify(title, desc + (" entry-level" if level == "entry_level" else ""), include_interns)
        if kind:
            rows.append(dict(company=name, title=title, location=loc, posted=posted, url=url, kind=kind, snippet=snippet(desc)))
    return rows


def fetch_oraclecloud(name, slug, today, days, include_interns):
    """Oracle HCM Cloud (Fusion) career sites. slug = 'host/CX_n'."""
    host, site = slug.split("/", 1)
    base = f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
    rows, cands = [], []
    # discover the tenant's "India" location facet id; fall back to keyword search
    sel = "keyword=India"
    try:
        f = http_json(f"{base}?onlyData=true&finder=findReqs;siteNumber={site},facetsList=LOCATIONS,limit=1",
                      headers={"Accept": "application/json"})
        for v in (f.get("items") or [{}])[0].get("locationsFacet") or []:
            if v.get("Name") == "India":
                sel = f"selectedLocationsFacet={v['Id']}"
                break
    except Exception:  # noqa: BLE001
        pass
    for offset in range(0, 300, 50):
        url = (f"{base}?onlyData=true&expand=requisitionList.secondaryLocations&finder=findReqs;siteNumber={site},"
               f"limit=50,offset={offset},sortBy=POSTING_DATES_DESC,{sel}")
        d = http_json(url, headers={"Accept": "application/json"})
        items = (d.get("items") or [{}])[0].get("requisitionList") or []
        stale = 0
        for j in items:
            posted = parse_iso(j.get("PostedDate"))
            if posted and (today - posted).days > days:
                stale += 1
                continue
            locs = [j.get("PrimaryLocation") or ""] + [s.get("Name", "") for s in j.get("secondaryLocations") or []]
            loc = " / ".join(x for x in locs if x)
            if not INDIA_RE.search(loc):
                continue
            title = j.get("Title") or ""
            if NON_TECH_RE.search(title) or not TECH_RE.search(title) or SENIOR_TITLE_RE.search(title):
                continue
            cands.append((title, locs[0], posted, j.get("Id"), j.get("ShortDescriptionStr") or ""))
        if len(items) < 50 or stale > len(items) * 0.8:
            break
    for title, loc, posted, jid, short in cands[:MAX_WORKDAY_DETAIL]:
        desc, url = short, f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{jid}"
        try:
            dd = http_json(f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
                           f"?expand=all&onlyData=true&finder=ById;Id=%22{jid}%22,siteNumber={site}",
                           headers={"Accept": "application/json"})
            it = (dd.get("items") or [{}])[0]
            desc = strip_html(" ".join(str(it.get(k) or "") for k in ("ExternalDescriptionStr", "ExternalQualificationsStr", "ExternalResponsibilitiesStr")))
        except Exception:  # noqa: BLE001
            pass
        kind = classify(title, desc, include_interns)
        if kind:
            rows.append(dict(company=name, title=title, location=loc, posted=posted, url=url, kind=kind, snippet=snippet(desc)))
    return rows


SF_DATE_RE = re.compile(r'class="jobDate[^"]*">\s*([A-Z][a-z]{2} \d{1,2}, \d{4})')


def fetch_successfactors(name, slug, today, days, include_interns):
    """SAP SuccessFactors Recruiting Marketing (RMK) career sites. slug = host, e.g. 'careers.ey.com'."""
    rows, cands = [], []
    for start in range(0, 150, 25):
        _, _, body = http(f"https://{slug}/search/?q=&locationsearch=India&sortColumn=referencedate&sortDirection=desc&startrow={start}",
                          headers={"Accept": "text/html"})
        tiles = re.split(r'<tr class="data-row', body)[1:]
        stale = 0
        for t in tiles:
            m = re.search(r'<a (?:[^>]*?class="jobTitle-link"[^>]*?href="([^"]+)"|href="([^"]+)"[^>]*?class="jobTitle-link")[^>]*>(.*?)</a>', t, re.S)
            if not m:
                continue
            path, title = (m.group(1) or m.group(2)), strip_html(m.group(3))
            dm = SF_DATE_RE.search(t)
            posted = None
            if dm:
                try:
                    posted = dt.datetime.strptime(dm.group(1), "%b %d, %Y").date()
                except ValueError:
                    posted = None
            if posted and (today - posted).days > days:
                stale += 1
                continue
            lm = re.search(r'class="jobLocation[^"]*">\s*(?:<span[^>]*>)?\s*([^<]+)', t)
            if not dm and start >= 50:   # no dates in listing: only look at the first two pages
                stale += 1
            loc = strip_html(lm.group(1)) if lm else ""
            if loc and not INDIA_RE.search(loc) and not re.search(r",\s*IN\b", loc):
                continue
            if NON_TECH_RE.search(title) or not TECH_RE.search(title) or SENIOR_TITLE_RE.search(title):
                continue
            cands.append((title, loc, posted, urllib.parse.urljoin(f"https://{slug}/", html.unescape(path))))
        if not tiles or stale > len(tiles) * 0.8:
            break
    for title, loc, posted, url in cands[:MAX_WORKDAY_DETAIL]:
        desc = ""
        try:
            _, _, body = http(url, headers={"Accept": "text/html"})
            m = re.search(r'<span class="jobdescription">(.*?)</span>\s*</div>', body, re.S) or re.search(r'class="job">(.*?)<div class="jobApply', body, re.S)
            desc = strip_html(m.group(1)) if m else strip_html(body)[:4000]
            if not posted:
                pm = re.search(r'"datePosted"\s*:\s*"(\d{4}-\d{2}-\d{2})', body)
                posted = parse_iso(pm.group(1)) if pm else None
                if posted and (today - posted).days > days:
                    continue
        except Exception:  # noqa: BLE001
            pass
        kind = classify(title, desc, include_interns)
        if kind:
            rows.append(dict(company=name, title=title, location=loc, posted=posted, url=url, kind=kind, snippet=snippet(desc)))
    return rows


FETCHERS = {"workday": fetch_workday, "greenhouse": fetch_greenhouse, "ashby": fetch_ashby, "lever": fetch_lever,
            "workable": fetch_workable, "smartrecruiters": fetch_smartrecruiters,
            "oraclecloud": fetch_oraclecloud, "successfactors": fetch_successfactors}


# --------------------------------------------------------------------------- Talentd layer
SKIP_SLUG_RE = re.compile(r"^(tags|freshers|internships|skills|companies|jobs-in-.*|.*-jobs)$")


def talentd_list(today, days):
    """Yield (slug, approx_date) for IT/Software fresher cards within the window."""
    out, seen = [], set()
    for page in range(1, TALENTD_MAX_PAGES + 1):
        try:
            _, _, body = http(TALENTD_LIST.format(page=page), headers={"Accept": "text/html"})
        except Exception:  # noqa: BLE001
            break
        cards = re.split(r'(?=<a[^>]+href="/jobs/[a-z0-9\-]+")', body)
        page_old = 0
        for c in cards:
            m = re.match(r'<a[^>]+href="/jobs/([a-z0-9\-]+)"', c)
            if not m or SKIP_SLUG_RE.match(m.group(1)) or m.group(1) in seen:
                continue
            text = strip_html(c[:4000])
            m2 = re.search(r"(\d+\s*(hours?|days?|minutes?)\s*ago|just now)", text, re.I)
            when = parse_relative(m2.group(0), today) if m2 else None
            if when and (today - when).days > days:
                page_old += 1
                continue
            seen.add(m.group(1))
            out.append((m.group(1), when))
        if page_old and page_old >= 8:
            break
    return out


def talentd_detail(slug, today, days, include_interns):
    url = f"https://www.talentd.in/jobs/{slug}"
    try:
        _, _, body = http(url, headers={"Accept": "text/html"})
    except Exception:  # noqa: BLE001
        return None
    if re.search(r"stopped taking applications|Applications closed|apply link no longer works", body, re.I):
        return None
    jp = None
    for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', body, re.S):
        try:
            d = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        graph = d.get("@graph", [d]) if isinstance(d, dict) else []
        for g in graph:
            if isinstance(g, dict) and g.get("@type") == "JobPosting":
                jp = g
    if not jp:
        return None
    posted = parse_iso(jp.get("datePosted"))
    if posted and (today - posted).days > days:
        return None
    company = (jp.get("hiringOrganization") or {}).get("name", "") or ""
    title = re.sub(r"\s*\|.*$", "", jp.get("title", ""))
    title = re.sub(r"^(.*?)\b(is )?hiring\b\s*", "", title, flags=re.I) if re.search(r"\bhiring\b", title, re.I) else title
    title = re.sub(r"\s*\((?:Bangalore|Bengaluru|Hyderabad|Chennai|Pune|Mumbai|Gurgaon|Gurugram|Noida|Delhi|Kolkata|Multiple Cities)[^)]*\)", "", title, flags=re.I)
    title = re.sub(r"\s+(in|at)\s+(Bangalore|Bengaluru|Hyderabad|Chennai|Pune|Mumbai|Gurgaon|Gurugram|Noida|Delhi|Kolkata|India|Multiple Cities|Lucknow|Uttar Pradesh|Gautam Buddha Nagar)\b.*$", "", title, flags=re.I)
    title = re.sub(r"\s*[-–|,]?\s*(Apply Now|Apply by .*|Job at .*|Job ID.*|Freshers( Eligible)?|\d{4} Batch|₹.*LPA.*|Hybrid( Role)?|Remote)$", "", title, flags=re.I)
    title = re.sub(r"\s*,?\s*(Bangalore|Bengaluru|Hyderabad|Chennai|Pune|Mumbai|Gurgaon|Gurugram|Noida|Delhi|Kolkata|Lucknow)$", "", title, flags=re.I)
    title = re.sub(r"^(" + re.escape(company) + r")\s+", "", title, flags=re.I).strip(" -–|,")
    locs = []
    for pl in jp.get("jobLocation", []) or []:
        a = (pl or {}).get("address", {}) or {}
        locs.append(a.get("addressLocality") or a.get("addressRegion") or "")
    location = " / ".join(x for x in locs if x) or "India"
    desc = strip_html(jp.get("description", ""))
    page_text = strip_html(re.sub(r"<script.*?</script>", "", body, flags=re.S))
    exp_m = re.search(r"Experience\s+(Freshers|0\s*[-–]\s*\d\s*years?|\d\s*[-–]\s*\d\s*years?)", page_text, re.I)
    experience = exp_m.group(1) if exp_m else ""
    if experience and not re.match(r"(Freshers|0)", experience, re.I):
        return None
    size_m = re.search(r"Size\s+([\d,]+\+?|[\d,]+\s*[-–]\s*[\d,]+)\s*people", page_text)
    size = size_m.group(1).replace(",", "") if size_m else ""
    big = size.endswith("+") or (size.isdigit() and int(size) >= 1000) or bool(re.match(r"\d+\s*[-–]\s*(\d{4,})", size))
    tier = "startup" if company.lower() in STARTUP_NAMES or not big else "mnc"
    am = re.search(r'<a[^>]+class="[^"]*\bapply\b[^"]*"[^>]+href="(https?://[^"]+)"', body) or \
         re.search(r'<a[^>]+href="(https?://[^"]+)"[^>]+class="[^"]*\bapply\b[^"]*"', body)
    apply_url = am.group(1) if am else ""
    if not apply_url:
        for m in re.finditer(r'href="(https?://[^"]+)"', body):
            u = m.group(1)
            if not any(b in u for b in APPLY_HOST_BLOCKLIST):
                apply_url = u
                break
    if not apply_url or any(b in apply_url for b in APPLY_HOST_BLOCKLIST):
        return None
    apply_url = html.unescape(apply_url)
    kind = classify(title, desc + " " + ("Experience: Freshers" if experience else ""), include_interns)
    if not kind:
        return None
    salary = ""
    bs = jp.get("baseSalary", {}).get("value", {}) if isinstance(jp.get("baseSalary"), dict) else {}
    if bs.get("minValue") and bs.get("maxValue"):
        lo, hi = bs["minValue"] / 1e5, bs["maxValue"] / 1e5
        salary = (f"₹{lo:g} LPA" if lo == hi else f"₹{lo:g}–{hi:g} LPA") + " (as listed)"
    batch_m = re.search(r"Takes batch ([\d, ]+)", page_text)
    return dict(company=company, title=title, location=location, posted=posted, url=apply_url, kind=kind,
                tier=tier, source="talentd", snippet=snippet(desc), salary=salary,
                batch=batch_m.group(1).strip() if batch_m else "", via=url)


def fetch_talentd(today, days, include_interns, verify=True):
    slugs = talentd_list(today, days)
    rows = []
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for r in ex.map(lambda s: talentd_detail(s[0], today, days, include_interns), slugs):
            if r:
                rows.append(r)
    if verify:
        with cf.ThreadPoolExecutor(max_workers=8) as ex:
            alive = list(ex.map(lambda r: url_alive(r["url"]), rows))
        rows = [r for r, ok in zip(rows, alive) if ok]
    return rows, len(slugs)


# --------------------------------------------------------------------------- LinkedIn guest layer
# Public, login-free endpoints LinkedIn serves to logged-out visitors. We use them for discovery,
# then read the job's own detail page for the description, seniority and (when the company set one)
# the external apply URL. Company headcount comes from the company page and is cached.
LI_SEARCH = ("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
             "?keywords={kw}&location=India&f_TPR=r{secs}{extra}&start={start}")
LI_DETAIL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{jid}"
LI_QUERIES = [
    ("software engineer", "&f_E=2"), ("software developer", "&f_E=2"), ("associate software engineer", ""),
    ("sde 1", ""), ("software engineer i", ""), ("graduate engineer trainee", ""), ("fresher software", ""),
    ("junior developer", ""), ("backend developer", "&f_E=2"), ("frontend developer", "&f_E=2"),
    ("full stack developer", "&f_E=2"), ("data analyst", "&f_E=2"), ("data engineer", "&f_E=2"),
    ("machine learning engineer", "&f_E=2"), ("qa engineer", "&f_E=2"), ("devops engineer", "&f_E=2"),
    ("python developer", "&f_E=2"), ("java developer", "&f_E=2"), ("2026 batch", ""), ("new grad engineer", ""),
]
LI_PAGES = 3
LI_MAX_DETAIL = 140
STAFFING_RE = re.compile(r"\b(staffing|manpower|recruit\w*|placement|consultan(ts?|cy|cies)|hr services|talent\w*|"
                         r"outsourc\w*|hiring|jobs|careers|workforce|headhunt\w*|search partners|opportunities|"
                         r"global solutions|infosystem)\b", re.I)
LI_MIN_STARTUP_SIZE = 15
COMPANY_CACHE = OUT_DIR / "companies.json"
_company_cache: dict = {}


def li_get(url, tries=3):
    delay = 2.0
    for i in range(tries):
        try:
            return http(url, headers={"Accept": "text/html,*/*"})[2]
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and i < tries - 1:
                import time
                time.sleep(delay)
                delay *= 2
                continue
            raise


def li_search(days):
    secs = days * 86400
    seen, cards = set(), []
    for kw, extra in LI_QUERIES:
        for page in range(LI_PAGES):
            try:
                body = li_get(LI_SEARCH.format(kw=urllib.parse.quote(kw), secs=secs, extra=extra, start=page * 10))
            except Exception:  # noqa: BLE001
                break
            found = 0
            for c in re.findall(r"<li>(.*?)</li>", body, re.S):
                jid = re.search(r'urn:li:jobPosting:(\d+)', c)
                if not jid or jid.group(1) in seen:
                    continue
                title = re.search(r'class="base-search-card__title">\s*(.*?)\s*</h3>', c, re.S)
                comp = re.search(r'class="base-search-card__subtitle">(.*?)</h4>', c, re.S)
                loc = re.search(r'class="job-search-card__location">\s*(.*?)\s*</span>', c, re.S)
                when = re.search(r'datetime="([^"]+)"', c)
                curl = re.search(r'href="(https://[a-z]+\.linkedin\.com/company/[^"?]+)', c)
                found += 1
                t = html.unescape(title.group(1)) if title else ""
                if not t or NON_TECH_RE.search(t) or not TECH_RE.search(t) or SENIOR_TITLE_RE.search(t):
                    continue
                seen.add(jid.group(1))
                cards.append(dict(jid=jid.group(1), title=t, company=strip_html(comp.group(1)) if comp else "",
                                  location=html.unescape(loc.group(1)) if loc else "",
                                  posted=parse_iso(when.group(1)) if when else None,
                                  company_url=curl.group(1) if curl else ""))
            if found < 10:
                break
    return cards


def li_company_size(name, url):
    key = name.lower().strip()
    if key in _company_cache:
        return _company_cache[key]
    size = None
    if url:
        try:
            body = li_get(url, tries=1)
            m = re.search(r'"numberOfEmployees":\{"value":(\d+)', body) or re.search(r'([\d,]+)\+?\s*employees', body)
            if m:
                size = int(m.group(1).replace(",", ""))
        except Exception:  # noqa: BLE001
            pass
    _company_cache[key] = size
    return size


def li_detail(card, include_interns):
    try:
        body = li_get(LI_DETAIL.format(jid=card["jid"]), tries=2)
    except Exception:  # noqa: BLE001
        return None
    crit = dict(re.findall(r'description__job-criteria-subheader">\s*(.*?)\s*</h3>\s*<span[^>]*>\s*(.*?)\s*</span>', body, re.S))
    seniority = html.unescape(crit.get("Seniority level", "")).lower()
    if seniority in ("mid-senior level", "director", "executive"):
        return None
    if seniority == "internship" and not include_interns:
        return None
    dm = re.search(r'class="show-more-less-html__markup[^"]*"[^>]*>(.*?)</div>', body, re.S)
    desc = strip_html(dm.group(1)) if dm else ""
    kind = classify(card["title"], desc + (" entry-level" if seniority == "entry level" else ""), include_interns)
    if not kind:
        return None
    am = re.search(r'<code id="applyUrl"[^>]*>\s*<!--\s*"?(https?://[^"\s]+)"?\s*-->', body)
    apply_url = html.unescape(am.group(1)) if am else f"https://www.linkedin.com/jobs/view/{card['jid']}/"
    if am:
        # LinkedIn wraps external applies in a redirector; unwrap it when possible
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(apply_url).query)
        if "url" in q:
            apply_url = q["url"][0]
    cu = re.search(r'href="(https://[a-z]+\.linkedin\.com/company/[^"?]+)', body)
    return dict(company=card["company"], title=card["title"], location=card["location"], posted=card["posted"],
                url=apply_url, kind=kind, source="linkedin", snippet=snippet(desc), salary="", batch="",
                via=f"https://www.linkedin.com/jobs/view/{card['jid']}/", company_url=cu.group(1) if cu else card["company_url"])


def fetch_linkedin(today, days, include_interns, verify=True):
    global _company_cache
    if COMPANY_CACHE.exists():
        _company_cache = json.loads(COMPANY_CACHE.read_text())
    cards = li_search(days)
    cards = [c for c in cards if not STAFFING_RE.search(c["company"])]
    cards.sort(key=lambda c: -(c["posted"].toordinal() if c["posted"] else 0))
    rows = []
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        for r in ex.map(lambda c: li_detail(c, include_interns), cards[:LI_MAX_DETAIL]):
            if r:
                rows.append(r)
    for r in rows:
        name = r["company"].lower()
        size = li_company_size(r["company"], r["company_url"])
        r["size"] = size
        r["tier"] = "startup" if name in STARTUP_NAMES or (size is not None and size < 2000) else "mnc"
    rows = [r for r in rows if r["company"].lower() in STARTUP_NAMES or r["size"] is None or r["size"] >= LI_MIN_STARTUP_SIZE]
    COMPANY_CACHE.write_text(json.dumps(_company_cache, indent=0, sort_keys=True))
    if verify:
        ext = [r for r in rows if "linkedin.com" not in r["url"]]
        with cf.ThreadPoolExecutor(max_workers=8) as ex:
            alive = dict(zip([id(r) for r in ext], ex.map(lambda r: url_alive(r["url"]), ext)))
        rows = [r for r in rows if alive.get(id(r), True)]
    return rows, len(cards)


# --------------------------------------------------------------------------- main
QUALITY_RE = re.compile(r"\b(software|sde|developer|engineer|data|machine learning|ml|ai|devops|cloud|backend|frontend|"
                        r"full ?stack|qa|test|security|firmware|embedded|scientist)\b", re.I)
LOW_RE = re.compile(r"\b(administrator|support|service desk|help ?desk|production support|desk ?side|l0|l1|analyst)\b", re.I)


def quality(r) -> int:
    s = 0
    if QUALITY_RE.search(r["title"]):
        s += 2
    if LOW_RE.search(r["title"]):
        s -= 2
    if r.get("salary"):
        s += 1
    if r.get("source") in ("workday", "greenhouse", "ashby", "lever", "smartrecruiters", "workable", "oraclecloud", "successfactors"):
        s += 1
    if "linkedin.com" in r.get("url", ""):
        s -= 1
    if r["company"].lower() in STARTUP_NAMES:
        s += 2
    size = r.get("size")
    if size is not None and 50 <= size <= 5000:
        s += 1
    return s
