"""
Minimal control panel (stdlib only): `python -m jobs_worker web` → http://127.0.0.1:8787

  Scrape        runs the full pipeline for today (same code path as cron); appends only never-published rows
  Hide / Unhide drop a row from the post without losing the "already seen" record
  Post text     ready-to-paste plain text for the community, regenerated from the DB on every load
  Probe         per-source health
"""
from __future__ import annotations

import collections
import datetime as dt
import html
import json
import logging
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config as C
from . import pipeline, store

LOG = collections.deque(maxlen=400)
STATE = {"running": False, "task": "", "started": None, "error": ""}
_lock = threading.Lock()


class _Handler(logging.Handler):
    def emit(self, record):
        LOG.append(f"{dt.datetime.now().strftime('%H:%M:%S')} {record.getMessage()}")


def _start(task, fn):
    with _lock:
        if STATE["running"]:
            return False
        STATE.update(running=True, task=task, started=dt.datetime.now().isoformat(timespec="seconds"), error="")

    def body():
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            STATE["error"] = f"{type(e).__name__}: {e}"
            LOG.append(f"ERROR {STATE['error']}")
        finally:
            STATE["running"] = False
            STATE["task"] = ""

    threading.Thread(target=body, daemon=True).start()
    return True


def _scrape(day):
    LOG.append(f"scrape started for {day}")
    res = pipeline.run_once(day, notify=False)
    LOG.append(f"scrape done: +{len(res['payload']['mnc'])} MNC, +{len(res['payload']['startups'])} startups, "
               f"{len(res['errors'])} source errors")


def _probe():
    LOG.append("probe started")
    rows, errors, health = pipeline.collect(dt.date.today(), verify=False)
    for name, kind, slug, n, err in sorted(health, key=lambda h: (bool(h[4]), h[0])):
        LOG.append(f"{'ERR ' if err else 'ok  '} {name:22s} {kind:11s} {err or f'{n} hits'}")
    LOG.append(f"probe done: {sum(1 for h in health if not h[4])}/{len(health)} sources ok, {len(rows)} candidates")


def post_text(rows, day: dt.date) -> str:
    out = [f"Fresher tech openings — {day.strftime('%d %b %Y')}", ""]
    for tier, label in (("mnc", "MNC"), ("startup", "Startups")):
        items = [r for r in rows if r["tier"] == tier]
        out.append(f"{label} ({len(items)})")
        for i, r in enumerate(items, 1):
            bits = [r["location"] or "India"]
            if r.get("salary"):
                bits.append(r["salary"].replace(" (as listed)", ""))
            if r.get("batch"):
                bits.append(f"batch {r['batch']}")
            out.append(f"{i}. {r['company']} – {r['title']} · {' · '.join(bits)}")
            out.append(f"   {r['url']}")
        out.append("")
    return "\n".join(out)


PAGE = """<!doctype html><meta charset=utf-8><title>jobs-worker</title>
<style>
body{font:14px/1.4 -apple-system,system-ui,sans-serif;margin:0;background:#f6f7f9;color:#111}
header{display:flex;gap:12px;align-items:center;padding:12px 20px;background:#fff;border-bottom:1px solid #ddd;position:sticky;top:0}
button{padding:7px 14px;border:1px solid #bbb;border-radius:6px;background:#fff;cursor:pointer}
button.primary{background:#111;color:#fff;border-color:#111}button:disabled{opacity:.5;cursor:default}
select{padding:6px}main{display:grid;grid-template-columns:1fr 420px;gap:16px;padding:16px 20px}
h2{font-size:15px;margin:18px 0 8px}table{width:100%;border-collapse:collapse;background:#fff}
td{padding:6px 8px;border-top:1px solid #eee;vertical-align:top}tr.hidden td{opacity:.4;text-decoration:line-through}
td.n{width:24px;color:#888}td.a{width:70px;text-align:right}a{color:#0645ad;text-decoration:none}
.small{color:#666;font-size:12px}pre{background:#111;color:#ddd;padding:10px;font-size:11px;height:260px;overflow:auto;margin:0;border-radius:6px}
textarea{width:100%;height:420px;font:12px/1.4 ui-monospace,monospace;padding:8px;box-sizing:border-box}
#status{color:#666}aside{position:sticky;top:60px;align-self:start}
td div.small a{word-break:break-all}
@media(max-width:1000px){main{grid-template-columns:1fr}aside{position:static}textarea{height:260px}}
</style>
<header>
  <strong>jobs-worker</strong>
  <select id=day></select>
  <button class=primary id=scrape>Scrape</button>
  <button id=probe>Probe sources</button>
  <span id=status></span>
</header>
<main>
<section id=list></section>
<aside>
  <h2 style="margin-top:0">Post text <button id=copy>Copy</button></h2>
  <textarea id=post readonly></textarea>
  <h2>Log</h2><pre id=log></pre>
</aside>
</main>
<script>
const $=s=>document.querySelector(s);let day=null,busy=false;
let token=localStorage.getItem('admin_token')||'';
function hdr(){return token?{'X-Admin-Token':token}:{}}
async function j(u,o){const r=await fetch(u,o);return r.json()}
async function post(u,body){let r=await fetch(u,{method:'POST',headers:hdr(),body:JSON.stringify(body||{})});
 if(r.status===401){token=prompt('Admin token')||'';localStorage.setItem('admin_token',token);r=await fetch(u,{method:'POST',headers:hdr(),body:JSON.stringify(body||{})});}
 return r}
async function loadDays(){const d=await j('/api/days');const t=new Date().toISOString().slice(0,10);if(!d.includes(t))d.unshift(t);
 $('#day').innerHTML=d.map(x=>`<option>${x}</option>`).join('');if(!day||!d.includes(day))day=d[0];$('#day').value=day}
async function load(){const d=await j('/api/day?date='+day);const g={mnc:[],startup:[]};d.rows.forEach(r=>g[r.tier]?.push(r));
 let h='';for(const [k,l] of [['mnc','MNC'],['startup','Startups']]){const vis=g[k].filter(r=>!r.hidden).length;
  h+=`<h2>${l} <span class=small>${vis} shown / ${g[k].length} scraped</span></h2><table>`;
  g[k].forEach((r,i)=>{h+=`<tr class="${r.hidden?'hidden':''}"><td class=n>${i+1}</td><td><b>${esc(r.company)}</b> – ${esc(r.title)}
   <div class=small>${esc(r.location||'')} · posted ${r.posted||'n/a'} · ${r.source}${r.salary?' · '+esc(r.salary):''}${r.batch?' · batch '+esc(r.batch):''}</div>
   <div class=small><a href="${r.url}" target=_blank>${r.url}</a></div></td>
   <td class=a><button onclick="hide('${r.url_key.replace(/'/g,"\\\\'")}',${r.hidden?0:1})">${r.hidden?'Unhide':'Hide'}</button></td></tr>`});
  h+='</table>'}
 $('#list').innerHTML=h||'<p class=small>Nothing for this day yet. Click Scrape.</p>';$('#post').value=d.post}
async function hide(k,v){await post('/api/hide',{url_key:k,hidden:v});load()}
async function status(){const s=await j('/api/status');$('#log').textContent=s.log.join('\\n');$('#log').scrollTop=1e9;
 $('#scrape').disabled=$('#probe').disabled=s.running;$('#status').textContent=s.running?`running ${s.task}… (since ${s.started.slice(11,16)})`:(s.error||'idle');
 if(busy&&!s.running){busy=false;await loadDays();load()}busy=s.running}
function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
$('#scrape').onclick=async()=>{await post('/api/scrape',{date:day});busy=true;status()};
$('#probe').onclick=async()=>{await post('/api/probe');busy=true;status()};
$('#copy').onclick=()=>{navigator.clipboard.writeText($('#post').value);$('#copy').textContent='Copied';setTimeout(()=>$('#copy').textContent='Copy',1200)};
$('#day').onchange=e=>{day=e.target.value;load()};
loadDays().then(load);status();setInterval(status,2000);
</script>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else (json.dumps(body, default=str) if ctype == "application/json" else body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path == "/":
            return self._send(200, PAGE, "text/html")
        if u.path == "/api/status":
            return self._send(200, {**STATE, "log": list(LOG)})
        con = store.connect()
        try:
            if u.path == "/api/days":
                return self._send(200, store.days(con))
            if u.path == "/api/day":
                day = q.get("date", [dt.date.today().isoformat()])[0]
                rows = store.day_rows(con, day, include_hidden=True)
                visible = [r for r in rows if not r["hidden"]]
                return self._send(200, {"rows": rows, "post": post_text(visible, dt.date.fromisoformat(day))})
            if u.path == "/api/post":
                day = q.get("date", [dt.date.today().isoformat()])[0]
                return self._send(200, post_text(store.day_rows(con, day), dt.date.fromisoformat(day)), "text/plain")
        finally:
            con.close()
        self._send(404, {"error": "not found"})

    def _authorized(self):
        if not C.ADMIN_TOKEN:
            return True
        return self.headers.get("X-Admin-Token", "") == C.ADMIN_TOKEN

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if not self._authorized():
            return self._send(401, {"error": "admin token required"})
        if u.path == "/api/scrape":
            day = dt.date.fromisoformat(self._body().get("date") or dt.date.today().isoformat())
            ok = _start("scrape", lambda: _scrape(day))
            return self._send(202 if ok else 409, {"started": ok})
        if u.path == "/api/probe":
            ok = _start("probe", _probe)
            return self._send(202 if ok else 409, {"started": ok})
        if u.path == "/api/hide":
            b = self._body()
            con = store.connect()
            try:
                store.set_hidden(con, b["url_key"], bool(b.get("hidden", 1)))
            finally:
                con.close()
            return self._send(200, {"ok": True})
        self._send(404, {"error": "not found"})


def serve_web(host="127.0.0.1", port=8787):
    logging.getLogger("jobs_worker").addHandler(_Handler())
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"jobs-worker UI → http://{host}:{port}   (data: {C.DATA_DIR})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
