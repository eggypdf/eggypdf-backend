"""Patch the validated Cloudflare release with Career Pro V1 billing UI.

This intentionally modifies release artifacts, not the classic source package.
That preserves the existing design while replacing the legacy anonymous checkout
with pricing -> account -> checkout and account-based Career Pro access.
"""
from pathlib import Path

STYLE = r'''<style id="careerBillingStyle">
.billing-modal{position:fixed;inset:0;background:rgba(17,24,39,.58);z-index:9999;display:none;align-items:center;justify-content:center;padding:18px}.billing-modal.open{display:flex}.billing-box{width:min(520px,100%);max-height:92vh;overflow:auto;background:#fff;border-radius:18px;border:1px solid #e5e7eb;box-shadow:0 24px 70px rgba(0,0,0,.24);padding:22px}.billing-head{display:flex;align-items:flex-start;gap:14px}.billing-head h2{font-size:23px;margin:0}.billing-close{margin-left:auto;border:0;background:#f3f4f6;border-radius:8px;width:34px;height:34px;cursor:pointer}.billing-tabs{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:18px 0}.billing-plan{border:1.5px solid #e5e7eb;border-radius:11px;background:#fff;padding:13px;cursor:pointer;text-align:left}.billing-plan.active{border-color:#f5a623;background:#fff8ed}.billing-plan b{display:block;font-size:14px}.billing-plan span{font-size:11px;color:#6b7280}.billing-price{text-align:center;padding:10px 0 4px}.billing-price strong{font-size:34px}.billing-price p{font-size:12px;color:#6b7280;margin:4px 0}.billing-save{display:inline-block;background:#ecfdf5;color:#166534;border-radius:99px;padding:5px 9px;font-size:10px;font-weight:800}.billing-features{display:grid;grid-template-columns:1fr 1fr;gap:8px 12px;margin:16px 0}.billing-features div{font-size:12px}.billing-features span{color:#16a34a;margin-right:5px}.billing-primary{width:100%;border:0;border-radius:10px;padding:13px;background:#1a1a2e;color:#fff;font-weight:800;cursor:pointer}.billing-primary:disabled{opacity:.55}.billing-auth{display:none}.billing-auth.open{display:block}.billing-auth input{width:100%;padding:11px;border:1.5px solid #e5e7eb;border-radius:9px;margin-top:8px}.billing-auth-switch{display:flex;gap:7px;margin:12px 0}.billing-auth-switch button{flex:1;border:1px solid #e5e7eb;background:#fff;border-radius:8px;padding:9px;cursor:pointer;font-weight:700}.billing-auth-switch button.active{background:#1a1a2e;color:#fff}.billing-code{display:flex;gap:7px;margin-top:8px}.billing-code input{margin-top:0}.billing-code button{border:1px solid #e5e7eb;background:#fff;border-radius:9px;padding:0 12px;font-weight:700}.billing-status{display:none;margin-top:10px;padding:9px 11px;border-radius:8px;font-size:11.5px}.billing-status.show{display:block}.billing-status.info{background:#eff6ff;color:#1e40af}.billing-status.error{background:#fef2f2;color:#991b1b}.billing-status.success{background:#ecfdf5;color:#166534}.credit-pill{display:inline-flex;align-items:center;gap:5px;background:#fff8ed;border:1px solid #f3d594;border-radius:99px;padding:5px 9px;font-size:11px;font-weight:800;color:#7c5a13}@media(max-width:620px){.billing-features{grid-template-columns:1fr}}
</style>'''

MODAL = r'''<div class="billing-modal" id="careerBillingModal" aria-hidden="true"><div class="billing-box"><div class="billing-head"><div><div class="pro-badge">Career Pro</div><h2>Choose your Career Pro plan</h2></div><button class="billing-close" id="billingClose" type="button">×</button></div><div id="billingPlans"><div class="billing-tabs"><button class="billing-plan" data-plan="monthly" type="button"><b>Monthly</b><span>$6.99 billed monthly</span></button><button class="billing-plan active" data-plan="yearly" type="button"><b>Yearly · Save 43%</b><span>$48 billed annually</span></button></div><div class="billing-price"><strong id="billingPrice">$4 / month</strong><p id="billingLine">$48 USD billed annually</p><span class="billing-save" id="billingSave">Save $35.88 a year</span></div><div class="billing-features"><div><span>✓</span>2,000 AI credits/month</div><div><span>✓</span>AI Resume Optimizer</div><div><span>✓</span>Job-specific tailoring</div><div><span>✓</span>AI Cover Letters</div><div><span>✓</span>Section regeneration</div><div><span>✓</span>AI PDF Summarizer</div><div><span>✓</span>Free ATS checks</div><div><span>✓</span>PDF & DOCX export</div></div><button class="billing-primary" id="billingContinue" type="button">Continue with Yearly</button></div><div class="billing-auth" id="billingAuth"><h3 id="billingAuthTitle">Sign in to continue</h3><div class="billing-auth-switch"><button type="button" class="active" data-auth="login">Sign in</button><button type="button" data-auth="signup">Create account</button></div><input id="billingEmail" type="email" autocomplete="email" placeholder="Email address"><input id="billingPassword" type="password" autocomplete="current-password" placeholder="Password (8+ characters)"><div class="billing-code"><input id="billingCreatorCode" placeholder="Creator Code (optional)"><button id="billingApplyCode" type="button">Apply</button></div><button class="billing-primary" id="billingAuthSubmit" type="button" style="margin-top:12px">Sign in & Continue</button><button type="button" id="billingBack" style="width:100%;border:0;background:none;padding:10px;color:#6b7280;cursor:pointer">← Back to plans</button></div><div class="billing-status" id="billingStatus"></div></div></div>'''

JS = r'''<script id="careerBillingScript">
(function(){
const BILLING_API='https://eggypdf-backend-1.onrender.com',ACCOUNT_KEY='eggypdf_account_session',BILLING_CHECKOUT_KEY='eggypdf_career_billing_checkout';let selectedPlan='yearly',authMode='login';
const q=id=>document.getElementById(id),session=()=>{try{return JSON.parse(localStorage.getItem(ACCOUNT_KEY)||'null')}catch(_){return null}},token=()=>session()?.access_token||'',headers=(json=true)=>{let h={};if(json)h['Content-Type']='application/json';if(token())h.Authorization='Bearer '+token();return h};
function status(msg,type='info'){let e=q('billingStatus');if(!e)return;e.textContent=msg;e.className='billing-status show '+type}function clearStatus(){let e=q('billingStatus');if(e)e.className='billing-status'}
function setPlan(plan){selectedPlan=plan;document.querySelectorAll('.billing-plan').forEach(b=>b.classList.toggle('active',b.dataset.plan===plan));if(plan==='yearly'){q('billingPrice').textContent='$4 / month';q('billingLine').textContent='$48 USD billed annually';q('billingSave').style.display='inline-block';q('billingContinue').textContent='Continue with Yearly'}else{q('billingPrice').textContent='$6.99 / month';q('billingLine').textContent='$6.99 USD billed monthly';q('billingSave').style.display='none';q('billingContinue').textContent='Continue with Monthly'}}
async function accountState(){if(!token())return null;try{let r=await fetch(BILLING_API+'/api/billing/me',{headers:headers(false)});if(r.status===401){localStorage.removeItem(ACCOUNT_KEY);return null}let d=await r.json();return r.ok?d:null}catch(_){return null}}
async function openOffer(){clearStatus();let me=await accountState();if(me?.career_pro?.active){location.href='career-pro.html';return}q('careerBillingModal').classList.add('open');q('careerBillingModal').setAttribute('aria-hidden','false');q('billingPlans').style.display='block';q('billingAuth').classList.remove('open');setPlan('yearly')}
window.openCareerProOffer=openOffer;
function closeOffer(){q('careerBillingModal').classList.remove('open');q('careerBillingModal').setAttribute('aria-hidden','true')}
async function createCheckout(){let r=await fetch(BILLING_API+'/api/billing/checkout',{method:'POST',headers:headers(),body:JSON.stringify({plan:selectedPlan})}),d=await r.json();if(!r.ok||!d.success)throw Error(d.error||'Could not start checkout.');localStorage.setItem(BILLING_CHECKOUT_KEY,d.session_id);location.assign(d.checkout_url)}
async function authAndContinue(){let email=q('billingEmail').value.trim(),password=q('billingPassword').value,btn=q('billingAuthSubmit');if(!email||!password){status('Enter your email and password.','error');return}btn.disabled=true;status(authMode==='signup'?'Creating your account…':'Signing you in…');try{let r=await fetch(BILLING_API+'/api/account/'+(authMode==='signup'?'signup':'login'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,password})}),d=await r.json();if(!r.ok||!d.success)throw Error(d.error||'Account request failed.');if(d.needs_email_confirmation){status('Check your email and confirm your EggyPDF account, then sign in to continue.','info');return}if(!d.session?.access_token)throw Error('No account session was returned.');localStorage.setItem(ACCOUNT_KEY,JSON.stringify(d.session));let code=q('billingCreatorCode').value.trim();if(code){let cr=await fetch(BILLING_API+'/api/billing/creator-code/redeem',{method:'POST',headers:headers(),body:JSON.stringify({code})}),cd=await cr.json();if(cr.ok&&cd.success){status('Creator Code applied. Career Pro is active.','success');setTimeout(()=>location.href='career-pro.html',450);return}if(!cr.ok)status(cd.error||cd.message||'Creator Code could not be applied. Continuing to checkout.','info')}await createCheckout()}catch(e){status(e.message,'error')}finally{btn.disabled=false}}
async function restoreBilling(){let params=new URLSearchParams(location.search);if(params.get('career_pro')!=='return')return;let id=localStorage.getItem(BILLING_CHECKOUT_KEY);if(!id||!token())return;try{let r=await fetch(BILLING_API+'/api/billing/checkout/'+encodeURIComponent(id),{headers:headers(false)}),d=await r.json();if(r.ok&&d.paid){localStorage.removeItem(BILLING_CHECKOUT_KEY);location.replace('career-pro.html')}}catch(_){}}
document.querySelectorAll('.billing-plan').forEach(b=>b.addEventListener('click',()=>setPlan(b.dataset.plan)));q('billingClose').onclick=closeOffer;q('careerBillingModal').addEventListener('click',e=>{if(e.target===q('careerBillingModal'))closeOffer()});q('billingContinue').onclick=async()=>{let me=await accountState();if(me){try{await createCheckout()}catch(e){status(e.message,'error')}return}q('billingPlans').style.display='none';q('billingAuth').classList.add('open')};q('billingBack').onclick=()=>{q('billingPlans').style.display='block';q('billingAuth').classList.remove('open');clearStatus()};document.querySelectorAll('[data-auth]').forEach(b=>b.onclick=()=>{authMode=b.dataset.auth;document.querySelectorAll('[data-auth]').forEach(x=>x.classList.toggle('active',x===b));q('billingAuthTitle').textContent=authMode==='signup'?'Create your EggyPDF account':'Sign in to continue';q('billingAuthSubmit').textContent=authMode==='signup'?'Create Account & Continue':'Sign in & Continue';q('billingPassword').autocomplete=authMode==='signup'?'new-password':'current-password'});q('billingAuthSubmit').onclick=authAndContinue;q('billingApplyCode').onclick=async()=>{if(!token()){status('Sign in or create your account first, then apply the Creator Code.','info');return}let code=q('billingCreatorCode').value.trim();if(!code){status('Enter a Creator Code.','error');return}try{let r=await fetch(BILLING_API+'/api/billing/creator-code/redeem',{method:'POST',headers:headers(),body:JSON.stringify({code})}),d=await r.json();if(!r.ok||!d.success)throw Error(d.error||d.message||'Creator Code could not be applied.');status('Creator Code applied. Career Pro is active.','success');setTimeout(()=>location.href='career-pro.html',450)}catch(e){status(e.message,'error')}};restoreBilling();
})();
</script>'''

PRO_JS = r'''<script id="careerProAccountPatch">
(function(){const ACCOUNT_KEY='eggypdf_account_session',API='https://eggypdf-backend-1.onrender.com';let s=null;try{s=JSON.parse(localStorage.getItem(ACCOUNT_KEY)||'null')}catch(_){}let token=s?.access_token||'';if(!token)return;const authHeaders=(json=false)=>{let h={Authorization:'Bearer '+token};if(json)h['Content-Type']='application/json';return h};window.eggyAuthHeaders=authHeaders;async function accountGate(){try{let r=await fetch(API+'/api/billing/me',{headers:authHeaders()}),d=await r.json();if(!r.ok||!d.career_pro?.active)throw Error(d.error||'Career Pro is not active on this account.');let gate=document.getElementById('gate'),workspace=document.getElementById('workspace');if(gate)gate.style.display='none';if(workspace)workspace.style.display='block';let credits=d.credits?.balance;if(credits!==undefined&&credits!==null){let pill=document.createElement('span');pill.className='credit-pill';pill.id='careerCreditPill';pill.textContent=Number(credits).toLocaleString()+' credits';let head=document.querySelector('.head');if(head)head.insertBefore(pill,head.querySelector('.back'))}}catch(e){let gs=document.getElementById('gateStatus');if(gs){gs.className='status error';gs.textContent=e.message}}}window.addEventListener('DOMContentLoaded',accountGate);const nativeFetch=window.fetch.bind(window);window.fetch=function(input,init={}){let url=typeof input==='string'?input:(input&&input.url)||'';if(url.includes('/api/career/pro/')){let h=new Headers(init.headers||{});h.set('Authorization','Bearer '+token);if(!h.has('X-Idempotency-Key')&&['/optimize','/cover-letter','/regenerate-section','/pdf-summary','/tailor'].some(x=>url.includes(x)))h.set('X-Idempotency-Key',crypto.randomUUID?crypto.randomUUID():Date.now()+'-'+Math.random());init={...init,headers:h}}return nativeFetch(input,init)};
})();
</script>'''


def patch_ats(path):
    p=Path(path); s=p.read_text()

    if 'careerBillingStyle' not in s:
        s=s.replace('</head>',STYLE+'</head>',1)

    if 'id="careerBillingModal"' not in s:
        s=s.replace('</body>', MODAL+'</body>', 1)

    if 'id="careerBillingScript"' not in s:
        s=s.replace('</body>', JS+'</body>', 1)

    # Existing packaged release has both top and result Career Pro buttons.
    s=s.replace(
        "document.getElementById('unlockPro').addEventListener('click',e=>startCheckout(e.currentTarget));",
        "document.getElementById('unlockPro').addEventListener('click',e=>openCareerProOffer());"
    )

    s=s.replace(
        "if(unlockProTop)unlockProTop.addEventListener('click',e=>startCheckout(e.currentTarget));",
        "if(unlockProTop)unlockProTop.addEventListener('click',e=>openCareerProOffer());"
    )

    # The new billing return verifier owns account-linked checkout restoration.
    s=s.replace(
        'restoreCareerPro();',
        '/* Career Pro V1 billing restoration handled below. */'
    )

    p.write_text(s)


def patch_pro(path):
    p=Path(path); s=p.read_text()
    if 'careerBillingStyle' not in s:
        s=s.replace('</head>',STYLE+'</head>',1)
    if 'careerProAccountPatch' not in s:
        s=s.replace('</body>',PRO_JS+'</body>',1)
    p.write_text(s)


def validate(ats_path, pro_path):
    ats=Path(ats_path).read_text(); pro=Path(pro_path).read_text()
    assert 'id="careerProOverview"' in ats
    assert 'id="careerBillingModal"' in ats
    assert 'Continue with Yearly' in ats and '$48 USD billed annually' in ats
    assert '$6.99 USD billed monthly' in ats and '2,000 AI credits/month' in ats
   assert '/api/billing/checkout' in ats
assert '/api/account/' in ats
assert "authMode==='signup'?'signup':'login'" in ats
    assert 'creator-code/redeem' in ats
    assert 'Cancel anytime' not in ats
    assert 'Payments already made are non-refundable except where required by law.' not in ats
    assert 'careerProAccountPatch' in pro
    assert '/api/billing/me' in pro
    assert 'X-Idempotency-Key' in pro


if __name__=='__main__':
    import sys
    patch_ats(sys.argv[1]); patch_pro(sys.argv[2]); validate(sys.argv[1],sys.argv[2])
