import json
import logging
import os
import threading
import uuid

from flask import Flask, request, jsonify, render_template_string

from . import bandcamp, db

log = logging.getLogger("camparr.web")

app = Flask(__name__)

manual_jobs = {}
_state = {"last_poll": None, "next_poll": None, "status": "idle", "cycle_results": None}


def set_state(**kw):
    _state.update(kw)


HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Camparr</title>
<style>
  *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
  body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;background:#0a0a0a;color:#e0e0e0;min-height:100vh}
  .container{max-width:860px;margin:0 auto;padding:1.5rem 1rem}
  h1{font-size:1.5rem;font-weight:600;margin-bottom:.3rem;color:#fff}
  h1 span{color:#1da0c3}
  .subtitle{color:#666;font-size:.85rem;margin-bottom:1.5rem}
  .stats{display:flex;gap:1rem;margin-bottom:1.5rem;flex-wrap:wrap}
  .stat{background:#151515;border:1px solid #222;border-radius:8px;padding:.7rem 1rem;flex:1;min-width:120px}
  .stat-val{font-size:1.3rem;font-weight:700;color:#1da0c3}
  .stat-label{font-size:.75rem;color:#666;margin-top:.15rem}
  .status-bar{background:#151515;border:1px solid #222;border-radius:8px;padding:.7rem 1rem;margin-bottom:1.5rem;display:flex;justify-content:space-between;align-items:center;font-size:.85rem}
  .status-dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:.4rem}
  .dot-idle{background:#666}.dot-polling{background:#f0b429}.dot-searching{background:#1da0c3}.dot-downloading{background:#2ea043}.dot-error{background:#da3633}
  section{margin-bottom:1.5rem}
  h2{font-size:1.05rem;color:#aaa;margin-bottom:.75rem;font-weight:500}
  .manual{display:flex;gap:.5rem;margin-bottom:1.5rem}
  .manual input{flex:1;padding:.55rem .75rem;border:1px solid #333;border-radius:6px;background:#151515;color:#e0e0e0;font-size:.9rem;outline:none}
  .manual input:focus{border-color:#1da0c3}
  .manual input::placeholder{color:#555}
  .manual button{padding:.55rem 1rem;border:none;border-radius:6px;background:#1da0c3;color:#fff;font-size:.9rem;font-weight:500;cursor:pointer}
  .manual button:hover{background:#1ab4db}
  table{width:100%;border-collapse:collapse;font-size:.82rem}
  th{text-align:left;color:#666;font-weight:500;padding:.4rem .6rem;border-bottom:1px solid #222}
  td{padding:.4rem .6rem;border-bottom:1px solid #1a1a1a;color:#aaa}
  tr:hover td{background:#111}
  .tag{font-size:.7rem;padding:.1rem .4rem;border-radius:8px;font-weight:600;text-transform:uppercase;letter-spacing:.03em}
  .tag-done{background:#2ea04322;color:#2ea043}.tag-error{background:#da363322;color:#da3633}
  .tag-found{background:#1da0c322;color:#1da0c3}.tag-not_found{background:#66666622;color:#666}
  .tag-downloading{background:#f0b42922;color:#f0b429}.tag-not_free{background:#e3930022;color:#e39300}
  a{color:#1da0c3;text-decoration:none}a:hover{text-decoration:underline}
  .empty{color:#555;font-style:italic;padding:1rem 0}
  .cycle-summary{background:#151515;border:1px solid #222;border-radius:8px;padding:.7rem 1rem;margin-bottom:1.5rem;font-size:.82rem;color:#888}
  .cycle-summary strong{color:#ccc}
</style>
</head>
<body>
<div class="container">
  <h1><span>&#9835;</span> Camparr</h1>
  <p class="subtitle">Automatic Bandcamp downloads for Lidarr</p>

  <div class="status-bar" id="status-bar">
    <span><span class="status-dot dot-idle" id="status-dot"></span> <span id="status-text">Loading...</span></span>
    <span id="poll-info"></span>
  </div>

  <div class="stats" id="stats"></div>

  <div id="cycle-summary"></div>

  <section>
    <h2>Manual Download</h2>
    <div class="manual">
      <input type="text" id="manual-url" placeholder="https://artist.bandcamp.com/album/...">
      <button onclick="manualDownload()">Download</button>
    </div>
  </section>

  <section>
    <h2>Recent Downloads</h2>
    <div id="downloads"><p class="empty">Loading...</p></div>
  </section>

  <section>
    <h2>Search History</h2>
    <div id="searches"><p class="empty">Loading...</p></div>
  </section>
</div>
<script>
function esc(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML}
function ago(iso){
  if(!iso)return'—';
  const ms=Date.now()-new Date(iso+'Z').getTime();
  if(ms<60000)return'just now';if(ms<3600000)return Math.floor(ms/60000)+'m ago';
  if(ms<86400000)return Math.floor(ms/3600000)+'h ago';return Math.floor(ms/86400000)+'d ago';
}
function refresh(){
  fetch('/api/status').then(r=>r.json()).then(d=>{
    const dot=document.getElementById('status-dot');
    const txt=document.getElementById('status-text');
    const info=document.getElementById('poll-info');
    dot.className='status-dot dot-'+(d.status||'idle');
    txt.textContent=d.status||'idle';
    info.textContent=d.last_poll?'Last poll: '+ago(d.last_poll):'Not polled yet';

    const st=d.stats||{};
    document.getElementById('stats').innerHTML=[
      ['Searched',st.total_searches||0],['Found on BC',st.found||0],
      ['Downloads',st.total_downloads||0],['Successful',st.successful||0],['Failed',st.failed||0]
    ].map(([l,v])=>'<div class="stat"><div class="stat-val">'+v+'</div><div class="stat-label">'+l+'</div></div>').join('');

    const cr=d.cycle_results;
    if(cr){
      document.getElementById('cycle-summary').innerHTML='<div class="cycle-summary">Last cycle: <strong>'+cr.wanted+'</strong> wanted, <strong>'+cr.searched+'</strong> searched, <strong>'+cr.found+'</strong> found on Bandcamp, <strong>'+cr.downloaded+'</strong> downloaded, <strong>'+cr.imported+'</strong> imported</div>';
    }

    const dl=d.downloads||[];
    if(dl.length){
      let h='<table><tr><th>Artist</th><th>Album</th><th>Format</th><th>Status</th><th>When</th></tr>';
      for(const r of dl)h+='<tr><td>'+esc(r.artist)+'</td><td>'+(r.bandcamp_url?'<a href="'+esc(r.bandcamp_url)+'" target=_blank>'+esc(r.album)+'</a>':esc(r.album))+'</td><td>'+esc(r.format)+'</td><td><span class="tag tag-'+r.status+'">'+r.status+'</span>'+(r.error?' <small>'+esc(r.error).slice(0,60)+'</small>':'')+'</td><td>'+ago(r.created_at)+'</td></tr>';
      h+='</table>';
      document.getElementById('downloads').innerHTML=h;
    }else{document.getElementById('downloads').innerHTML='<p class="empty">No downloads yet</p>'}

    const sh=d.searches||[];
    if(sh.length){
      let h='<table><tr><th>Artist</th><th>Album</th><th>Result</th><th>Searched</th></tr>';
      for(const r of sh)h+='<tr><td>'+esc(r.artist)+'</td><td>'+esc(r.album)+'</td><td><span class="tag tag-'+r.result+'">'+r.result+'</span>'+(r.bandcamp_url?' <a href="'+esc(r.bandcamp_url)+'" target=_blank>link</a>':'')+'</td><td>'+ago(r.last_searched)+'</td></tr>';
      h+='</table>';
      document.getElementById('searches').innerHTML=h;
    }else{document.getElementById('searches').innerHTML='<p class="empty">No searches yet</p>'}
  });
}
function manualDownload(){
  const url=document.getElementById('manual-url').value.trim();
  if(!url)return;
  document.getElementById('manual-url').value='';
  fetch('/api/download',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url})})
  .then(r=>r.json()).then(d=>{if(d.error)alert(d.error);else setTimeout(refresh,2000)});
}
document.getElementById('manual-url').addEventListener('keydown',e=>{if(e.key==='Enter')manualDownload()});
refresh();setInterval(refresh,10000);
</script>
</body>
</html>"""


@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/api/status")
def status():
    return jsonify({
        **_state,
        "stats": db.get_stats(),
        "downloads": db.get_downloads(20),
        "searches": db.get_search_history(30),
    })


@app.route("/api/download", methods=["POST"])
def manual_download():
    data = request.json or {}
    url = (data.get("url") or "").strip()
    if not url or "bandcamp.com" not in url:
        return jsonify({"error": "Not a valid Bandcamp URL"}), 400

    fmt = data.get("format", app.config.get("BANDCAMP_FORMAT", "FLAC"))
    download_dir = app.config.get("DOWNLOAD_PATH", "/downloads")

    def run():
        files, error = bandcamp.download(url, download_dir, fmt)
        db.record_download(
            album_id=None,
            artist="Manual",
            album=url.split("/")[-1],
            bandcamp_url=url,
            fmt=fmt,
            status="done" if files else "error",
            files=files,
            error=error,
        )

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/healthcheck")
def healthcheck():
    return "ok"
