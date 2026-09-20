(function(){
  'use strict';
  const API='https://eggypdf-backend-1.onrender.com';
  const SESSION_KEY='eggypdf_account_session';
  const CREATOR_KEY='eggypdf_pending_creator_code';
  let meCache=null, refreshPromise=null, authWaiters=[], reconcileAttempted=false;

  function readSession(){try{return JSON.parse(localStorage.getItem(SESSION_KEY)||'null')}catch(_){return null}}
  function writeSession(s){if(s&&s.access_token)localStorage.setItem(SESSION_KEY,JSON.stringify(s));else localStorage.removeItem(SESSION_KEY);meCache=null;reconcileAttempted=false;renderHeader();return s}
  function clearSession(){localStorage.removeItem(SESSION_KEY);meCache=null;reconcileAttempted=false;renderHeader()}
  function token(){return readSession()?.access_token||''}
  function headers(extra){const h=Object.assign({},extra||{});const t=token();if(t)h.Authorization='Bearer '+t;return h}
  async function safeJson(r,fallback){const text=await r.text();if(!text)return {};try{return JSON.parse(text)}catch(_){throw Error(fallback||'EggyPDF received an unexpected server response. Please try again.')}}

  async function refresh(){
    if(refreshPromise)return refreshPromise;
    const s=readSession(); if(!s?.refresh_token)return null;
    refreshPromise=(async()=>{try{
      const r=await fetch(API+'/api/account/refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({refresh_token:s.refresh_token})});
      const d=await safeJson(r,'Your session could not be refreshed. Please sign in again.'); if(!r.ok||!d.success)throw Error(d.error||'Session expired.');
      return writeSession(d.session);
    }catch(_){clearSession();return null}finally{refreshPromise=null}})();
    return refreshPromise;
  }

  async function accountFetch(url,opts,retry){
    opts=Object.assign({},opts||{}); opts.headers=headers(opts.headers);
    let r=await fetch(url,opts);
    if(r.status===401 && retry!==false && readSession()?.refresh_token){
      const s=await refresh(); if(s){opts.headers=headers(opts.headers);r=await fetch(url,opts)}
    }
    return r;
  }

  async function fetchAccountState(){
    const r=await accountFetch(API+'/api/account/me',{},true);
    const d=await safeJson(r,'Could not verify your account right now.');
    if(!r.ok||!d.success){if(r.status===401)clearSession();return null}
    return d;
  }

  async function tryReconcile(){
    if(reconcileAttempted||!token())return false;
    reconcileAttempted=true;
    try{
      const r=await accountFetch(API+'/api/billing/reconcile-account',{},true);
      const d=await safeJson(r,'Could not restore Career Pro right now.');
      return !!(r.ok&&d.success&&d.active);
    }catch(_){return false}
  }

  async function me(force){
    if(meCache&&!force)return meCache;
    if(!token())return null;
    try{
      let d=await fetchAccountState();
      if(!d)return null;
      if(!d.career_pro?.active&&force&&await tryReconcile()){
        d=await fetchAccountState()||d;
      }
      meCache=d;renderHeader();document.dispatchEvent(new CustomEvent('eggy:account',{detail:d}));return d;
    }catch(_){return null}
  }

  async function login(email,password){
    const r=await fetch(API+'/api/account/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,password})});
    const d=await safeJson(r,'Sign in service returned an unexpected response. Please try again.'); if(!r.ok||!d.success)throw Error(d.error||'Could not sign in.'); writeSession(d.session); await me(true); return d;
  }
  async function signup(email,password){
    const r=await fetch(API+'/api/account/signup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,password})});
    const d=await safeJson(r,'Account creation service returned an unexpected response. Please try again.'); if(!r.ok||!d.success)throw Error(d.error||'Could not create account.');
    if(d.session?.access_token){writeSession(d.session);await me(true)}
    return d;
  }
  async function redeemCreatorCode(code){
    code=String(code||'').trim().toUpperCase();if(!code)throw Error('Enter your Creator Code first.');
    const r=await accountFetch(API+'/api/billing/creator-code/redeem',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code})},true);
    const d=await safeJson(r,'Creator Code service returned an unexpected response.');if(!r.ok||!d.success)throw Error(d.error||'Could not redeem this Creator Code.');
    localStorage.removeItem(CREATOR_KEY);reconcileAttempted=false;await me(true);return d;
  }
  async function redeemPendingCreatorCode(){const code=localStorage.getItem(CREATOR_KEY);if(!code)return null;return redeemCreatorCode(code)}
  async function logout(){try{await accountFetch(API+'/api/account/logout',{method:'POST'},false)}catch(_){}clearSession();location.reload()}

  function ensureModal(){
    if(document.getElementById('eggyAuthOverlay'))return;
    const wrap=document.createElement('div');wrap.id='eggyAuthOverlay';wrap.className='eggy-auth-overlay';wrap.innerHTML=`<div class="eggy-auth-card" role="dialog" aria-modal="true" aria-labelledby="eggyAuthTitle"><button class="eggy-auth-close" type="button" aria-label="Close">×</button><div class="eggy-auth-brand">Eggy<span>PDF</span></div><h2 id="eggyAuthTitle">Sign in to EggyPDF</h2><p class="eggy-auth-copy" id="eggyAuthCopy">Use your account to keep Career Pro access available across devices.</p><div class="eggy-auth-price" aria-label="Career Pro price"><span class="eggy-premium-label"><svg class="premium-crown" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M3 7.5 7.5 11 12 4l4.5 7L21 7.5 19.2 18H4.8L3 7.5Zm2.7 8.5h12.6l.7-4.1-2.9 2.2-4.1-6.3-4.1 6.3L5 11.9 5.7 16Z"/></svg> Career Pro</span><strong>From $4 USD / month</strong><small>$48 yearly · or $6.99 monthly · 2,000 AI credits/month</small></div><div class="eggy-auth-tabs"><button type="button" class="eggy-auth-tab active" data-mode="login">Sign in</button><button type="button" class="eggy-auth-tab" data-mode="signup">Create account</button></div><form id="eggyAuthForm"><label class="eggy-auth-field"><span>Email</span><input id="eggyAuthEmail" type="email" autocomplete="email" required placeholder="you@example.com"></label><label class="eggy-auth-field"><span>Password</span><input id="eggyAuthPassword" type="password" minlength="8" autocomplete="current-password" required placeholder="At least 8 characters"></label><div class="eggy-creator-field" id="eggyCreatorField"><label><span>Have a Creator Code?</span></label><div class="eggy-creator-row"><input id="eggyCreatorCode" type="text" maxlength="80" autocomplete="off" placeholder="EGGY-CREATOR-XXXX"><button id="eggyCreatorApply" type="button">Apply</button></div><small>Optional. Your one-time code is redeemed after you confirm your email and sign in.</small></div><button class="eggy-auth-submit" id="eggyAuthSubmit" type="submit">Sign in</button><div class="eggy-auth-status" id="eggyAuthStatus"></div><p class="eggy-auth-note" id="eggyAuthNote">Free PDF tools do not require an account.</p></form></div>`;
    document.body.appendChild(wrap);
    wrap.addEventListener('click',e=>{if(e.target===wrap)close(false)});wrap.querySelector('.eggy-auth-close').onclick=()=>close(false);
    wrap.querySelectorAll('.eggy-auth-tab').forEach(b=>b.onclick=()=>setMode(b.dataset.mode));
    wrap.querySelector('#eggyAuthForm').onsubmit=submitAuth;wrap.querySelector('#eggyCreatorApply').onclick=()=>{const code=wrap.querySelector('#eggyCreatorCode').value.trim().toUpperCase();if(!code){status('Enter your Creator Code first.','error');return}localStorage.setItem(CREATOR_KEY,code);status('Creator Code saved. Confirm your email and sign in to redeem it.','confirm')};
  }
  let mode='login';
  function setMode(next){mode=next==='signup'?'signup':'login';const root=document.getElementById('eggyAuthOverlay');if(!root)return;root.querySelectorAll('.eggy-auth-tab').forEach(b=>b.classList.toggle('active',b.dataset.mode===mode));root.querySelector('#eggyAuthTitle').textContent=mode==='signup'?'Create your EggyPDF account':'Sign in to EggyPDF';root.querySelector('#eggyAuthCopy').textContent=mode==='signup'?'Create one account for Career Pro access on your other devices.':'Use your account to keep Career Pro access available across devices.';root.querySelector('#eggyAuthSubmit').textContent=mode==='signup'?'Create account':'Sign in';root.querySelector('#eggyAuthPassword').autocomplete=mode==='signup'?'new-password':'current-password';root.querySelector('#eggyCreatorField').style.display=mode==='signup'?'block':'none';const saved=localStorage.getItem(CREATOR_KEY);if(saved)root.querySelector('#eggyCreatorCode').value=saved;status('','')}
  function status(msg,type){const el=document.getElementById('eggyAuthStatus');if(!el)return;el.textContent=msg||'';el.className='eggy-auth-status'+(msg?' show '+(type||''):'')}
  function showEmailConfirmationNotice(email){
    setMode('login');
    const root=document.getElementById('eggyAuthOverlay');if(!root)return;
    root.querySelector('#eggyAuthEmail').value=email||'';
    root.querySelector('#eggyAuthPassword').value='';
    root.querySelector('#eggyAuthTitle').textContent='Please confirm your email';
    root.querySelector('#eggyAuthCopy').textContent='We sent a confirmation link to '+email+'. Open that email and confirm your account before signing in.';
    root.querySelector('#eggyAuthSubmit').textContent='Sign in after confirmation';
    status('Please confirm your email account. After you click the confirmation link, come back here and sign in.','confirm');
  }
  async function submitAuth(e){e.preventDefault();const email=document.getElementById('eggyAuthEmail').value.trim(),password=document.getElementById('eggyAuthPassword').value,btn=document.getElementById('eggyAuthSubmit');btn.disabled=true;status(mode==='signup'?'Creating your account…':'Signing you in…','');try{if(mode==='signup'){const code=document.getElementById('eggyCreatorCode').value.trim().toUpperCase();if(code)localStorage.setItem(CREATOR_KEY,code);const d=await signup(email,password);if(d.needs_email_confirmation){showEmailConfirmationNotice(email);return}}else await login(email,password);let redeemed=null;try{redeemed=await redeemPendingCreatorCode()}catch(codeErr){status('Signed in. Creator Code was not applied: '+codeErr.message,'error');resolveWaiters(true);return}status(redeemed?'Signed in. Creator Code applied — Career Pro is active.':'Signed in successfully.','ok');resolveWaiters(true);setTimeout(()=>close(true),350)}catch(err){status(err.message||'Something went wrong.','error')}finally{btn.disabled=false}}
  function open(which){ensureModal();setMode(which||'login');document.getElementById('eggyAuthOverlay').classList.add('show');document.body.style.overflow='hidden';setTimeout(()=>document.getElementById('eggyAuthEmail')?.focus(),50)}
  function close(success){const el=document.getElementById('eggyAuthOverlay');if(el)el.classList.remove('show');document.body.style.overflow='';if(!success)resolveWaiters(false)}
  function resolveWaiters(ok){const waiters=authWaiters.splice(0);waiters.forEach(x=>ok?x.resolve(readSession()):x.reject(Error('Sign in was cancelled.')))}
  function requireAuth(which){if(token())return Promise.resolve(readSession());open(which||'login');return new Promise((resolve,reject)=>authWaiters.push({resolve,reject}))}

  function headerHost(){return document.querySelector('.header-actions')||document.querySelector('.head-actions')||document.querySelector('header .header-inner')||document.querySelector('header .head')}
  async function renderHeader(){
    const host=headerHost(); if(!host)return;
    let slot=document.getElementById('eggyAccountSlot');
    if(!slot){slot=document.createElement('div');slot.id='eggyAccountSlot';slot.className='eggy-account-slot';host.appendChild(slot)}
    const s=readSession();
    if(!s){slot.innerHTML='<button class="eggy-account-btn" type="button" data-eggy-login>Sign in</button><button class="eggy-account-btn primary" type="button" data-eggy-signup>Sign up</button>';slot.querySelector('[data-eggy-login]').onclick=()=>open('login');slot.querySelector('[data-eggy-signup]').onclick=()=>open('signup');return}
    const info=meCache;const email=info?.user?.email||s.user?.email||'Account';const pro=!!info?.career_pro?.active;
    slot.innerHTML=`<div class="eggy-account-user">${pro?'<span class="eggy-pro-pill">Career Pro</span>':''}<span class="eggy-account-email" title="${escapeHtml(email)}">${escapeHtml(email)}</span><div class="eggy-account-menu"><button class="eggy-account-btn" type="button" id="eggyAccountMenuBtn">Account ▾</button><div class="eggy-account-menu-panel"><div class="meta"><b>${escapeHtml(email)}</b><span>${pro?'Career Pro active':'Free account'}</span></div>${pro?'<a href="/career-pro.html">Open Career Pro</a>':'<button type="button" id="eggyRedeemCreatorBtn">Redeem Creator Code</button>'}<button type="button" id="eggyLogoutBtn">Sign out</button></div></div></div>`;
    const menu=slot.querySelector('.eggy-account-menu');slot.querySelector('#eggyAccountMenuBtn').onclick=e=>{e.stopPropagation();menu.classList.toggle('open')};const redeemBtn=slot.querySelector('#eggyRedeemCreatorBtn');if(redeemBtn)redeemBtn.onclick=async()=>{const code=prompt('Enter your one-time EggyPDF Creator Code');if(!code)return;try{await redeemCreatorCode(code);alert('Creator Code applied. Career Pro is now active.')}catch(e){alert(e.message||'Could not redeem Creator Code.')}};slot.querySelector('#eggyLogoutBtn').onclick=logout;
  }
  function escapeHtml(v){return String(v||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot',"'":'&#39;'}[c]))}

  function wireLegacyHomeButtons(){
    document.querySelectorAll('[onclick*="showSignInModal"]').forEach((b,i)=>{b.removeAttribute('onclick');b.style.display='none';b.onclick=()=>open(i===0?'login':'signup')});
    window.showSignInModal=()=>open('login');window.closeSignInModal=()=>close(false);window.closeModalOnBackdrop=()=>{};
    const old=document.getElementById('signInModal');if(old)old.remove();
  }
  document.addEventListener('click',()=>document.querySelectorAll('.eggy-account-menu.open').forEach(x=>x.classList.remove('open')));
  document.addEventListener('keydown',e=>{if(e.key==='Escape')close(false)});
  document.addEventListener('DOMContentLoaded',()=>{ensureModal();wireLegacyHomeButtons();renderHeader();if(token())me(true)});

  window.EggyAccount={API,readSession,token,headers,fetch:accountFetch,me,login,signup,logout,open,close,requireAuth,refresh,renderHeader,redeemCreatorCode,isSignedIn:()=>!!token()};
})();
