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


def patch_pro(path):
    p=Path(path); s=p.read_text()
    s=s.replace("const API='https://eggypdf-backend-1.onrender.com',KEY='eggypdf_career_pro_checkout';", "const API='https://eggypdf-backend-1.onrender.com',KEY='eggypdf_career_pro_checkout',HANDOFF_KEY='eggypdf_career_handoff';",1)
    importer="""function importCareerHandoff(){try{let raw=sessionStorage.getItem(HANDOFF_KEY);if(!raw)return;let h=JSON.parse(raw),age=Date.now()-(Number(h.saved_at)||0),r=String(h.resume_text||'').trim(),j=String(h.job_description||'').trim();if(age<0||age>2*60*60*1000||r.length>100000||j.length>100000){sessionStorage.removeItem(HANDOFF_KEY);return}if(r&&!$('resume').value.trim())$('resume').value=r;if(j&&!$('job').value.trim())$('job').value=j;if(r||j)$('uploadmsg').textContent='✓ Resume and job description carried over from your free ATS check.';sessionStorage.removeItem(HANDOFF_KEY)}catch(_){}}\n"""
    if 'function importCareerHandoff()' not in s:
        s=s.replace("async function verify(){", importer+"async function verify(){",1)
    s=s.replace("$('workspace').style.display='block'}catch(e)", "$('workspace').style.display='block';importCareerHandoff()}catch(e)",1)
    s=s.replace("Uploaded resume text is processed for this request; Career Pro does not create permanent resume storage.</p>", "Uploaded resume text is processed for this request; Career Pro does not create permanent resume storage. If you came from the free ATS checker in this tab, your resume is filled automatically.</p>",1)
    card='<div class="card" style="margin-top:16px;border-color:#f3d594;background:linear-gradient(135deg,#fff8ed,#fff)"><h2>AI PDF Summarizer</h2><p class="muted">Summarize long text-based PDFs into an overview, key points, important details and action items.</p><a class="btn" href="career-pdf-summarizer.html" style="display:inline-block;text-decoration:none">Open AI PDF Summarizer</a></div>'
    if card in s:
        s=s.replace(card,'',1)
        s=s.replace('<section class="card panel" id="letter">',card+'\n<section class="card panel" id="letter">',1)
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
    assert 'Download DOCX' in pro and 'Download PDF' in pro


if __name__=='__main__':
    import sys
    patch_ats(sys.argv[1]); patch_pro(sys.argv[2]); validate(sys.argv[1],sys.argv[2])
