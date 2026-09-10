from pathlib import Path

HANDOFF_JS = """const HANDOFF_KEY='eggypdf_career_handoff';let lastResumeText='';function saveCareerHandoff(resume,job){resume=(resume||'').trim();job=(job||'').trim();if(!resume&&!job)return;try{sessionStorage.setItem(HANDOFF_KEY,JSON.stringify({resume_text:resume.slice(0,100000),job_description:job.slice(0,100000),saved_at:Date.now()}))}catch(_){}}function captureCareerHandoff(){saveCareerHandoff(lastResumeText||document.getElementById('resumeText').value,document.getElementById('jobText').value)}"""


def patch_ats(path):
    p=Path(path); s=p.read_text()
    s=s.replace("<header><div class=\"head\"><a class=\"logo\" href=\"/\">Eggy<span>PDF</span></a><a class=\"back\" href=\"resume-builder.html\">Build a Resume →</a></div></header>",
                "<header><div class=\"head\"><a class=\"logo\" href=\"/\">Eggy<span>PDF</span></a><div style=\"margin-left:auto;display:flex;gap:8px;align-items:center\"><a class=\"back\" href=\"resume-builder.html\">Build a Resume →</a><a class=\"back\" href=\"#careerProOverview\" style=\"background:#1a1a2e;color:#fff;border-color:#1a1a2e\">Career Pro</a></div></div></header>")
    overview='''<section class="card pro-card" id="careerProOverview" style="max-width:1120px;margin:22px auto 0"><div class="pro-grid"><div><div class="pro-badge">Career Pro</div><h2>Go from ATS check to a complete job application.</h2><p class="pro-copy">Upgrade once and keep working with the same resume in this browser session — no repetitive upload after the free ATS check.</p><div class="pro-list"><div><span>✓</span>AI resume optimizer</div><div><span>✓</span>Job-specific tailoring</div><div><span>✓</span>Regenerate individual sections</div><div><span>✓</span>AI cover letter</div><div><span>✓</span>DOCX & PDF resume export</div><div><span>✓</span>AI PDF Summarizer</div></div></div><div class="pro-action"><div class="pro-price">Career Pro<small>One secure checkout · Dodo Payments</small></div><button class="pro-btn" id="unlockProTop" type="button">Unlock Career Pro</button><div class="pro-note">Your free ATS resume and job description are carried into Career Pro in the same browser tab.</div></div></div></section>'''
    if 'careerProOverview' not in s:
        s=s.replace('</section><main>', '</section>'+overview+'<main>',1)
    s=s.replace('<div class="pro-list"><div><span>✓</span>Advanced resume optimization</div><div><span>✓</span>Job-specific tailoring</div><div><span>✓</span>Cover letter tools</div><div><span>✓</span>Career Pro workspace</div></div>',
                '<div class="pro-list"><div><span>✓</span>AI resume optimization</div><div><span>✓</span>Job-specific tailoring</div><div><span>✓</span>Section regeneration</div><div><span>✓</span>AI cover letter</div><div><span>✓</span>DOCX & PDF export</div><div><span>✓</span>AI PDF Summarizer</div></div>')
    anchor="const API_BASE='https://eggypdf-backend-1.onrender.com',CHECKOUT_KEY='eggypdf_career_pro_checkout';"
    if "HANDOFF_KEY='eggypdf_career_handoff'" not in s:
        s=s.replace(anchor,anchor+HANDOFF_JS,1)
    s=s.replace("btn.onclick=()=>location.href='career-pro.html'", "btn.onclick=()=>{captureCareerHandoff();location.href='career-pro.html'}")
    s=s.replace("async function startCheckout(){const btn=document.getElementById('unlockPro');", "async function startCheckout(sourceBtn){captureCareerHandoff();const btn=sourceBtn||document.getElementById('unlockPro');")
    s=s.replace("document.getElementById('unlockPro').addEventListener('click',startCheckout);", "document.getElementById('unlockPro').addEventListener('click',e=>startCheckout(e.currentTarget));document.getElementById('unlockProTop').addEventListener('click',e=>startCheckout(e.currentTarget));")
    s=s.replace("showProUnlocked();return true", "showProUnlocked();const top=document.getElementById('unlockProTop');if(top){top.textContent='Open Career Pro';top.onclick=()=>{captureCareerHandoff();location.href='career-pro.html'}}return true")
    s=s.replace("if(!res.ok||!data.success)throw new Error(data.error||'Analysis failed.');render(data.analysis)", "if(!res.ok||!data.success)throw new Error(data.error||'Analysis failed.');lastResumeText=(data.resume_text||text||'').trim();saveCareerHandoff(lastResumeText,job);render(data.analysis)")
    p.write_text(s)


def _inject_exports(s):
    s=s.replace('onclick="exportResume(\'docx\')"','onclick="exportResume(&quot;docx&quot;)"')
    s=s.replace('onclick="exportResume(\'pdf\')"','onclick="exportResume(&quot;pdf&quot;)"')
    if 'Download DOCX' in s and '/api/career/pro/export-resume' in s:
        return s
    old='<div class="actions"><button class="btn secondary" id="copyResume">Copy Optimized Resume</button></div>'
    new='<div class="actions"><button class="btn secondary" id="copyResume">Copy Optimized Resume</button><button class="btn secondary" type="button" onclick="exportResume(&quot;docx&quot;)">Download DOCX</button><button class="btn secondary" type="button" onclick="exportResume(&quot;pdf&quot;)">Download PDF</button></div>'
    if old not in s:
        raise RuntimeError('Career Pro resume actions marker not found')
    s=s.replace(old,new,1)
    helper="""async function exportResume(format){if(!lastResume){alert('Optimize your resume first.');return}try{let r=await fetch(API+'/api/career/pro/export-resume',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:session,resume_text:lastResume,format})});if(!r.ok){let d={};try{d=await r.json()}catch{}throw Error(d.error||'Resume export failed.')}let blob=await r.blob(),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=format==='docx'?'EggyPDF-Optimized-Resume.docx':'EggyPDF-Optimized-Resume.pdf';document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}catch(e){alert(e.message)}};"""
    s=s.replace('</script>',helper+'</script>',1)
    return s


def _inject_comparison(s):
    if 'function comparisonHtml' in s:
        return s
    css='''.compare-wrap{margin:18px 0}.compare-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:10px}.compare-head h3{margin:0;font-size:15px}.compare-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.compare-card{border:1px solid #e5e7eb;border-radius:10px;background:#fff;padding:13px}.compare-card.before{background:#fff7ed;border-color:#fed7aa}.compare-card.after{background:#ecfdf5;border-color:#bbf7d0}.compare-label{font-size:10px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:#6b7280;margin-bottom:7px}.compare-text{white-space:pre-wrap;font-size:12.5px;line-height:1.55}.compare-pair{margin:10px 0}.delta{font-size:11px;font-weight:800;color:#166534}.changes-list{margin:8px 0 0;padding-left:18px}.changes-list li{margin-bottom:6px}.compare-empty{color:#9ca3af;font-style:italic}@media(max-width:760px){.compare-grid{grid-template-columns:1fr}}'''
    s=s.replace('</style>',css+'</style>',1)
    helper="""function comparisonHtml(o){let c=o.comparison;if(!c)return'';let summary='<div class="compare-wrap"><div class="compare-head"><h3>Before vs After</h3><span class="delta">'+(c.score?.delta>0?'+':'')+(c.score?.delta??0)+' resume-score points</span></div><div class="compare-grid"><div class="compare-card before"><div class="compare-label">Original summary</div><div class="compare-text">'+esc(c.summary?.before||'No clearly labeled summary detected.')+'</div></div><div class="compare-card after"><div class="compare-label">Optimized summary</div><div class="compare-text">'+esc(c.summary?.after||'No optimized summary returned.')+'</div></div></div>';let pairs=(c.bullets||[]).map((x,i)=>'<div class="compare-pair"><div class="compare-grid"><div class="compare-card before"><div class="compare-label">Original bullet '+(i+1)+'</div><div class="compare-text '+(!x.before?'compare-empty':'')+'">'+esc(x.before||'No matching original bullet detected.')+'</div></div><div class="compare-card after"><div class="compare-label">Rewritten bullet '+(i+1)+'</div><div class="compare-text">'+esc(x.after||'')+'</div></div></div></div>').join('');let changes=(c.changes||[]).length?'<div class="compare-card" style="margin-top:12px"><div class="compare-label">What changed</div><ul class="changes-list">'+c.changes.map(x=>'<li>'+esc(x)+'</li>').join('')+'</ul></div>':'';return summary+pairs+changes+'</div>'}"""
    s=s.replace('function chips(',helper+'function chips(',1)
    marker="'+sparse+'<div class=\"block\"><h3>Optimized professional summary</h3>"
    if marker not in s:
        raise RuntimeError('Career Pro optimizer output marker not found')
    s=s.replace(marker,"'+sparse+comparisonHtml(o)+'<div class=\"block\"><h3>Optimized professional summary</h3>",1)
    return s


def patch_pro(path):
    p=Path(path); s=p.read_text()
    s=_inject_exports(s)
    s=_inject_comparison(s)
    s=s.replace("const API='https://eggypdf-backend-1.onrender.com',KEY='eggypdf_career_pro_checkout';", "const API='https://eggypdf-backend-1.onrender.com',KEY='eggypdf_career_pro_checkout',HANDOFF_KEY='eggypdf_career_handoff';",1)
    importer="""function importCareerHandoff(){try{let raw=sessionStorage.getItem(HANDOFF_KEY);if(!raw)return;let h=JSON.parse(raw),age=Date.now()-(Number(h.saved_at)||0),r=String(h.resume_text||'').trim(),j=String(h.job_description||'').trim();if(age<0||age>2*60*60*1000||r.length>100000||j.length>100000){sessionStorage.removeItem(HANDOFF_KEY);return}if(r&&!$('resume').value.trim())$('resume').value=r;if(j&&!$('job').value.trim())$('job').value=j;if(r||j)$('uploadmsg').textContent='✓ Resume and job description carried over from your free ATS check.';sessionStorage.removeItem(HANDOFF_KEY)}catch(_){}}\n"""
    if 'function importCareerHandoff()' not in s:
        s=s.replace("async function verify(){", importer+"async function verify(){",1)
    s=s.replace("$('workspace').style.display='block'}catch(e)", "$('workspace').style.display='block';importCareerHandoff()}catch(e)",1)
    s=s.replace("Uploaded resume text is processed for this request; Career Pro does not create permanent resume storage.</p>", "Uploaded resume text is processed for this request; Career Pro does not create permanent resume storage. If you came from the free ATS checker in this tab, your resume is filled automatically.</p>",1)
    card='<div class="card" style="margin-top:16px;border-color:#f3d594;background:linear-gradient(135deg,#fff8ed,#fff)"><h2>AI PDF Summarizer</h2><p class="muted">Summarize long text-based PDFs into an overview, key points, important details and action items.</p><a class="btn" href="career-pdf-summarizer.html" style="display:inline-block;text-decoration:none">Open AI PDF Summarizer</a></div>'
    if card in s:
        s=s.replace(card,'',1)
    marker='<section class="card panel" id="letter">'
    if marker not in s:
        raise RuntimeError('Career Pro cover-letter panel marker not found')
    s=s.replace(marker,card+'\n'+marker,1)
    p.write_text(s)


def validate(ats_path, pro_path):
    ats=Path(ats_path).read_text(); pro=Path(pro_path).read_text()
    assert 'careerProOverview' in ats
    assert "eggypdf_career_handoff" in ats and 'saveCareerHandoff' in ats
    assert "data.resume_text" in ats
    assert 'AI PDF Summarizer' in ats and 'DOCX & PDF' in ats
    assert 'importCareerHandoff' in pro and "eggypdf_career_handoff" in pro
    assert pro.find('Optimize My Resume') < pro.find('AI PDF Summarizer')
    assert '/api/career/pro/regenerate-section' in pro
    assert '/api/career/pro/export-resume' in pro
    assert 'Download DOCX' in pro and 'Download PDF' in pro
    assert "exportResume('docx')" not in pro and "exportResume('pdf')" not in pro
    assert 'Before vs After' in pro and 'comparisonHtml' in pro


if __name__=='__main__':
    import sys
    patch_ats(sys.argv[1]); patch_pro(sys.argv[2]); validate(sys.argv[1],sys.argv[2])
