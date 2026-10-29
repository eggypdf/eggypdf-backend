"""Patch a compress.html so it uses the async compress job API.

Usage: python scripts/patch-compress-async.py path/to/compress.html

Works on both the plain repo compress.html and the Career Pro patched one
(scripts/add-career-buttons.py): it only replaces the request/response lines
and leaves the blob/result handling (and any Career Pro return flow) alone.
Safe to run twice.
"""
import sys
from pathlib import Path

path = Path(sys.argv[1])
html = path.read_text(encoding="utf-8")

if "compressViaJob" in html:
    print("compress.html already patched; nothing to do.")
    sys.exit(0)

# Variant A: the plain repo compress.html. Variant B: the live Cloudflare one
# (90s timeout, its own error handling and result stats just below the call).
old_request = """    const res=await fetchWithTimeout(API_BASE+'/api/compress',{method:'POST',body:fd});
    finishEggProgress();
    if(!res.ok){const e=await res.json();throw new Error(e.error||'Compression failed.');}
"""
new_request = """    const res=await compressViaJob(fd);
    finishEggProgress();
"""
old_live = "const res=await fetchWithTimeout(API_BASE+'/api/compress',{method:'POST',body:fd},90000);"
new_live = "const res=await compressViaJob(fd);"
if old_request in html:
    html = html.replace(old_request, new_request, 1)
elif old_live in html:
    html = html.replace(old_live, new_live, 1)
else:
    raise RuntimeError("compress.html request block not found.")

helper = r"""const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const fmtMB=b=>(b/1024/1024).toFixed(2)+' MB';
function showCompressStats(before,after){
  const st=document.getElementById('resultStats');
  if(!st||st.tagName!=='P'||!(before>0)||!(after>0)) return;
  const pct=Math.round((1-after/before)*100);
  st.textContent=pct>=3
    ? `${fmtMB(before)} → ${fmtMB(after)} (${pct}% smaller)`
    : `${fmtMB(before)} → ${fmtMB(after)}. This PDF could barely be reduced at this level — try "High" for a smaller file.`;
}
// Upload, then poll the server until the job is done. Returns the download
// Response (a PDF) so the caller's existing result handling keeps working.
async function compressViaJob(fd){
  fd.append('async','1');
  const res=await fetchWithTimeout(API_BASE+'/api/compress',{method:'POST',body:fd},180000);
  if((res.headers.get('content-type')||'').includes('application/pdf')) return res; // older backend, synchronous
  const start=await res.json().catch(()=>({}));
  if(!res.ok||!start.job_id) throw new Error(start.error||'Compression failed. Please try again.');
  const t0=Date.now();let fails=0,stats=null;
  while(Date.now()-t0<360000){
    await sleep(2000);
    const secs=(Date.now()-t0)/1000;
    const tt=document.getElementById('eggTitle');
    if(tt&&secs>15) tt.textContent=secs>60?'Still working — big files take a bit longer...':'Compressing your PDF...';
    let j;
    try{
      const sr=await fetchWithTimeout(API_BASE+'/api/compress/status/'+start.job_id,{},20000);
      j=await sr.json();fails=0;
      if(sr.status===404) throw new Error(j.error||'Job expired. Please try again.');
    }catch(e){
      if(e.message&&!/timed out|taking too long|Failed to fetch|NetworkError|Load failed/i.test(e.message)) throw e;
      if(++fails>=6) throw new Error('Lost connection to the server. Please try again.');
      continue;
    }
    if(j.status==='error') throw new Error(j.error||'Compression failed.');
    if(j.status==='done'){stats=j;break;}
  }
  if(!stats) throw new Error('Compression is taking too long. Try the High level or a smaller file.');
  const dl=await fetchWithTimeout(API_BASE+'/api/compress/download/'+start.job_id,{},180000);
  if(!dl.ok){const e=await dl.json().catch(()=>({}));throw new Error(e.error||'Download failed. Please try again.');}
  showCompressStats(stats.original_size,stats.compressed_size);
  return dl;
}
"""
marker = "async function processFile(){"
if marker not in html:
    raise RuntimeError("processFile not found.")
html = html.replace(marker, helper + marker, 1)

old_p = "<p>Your PDF has been compressed successfully.</p>"
if old_p in html:
    html = html.replace(old_p, '<p id="resultStats">Your PDF has been compressed successfully.</p>', 1)

path.write_text(html, encoding="utf-8")
print("compress.html patched for async compression.")
