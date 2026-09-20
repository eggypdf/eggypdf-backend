"""Final release corrections for Career Pro V1.

Applied only to the packaged Cloudflare release. Keeps the free ATS checker first,
keeps Career Pro always visible below the free checker, restores free resume text
extraction, replaces the old homepage account placeholder, and makes payment
recovery user-dismissible without repeated checkout prompts.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ACCOUNT_STYLE = r'''<style id="eggAccountStyle">
.egg-account-tabs{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:18px 0 12px}.egg-account-tab{border:1px solid #e5e7eb;background:#fff;border-radius:10px;padding:10px;font-weight:700;cursor:pointer}.egg-account-tab.active{background:#17172b;color:#fff;border-color:#17172b}.egg-account-input{width:100%;box-sizing:border-box;border:1px solid #d9dde5;border-radius:10px;padding:12px 13px;margin:7px 0;font:inherit}.egg-account-status{display:none;text-align:left;margin:10px 0;padding:10px 12px;border-radius:9px;font-size:13px;line-height:1.45}.egg-account-status.show{display:block}.egg-account-status.info{background:#eff6ff;color:#1e40af}.egg-account-status.error{background:#fef2f2;color:#991b1b}.egg-account-status.success{background:#ecfdf5;color:#166534}.egg-account-secondary{display:none;width:100%;margin-top:9px;border:1px solid #d9dde5;background:#fff;border-radius:10px;padding:11px 14px;font-weight:700;cursor:pointer}
</style>'''

ACCOUNT_MODAL = r'''<div class="modal-overlay" id="signInModal" onclick="eggCloseOnBackdrop(event)">
  <div class="modal-box" style="max-width:440px">
    <button class="modal-close" onclick="closeEggyAccount()">&#x2715;</button>
    <h2 id="eggAccountTitle">Sign in to EggyPDF</h2>
    <p id="eggAccountCopy" style="margin-bottom:12px">Use your EggyPDF account for Career Pro access and subscription management.</p>
    <div class="egg-account-tabs">
      <button class="egg-account-tab active" id="eggLoginTab" type="button" onclick="setEggyAccountMode('login')">Log in</button>
      <button class="egg-account-tab" id="eggSignupTab" type="button" onclick="setEggyAccountMode('signup')">Sign up</button>
    </div>
    <input class="egg-account-input" id="eggAccountEmail" type="email" autocomplete="email" placeholder="Email address">
    <input class="egg-account-input" id="eggAccountPassword" type="password" autocomplete="current-password" placeholder="Password (8+ characters)">
    <div class="egg-account-status" id="eggAccountStatus"></div>
    <button class="modal-cta" id="eggAccountSubmit" type="button" onclick="submitEggyAccount()" style="width:100%">Log in</button>
    <button class="egg-account-secondary" id="eggAccountCareer" type="button" onclick="location.href='career-pro.html'">Open Career Pro</button>
    <button class="egg-account-secondary" id="eggAccountLogout" type="button" onclick="logoutEggyAccount()">Sign out</button>
  </div>
</div>'''

ACCOUNT_JS = r'''<script id="eggAccountAuthScript">
(function(){
const API='https://eggypdf-backend-1.onrender.com',KEY='eggypdf_account_session';let mode='login';
const q=id=>document.getElementById(id);const read=()=>{try{return JSON.parse(localStorage.getItem(KEY)||'null')}catch(_){return null}};
function setStatus(msg,type='info'){const e=q('eggAccountStatus');e.textContent=msg;e.className='egg-account-status show '+type}
window.setEggyAccountMode=function(next){mode=next==='signup'?'signup':'login';q('eggLoginTab').classList.toggle('active',mode==='login');q('eggSignupTab').classList.toggle('active',mode==='signup');q('eggAccountTitle').textContent=mode==='signup'?'Create your EggyPDF account':'Sign in to EggyPDF';q('eggAccountSubmit').textContent=mode==='signup'?'Create account':'Log in';q('eggAccountPassword').autocomplete=mode==='signup'?'new-password':'current-password';q('eggAccountStatus').className='egg-account-status';q('eggAccountCareer').style.display='none'};
async function accountMe(){const s=read();if(!s?.access_token)return null;let r=await fetch(API+'/api/billing/me',{headers:{Authorization:'Bearer '+s.access_token}});if(r.status===401&&s.refresh_token){const rr=await fetch(API+'/api/account/refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({refresh_token:s.refresh_token})}),rd=await rr.json();if(rr.ok&&rd.success&&rd.session?.access_token){localStorage.setItem(KEY,JSON.stringify(rd.session));return accountMe()}localStorage.removeItem(KEY);return null}if(!r.ok)return null;return r.json()}
window.openEggyAccount=async function(next='login'){setEggyAccountMode(next);q('signInModal').classList.add('show');document.body.style.overflow='hidden';const me=await accountMe();if(me?.user?.email){setStatus('Signed in as '+me.user.email+'.','success');q('eggAccountLogout').style.display='block';if(me.career_pro?.active)q('eggAccountCareer').style.display='block'}else{q('eggAccountLogout').style.display='none'}};
window.closeEggyAccount=function(){q('signInModal').classList.remove('show');document.body.style.overflow=''};
window.eggCloseOnBackdrop=function(e){if(e.target===q('signInModal'))closeEggyAccount()};
window.submitEggyAccount=async function(){const email=q('eggAccountEmail').value.trim(),password=q('eggAccountPassword').value,btn=q('eggAccountSubmit');if(!email||!password){setStatus('Enter your email and password.','error');return}btn.disabled=true;setStatus(mode==='signup'?'Creating your account…':'Signing you in…');try{const r=await fetch(API+'/api/account/'+mode,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,password})}),d=await r.json();if(!r.ok||!d.success)throw Error(d.error||'Account request failed.');if(d.needs_email_confirmation){setStatus('Check your email and confirm your EggyPDF account. Then come back and log in.','info');return}if(!d.session?.access_token)throw Error('No account session was returned.');localStorage.setItem(KEY,JSON.stringify(d.session));const me=await accountMe();setStatus('You are signed in successfully.','success');q('eggAccountLogout').style.display='block';if(me?.career_pro?.active)q('eggAccountCareer').style.display='block'}catch(e){setStatus(e.message||'Account request failed.','error')}finally{btn.disabled=false}};
window.logoutEggyAccount=async function(){const s=read();try{if(s?.access_token)await fetch(API+'/api/account/logout',{method:'POST',headers:{Authorization:'Bearer '+s.access_token}})}catch(_){}localStorage.removeItem(KEY);q('eggAccountCareer').style.display='none';q('eggAccountLogout').style.display='none';setStatus('You are signed out.','info')};
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeEggyAccount()});
})();
</script>'''

FREE_EXTRACT_JS = r'''<script id="freeResumeExtraction">
(function(){
const API='https://eggypdf-backend-1.onrender.com';
const input=document.getElementById('resumeFile'),drop=document.getElementById('dropZone'),box=document.getElementById('resumeText'),name=document.getElementById('fileName'),err=document.getElementById('errorBox');
if(!input||!drop||!box)return;let extracting=false,last='';
function error(msg){if(err){err.textContent=msg;err.style.display='block'}if(name)name.textContent=msg}
function clear(){if(err)err.style.display='none'}
async function extract(file){if(!file||extracting)return;const sig=[file.name,file.size,file.lastModified].join(':');if(sig===last&&box.value.trim())return;if(!/\.(pdf|docx|txt)$/i.test(file.name||'')){error('Upload a PDF, DOCX or TXT resume.');return}extracting=true;clear();if(name)name.textContent=(file.name||'Resume')+' · extracting text…';try{const fd=new FormData();fd.append('resume',file,file.name||'resume');const r=await fetch(API+'/api/career/ats/extract-resume',{method:'POST',body:fd});let d={};try{d=await r.json()}catch(_){}if(!r.ok||!d.success||!d.resume_text)throw Error(d.error||'We could not extract readable text from this resume.');box.value=d.resume_text;box.dispatchEvent(new Event('input',{bubbles:true}));last=sig;if(name)name.textContent='✓ '+(file.name||d.filename||'Resume')+' · text extracted below'}catch(e){error(e.message||'Resume extraction failed. You can still paste the text manually.')}finally{extracting=false}}
input.addEventListener('change',()=>{const f=input.files&&input.files[0];if(f)extract(f)});drop.addEventListener('drop',e=>{const f=e.dataTransfer&&e.dataTransfer.files&&e.dataTransfer.files[0];if(f)setTimeout(()=>extract(f),0)});
})();
</script>'''

RECOVERY_JS = r'''<script id="careerBillingRecovery">
(function(){
const API='https://eggypdf-backend-1.onrender.com',ACCOUNT_KEY='eggypdf_account_session',CHECKOUT_KEY='eggypdf_career_billing_checkout';
const q=id=>document.getElementById(id),sleep=ms=>new Promise(r=>setTimeout(r,ms));let closed=false;
function read(){try{return JSON.parse(localStorage.getItem(ACCOUNT_KEY)||'null')}catch(_){return null}}
async function refresh(){const s=read();if(!s?.refresh_token)return false;try{const r=await fetch(API+'/api/account/refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({refresh_token:s.refresh_token})}),d=await r.json();if(r.ok&&d.success&&d.session?.access_token){localStorage.setItem(ACCOUNT_KEY,JSON.stringify(d.session));return true}}catch(_){}return false}
async function auth(path,retry=true){let s=read();if(!s?.access_token)return {state:'signin'};try{let r=await fetch(API+path,{headers:{Authorization:'Bearer '+s.access_token}});if(r.status===401&&retry&&await refresh())return auth(path,false);let d={};try{d=await r.json()}catch(_){}return {r,d}}catch(_){return {state:'error'}}}
function message(msg,type='info',open=false){const e=q('billingStatus');if(e){e.textContent=msg;e.className='billing-status show '+type}if(open&&!closed){const m=q('careerBillingModal');if(m){m.classList.add('open');m.setAttribute('aria-hidden','false')}const plans=q('billingPlans');if(plans)plans.style.display='none';const a=q('billingAuth');if(a)a.classList.remove('open')}}
function markClosed(){closed=true}const close=q('billingClose'),modal=q('careerBillingModal');if(close)close.addEventListener('click',markClosed);if(modal)modal.addEventListener('click',e=>{if(e.target===modal)markClosed()});
async function active(){const x=await auth('/api/billing/me');return !!(x.r?.ok&&x.d?.career_pro?.active)}
async function checkout(){const id=localStorage.getItem(CHECKOUT_KEY);if(!id)return {state:'none'};const x=await auth('/api/billing/checkout/'+encodeURIComponent(id));if(x.state==='signin')return x;if(x.state==='error'||!x.r)return {state:'error'};if([400,403,404].includes(x.r.status))return {state:'stale'};if(!x.r.ok)return {state:'error'};if(x.d?.active)return {state:'active'};if(x.d?.paid||String(x.d?.payment_status||'').toLowerCase()==='succeeded')return {state:'paid'};return {state:'unpaid'}}
async function waitForActive(n=8){for(let i=0;i<n;i++){if(await active())return true;const s=await checkout();if(s.state==='active')return true;if(s.state!=='paid'&&s.state!=='error')return false;if(i<n-1)await sleep(1400)}return false}
const original=window.openCareerProOffer;
window.openCareerProOffer=async function(){closed=false;if(await active()){localStorage.removeItem(CHECKOUT_KEY);location.href='career-pro.html';return}const s=await checkout();if(s.state==='active'){localStorage.removeItem(CHECKOUT_KEY);location.href='career-pro.html';return}if(s.state==='stale'||s.state==='unpaid'||s.state==='none'){if(s.state!=='none')localStorage.removeItem(CHECKOUT_KEY);if(original)return original();return}if(s.state==='signin'){message('Sign in to your EggyPDF account first so we can check your Career Pro access.','info',true);return}if(s.state==='paid'){message('Your payment was received. We are finishing your Career Pro access now…','info',true);const ok=await waitForActive(8);if(ok){localStorage.removeItem(CHECKOUT_KEY);location.href='career-pro.html';return}message('Your payment is recorded, but access is still syncing. You can close this message and refresh shortly — do not pay again.','error',false);return}message('We could not verify the previous checkout right now. Close this message and try again shortly. You will not be charged again.','error',true)};
const params=new URLSearchParams(location.search);if(params.get('career_pro')==='return'){params.delete('career_pro');history.replaceState({},'',location.pathname+(params.toString()?'?'+params.toString():'')+location.hash);closed=false;message('Payment received. Confirming your Career Pro access…','info',true);waitForActive(10).then(async ok=>{if(ok){localStorage.removeItem(CHECKOUT_KEY);location.replace('career-pro.html');return}const s=await checkout();if(s.state==='stale'||s.state==='unpaid'){localStorage.removeItem(CHECKOUT_KEY);message('This checkout was not completed. Close this message and use Unlock Career Pro if you want to try again.','info',false)}else if(s.state==='signin')message('Please sign in again so we can finish unlocking Career Pro.','error',false);else message('Your payment is still being confirmed. You can close this message and refresh shortly — do not pay again.','error',false)})}
})();
</script>'''


def patch_index(path: str) -> None:
    p=Path(path); s=p.read_text()
    s=s.replace('<button class="btn-ghost" onclick="showSignInModal()">Log in</button>', '<button class="btn-ghost" onclick="openEggyAccount(\'login\')">Log in</button>', 1)
    s=s.replace('<button class="btn-primary" onclick="showSignInModal()">Sign up free</button>', '<button class="btn-primary" onclick="openEggyAccount(\'signup\')">Sign up free</button>', 1)
    if 'id="eggAccountStyle"' not in s:s=s.replace('</head>',ACCOUNT_STYLE+'</head>',1)
    marker='<div class="modal-overlay" id="signInModal" onclick="closeModalOnBackdrop(event)">';start=s.find(marker);end=s.rfind('</body>')
    if start < 0 or end < 0 or end <= start:raise RuntimeError('Homepage account modal marker not found')
    s=s[:start]+ACCOUNT_MODAL+'\n'+ACCOUNT_JS+'\n'+s[end:];p.write_text(s)


def patch_ats(path: str) -> None:
    p=Path(path);s=p.read_text()
    s=re.sub(r'<section class="card pro-card" id="careerProOverview".*?</section>', '', s, count=1, flags=re.S)
    s=re.sub(r'<a class="back" href="#careerProOverview"[^>]*>Career Pro</a>', '', s, count=1)
    m=re.search(r'<section class="card pro-card" id="careerPro">.*?</section>',s,flags=re.S)
    if not m:raise RuntimeError('Career Pro card not found')
    card=m.group(0);s=s[:m.start()]+s[m.end():]
    card=re.sub(r'<h2 id="proTitle">.*?</h2>','<h2 id="proTitle">Go from free ATS check to a complete job application.</h2>',card,count=1,flags=re.S)
    card=re.sub(r'<p class="pro-copy" id="proCopy">.*?</p>','<p class="pro-copy" id="proCopy">Use the free ATS checker first, then unlock Career Pro for AI resume optimization, job tailoring, cover letters and exports.</p>',card,count=1,flags=re.S)
    pos=s.find('</form>')
    if pos<0:raise RuntimeError('ATS form closing tag not found')
    pos+=len('</form>');s=s[:pos]+'\n'+card+'\n'+s[pos:]
    s=s.replace('accept=".pdf,.txt"','accept=".pdf,.docx,.txt"',1).replace('Upload PDF/TXT, or paste the resume text below.','Upload PDF/DOCX/TXT, or paste the resume text below.',1).replace('<small>PDF or TXT</small>','<small>PDF, DOCX or TXT</small>',1)
    s=re.sub(r'<script id="careerBillingRecovery">.*?</script>','',s,count=1,flags=re.S)
    if 'id="freeResumeExtraction"' not in s:s=s.replace('</body>',FREE_EXTRACT_JS+'</body>',1)
    s=s.replace('</body>',RECOVERY_JS+'</body>',1)
    p.write_text(s)


def validate(index_path: str, ats_path: str) -> None:
    index=Path(index_path).read_text();ats=Path(ats_path).read_text()
    assert 'Something great is hatching!' not in index
    assert "openEggyAccount('login')" in index and "openEggyAccount('signup')" in index
    assert 'id="eggAccountAuthScript"' in index and '/api/account/' in index
    assert 'id="careerProOverview"' not in ats and 'href="#careerProOverview"' not in ats
    assert 'id="atsForm"' in ats and 'id="careerPro"' in ats and 'id="results"' in ats
    assert ats.find('</form>') < ats.find('id="careerPro"') < ats.find('id="results"')
    assert 'id="freeResumeExtraction"' in ats and '/api/career/ats/extract-resume' in ats
    assert 'accept=".pdf,.docx,.txt"' in ats and 'PDF, DOCX or TXT' in ats
    assert 'id="careerBillingRecovery"' in ats and 'do not pay again' in ats
    assert 'You will not be charged again' in ats


if __name__=='__main__':
    if len(sys.argv)!=3:raise SystemExit('usage: release_v1_fix.py INDEX_HTML ATS_HTML')
    patch_index(sys.argv[1]);patch_ats(sys.argv[2]);validate(sys.argv[1],sys.argv[2])
