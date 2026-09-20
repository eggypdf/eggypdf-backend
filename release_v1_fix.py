"""Final release corrections for Career Pro V1.

Applied only to the packaged Cloudflare release. This keeps the free ATS checker
first, replaces the old placeholder account modal with real Supabase auth, and
adds resilient post-checkout entitlement recovery so a paid user is never sent
straight into a second checkout while the first payment is being confirmed.
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

RECOVERY_JS = r'''<script id="careerBillingRecovery">
(function(){
const API='https://eggypdf-backend-1.onrender.com',ACCOUNT_KEY='eggypdf_account_session',CHECKOUT_KEY='eggypdf_career_billing_checkout';
const sleep=ms=>new Promise(r=>setTimeout(r,ms));const q=id=>document.getElementById(id);
function readSession(){try{return JSON.parse(localStorage.getItem(ACCOUNT_KEY)||'null')}catch(_){return null}}
async function refreshSession(){const s=readSession();if(!s?.refresh_token)return false;try{const r=await fetch(API+'/api/account/refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({refresh_token:s.refresh_token})}),d=await r.json();if(r.ok&&d.success&&d.session?.access_token){localStorage.setItem(ACCOUNT_KEY,JSON.stringify(d.session));return true}}catch(_){}localStorage.removeItem(ACCOUNT_KEY);return false}
async function authFetch(path,init={},retry=true){let s=readSession();if(!s?.access_token)return {r:null,d:null};let h=new Headers(init.headers||{});h.set('Authorization','Bearer '+s.access_token);try{let r=await fetch(API+path,{...init,headers:h});if(r.status===401&&retry&&await refreshSession())return authFetch(path,init,false);let d={};try{d=await r.json()}catch(_){}return {r,d}}catch(_){return {r:null,d:null}}}
function status(msg,type='info',open=false){const e=q('billingStatus');if(e){e.textContent=msg;e.className='billing-status show '+type}if(open){const m=q('careerBillingModal');if(m){m.classList.add('open');m.setAttribute('aria-hidden','false')}const plans=q('billingPlans');if(plans)plans.style.display='none';const auth=q('billingAuth');if(auth)auth.classList.remove('open')}}
async function accountActive(){const x=await authFetch('/api/billing/me');return !!(x.r?.ok&&x.d?.career_pro?.active)}
async function verifyPending(){const id=localStorage.getItem(CHECKOUT_KEY);if(!id)return {active:false,pending:false,terminal:false};const x=await authFetch('/api/billing/checkout/'+encodeURIComponent(id));if(x.r?.ok&&x.d?.active)return {active:true,pending:false,terminal:false};const ps=String(x.d?.payment_status||'').toLowerCase();const ss=String(x.d?.subscription_status||'').toLowerCase();const terminal=['failed','cancelled','expired'].includes(ps)||['failed','cancelled','expired'].includes(ss);return {active:false,pending:!terminal,terminal}}
async function recover(attempts=8,visible=false){for(let i=0;i<attempts;i++){if(await accountActive()){localStorage.removeItem(CHECKOUT_KEY);return {active:true}}const state=await verifyPending();if(state.active){localStorage.removeItem(CHECKOUT_KEY);return {active:true}}if(state.terminal){localStorage.removeItem(CHECKOUT_KEY);return {active:false,terminal:true}}if(visible)status('Confirming your Career Pro payment…','info',true);if(i<attempts-1)await sleep(1400)}return {active:false,pending:!!localStorage.getItem(CHECKOUT_KEY)}}
const originalOpen=window.openCareerProOffer;
window.openCareerProOffer=async function(){const first=await recover(2,false);if(first.active){location.href='career-pro.html';return}if(localStorage.getItem(CHECKOUT_KEY)){status('We are checking your previous Career Pro payment. You will not be charged again while this check is running.','info',true);const result=await recover(8,true);if(result.active){location.href='career-pro.html';return}if(result.terminal){const plans=q('billingPlans');if(plans)plans.style.display='block';status('The previous checkout was not completed. You can start a new checkout.','info',true);return}status('Your payment has not been confirmed yet. Please wait a moment and refresh this page rather than paying again.','error',true);return}if(originalOpen)return originalOpen();};
const params=new URLSearchParams(location.search);if(params.get('career_pro')==='return'){status('Payment received. Confirming your Career Pro access…','info',true);recover(12,true).then(result=>{if(result.active){location.replace('career-pro.html');return}if(result.terminal){const plans=q('billingPlans');if(plans)plans.style.display='block';status('The checkout was not completed. You can try again.','info',true)}else status('We are still waiting for payment confirmation. Please refresh this page in a moment — do not pay again.','error',true)})}
})();
</script>'''


def patch_index(path: str) -> None:
    p=Path(path); s=p.read_text()
    s=s.replace('<button class="btn-ghost" onclick="showSignInModal()">Log in</button>', '<button class="btn-ghost" onclick="openEggyAccount(\'login\')">Log in</button>', 1)
    s=s.replace('<button class="btn-primary" onclick="showSignInModal()">Sign up free</button>', '<button class="btn-primary" onclick="openEggyAccount(\'signup\')">Sign up free</button>', 1)
    if 'id="eggAccountStyle"' not in s:
        s=s.replace('</head>',ACCOUNT_STYLE+'</head>',1)
    marker='<div class="modal-overlay" id="signInModal" onclick="closeModalOnBackdrop(event)">'
    start=s.find(marker)
    end=s.rfind('</body>')
    if start < 0 or end < 0 or end <= start:
        raise RuntimeError('Homepage account modal marker not found')
    s=s[:start]+ACCOUNT_MODAL+'\n'+ACCOUNT_JS+'\n'+s[end:]
    p.write_text(s)


def patch_ats(path: str) -> None:
    p=Path(path); s=p.read_text()
    s=re.sub(r'<section class="card pro-card" id="careerProOverview".*?</section>', '', s, count=1, flags=re.S)
    s=re.sub(r'<a class="back" href="#careerProOverview"[^>]*>Career Pro</a>', '', s, count=1)
    if 'id="careerBillingRecovery"' not in s:
        s=s.replace('</body>',RECOVERY_JS+'</body>',1)
    p.write_text(s)


def validate(index_path: str, ats_path: str) -> None:
    index=Path(index_path).read_text(); ats=Path(ats_path).read_text()
    assert 'Something great is hatching!' not in index
    assert "openEggyAccount('login')" in index
    assert "openEggyAccount('signup')" in index
    assert 'id="eggAccountAuthScript"' in index
    assert '/api/account/' in index
    assert 'id="careerProOverview"' not in ats
    assert 'href="#careerProOverview"' not in ats
    assert 'id="careerPro"' in ats
    assert 'id="careerBillingRecovery"' in ats
    assert 'You will not be charged again' in ats


if __name__=='__main__':
    if len(sys.argv)!=3:
        raise SystemExit('usage: release_v1_fix.py INDEX_HTML ATS_HTML')
    patch_index(sys.argv[1]); patch_ats(sys.argv[2]); validate(sys.argv[1],sys.argv[2])
