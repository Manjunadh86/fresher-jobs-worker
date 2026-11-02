# fresher-jobs-worker

Scrapes fresh **fresher tech openings in India** every day from employer career portals and job platforms,
filters them deterministically (no LLMs), and publishes a digest of **10 MNC + 10–15 startup** roles that
have never been posted before. Pure Python, stdlib-only worker, SQLite state, Streamlit front end.

**Live app:** deploy on Streamlit Community Cloud (steps below). **Daily run:** GitHub Actions, 08:30 IST.

## Sources

| Layer | What | How |
|---|---|---|
| Employer portals | ~160 companies' own career sites | Public ATS APIs: Workday, Greenhouse, Ashby, Lever, Workable, SmartRecruiters, **Oracle HCM Cloud**, **SAP SuccessFactors** (`engine.SOURCES`) |
| Talentd | Curated fresher feed | Listing → JSON-LD detail → official apply link |
| LinkedIn | Guest job search, entry level, India | 20 queries × 3 pages; company headcount → MNC/startup tier |
| Unstop | `usertype=fresher` jobs API | Salary, location, approved date |
| Internshala | Fresher + 10 tech category listings | Card parse + detail page |
| Adzuna (optional) | Aggregator API | Set `ADZUNA_APP_ID/KEY` (free at developer.adzuna.com) |

Every row goes through the same filters: India location, tech title (generic titles like "Analyst" must show
tech content in the description), non-tech / senior / staffing-agency exclusion, fresher signals, dedupe by URL and
(company, title, location), quality score. Every apply URL is checked live. A posting is published at most once.

## Run locally

```bash
python -m jobs_worker run       # one shot → data/<date>.md, .csv, SQLite
python -m jobs_worker probe     # per-source health
python -m jobs_worker web       # minimal control panel at :8787
python -m jobs_worker serve     # built-in daily scheduler (Docker / systemd)

pip install -r requirements.txt && streamlit run app.py   # the public UI
```

## Host it for everyone (free, no server)

**1. Daily scrape — GitHub Actions** (already in `.github/workflows/daily.yml`)
Runs at 08:30 IST, commits `data/` back to the repo. Add optional secrets under *Settings → Secrets → Actions*:
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `DISCORD_WEBHOOK_URL`, `SLACK_WEBHOOK_URL`, `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`.
Trigger the first run manually: *Actions → daily-fresher-jobs → Run workflow*.

**2. Public UI — Streamlit Community Cloud**
1. Go to https://share.streamlit.io → *Create app* → *Deploy a public app from GitHub*.
2. Repository: this repo · Branch: `main` · Main file path: `app.py`.
3. *Advanced settings → Secrets*, paste:
   ```toml
   ADMIN_TOKEN = "choose-a-long-random-string"
   ```
   Without it anyone can press **Scrape now** / **Hide**. Everything else is read-only for visitors.
4. Deploy. The app redeploys automatically whenever the Action commits new data.

Visitors get: day picker, search, tier filter, every job with its official link, ready-to-paste post text, CSV download.
Admins (token) additionally get **Scrape now** and **Hide from post**.

**Why not Vercel?** A scrape takes 2–4 minutes and needs a writable SQLite file; Vercel functions time out at 10–60 s
and have no persistent disk. Streamlit Cloud + Actions fits the workload with zero infra.

### Other deployment options

- Docker: `docker compose up -d --build` (runs `serve`, `restart: unless-stopped`)
- Host cron: `deploy/crontab.example` · systemd: `deploy/jobs-worker.service` · macOS launchd: `deploy/*.plist`

## Configuration

See `.env.example`. Key knobs: `MNC_DAYS` (3), `STARTUP_DAYS` (10), `MNC_COUNT` (10), `STARTUP_MIN/MAX` (10/15),
`INCLUDE_INTERNS`, `VERIFY_LINKS`, per-source `ENABLE_*`, `ADMIN_TOKEN`.

## Layout

```
app.py             Streamlit UI (public)
jobs_worker/
  config.py        env → settings
  engine.py        HTTP, filters, ATS fetchers (8 systems), Talentd, LinkedIn, quality score
  platforms.py     Unstop, Internshala, Adzuna
  pipeline.py      collect → select → render → run_once
  store.py         SQLite (jobs, runs, digests)
  notify.py        Telegram / Discord / Slack / generic webhook
  scheduler.py     serve loop
  web.py           stdlib control panel
  __main__.py      CLI
.github/workflows/daily.yml
deploy/            crontab, systemd, launchd, publish.sh
```

## Adding a company portal

Append to `engine.SOURCES`: `("Company", "<workday|greenhouse|ashby|lever|workable|smartrecruiters|oraclecloud|successfactors>", "<slug>", "<mnc|startup>")`
and check with `python -m jobs_worker probe`.
Slug formats: Workday `tenant.wd5/SiteName` · Oracle `host.fa.ocs.oraclecloud.com/CX_1` · SuccessFactors `careers.company.com` · others: board slug.
