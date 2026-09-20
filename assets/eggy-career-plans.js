(function(){
  'use strict';
  const API='https://eggypdf-backend-1.onrender.com';
  const CHECKOUT_KEY='eggypdf_career_billing_checkout';
  let selected='annual', target='/career-pro.html';
  function ensure(){
    if(document.getElementById('eggyPlanOverlay'))return;
    const x=document.createElement('div');x.id='eggyPlanOverlay';x.className='eggy-plan-overlay';x.innerHTML=`<div class="eggy-plan-card" role="dialog" aria-modal="true" aria-labelledby="eggyPlanTitle"><button class="eggy-plan-close" type="button" aria-label="Close">×</button><div class="eggy-plan-head"><svg class="eggy-plan-crown" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7.5 7.5 11 12 4l4.5 7L21 7.5 19.2 18H4.8L3 7.5Zm2.7 8.5h12.6l.7-4.1-2.9 2.2-4.1-6.3-4.1 6.3L5 11.9 5.7 16Z"/></svg><h2 id="eggyPlanTitle">Career Pro</h2><p>Choose the plan that fits you. Every paid plan includes 2,000 AI credits each month.</p></div><div class="eggy-plan-toggle"><button type="button" class="eggy-plan-choice" data-plan="monthly">Monthly Billing</button><button type="button" class="eggy-plan-choice active" data-plan="annual">Yearly Billing<span class="eggy-save-tag">SAVE 43%</span></button></div><div class="eggy-plan-main"><div class="eggy-plan-price"><div><span class="amount" id="eggyPlanAmount">$4</span> <span class="period">/ month</span></div><div class="eggy-plan-billed" id="eggyPlanBilled">$48 USD billed annually</div><div class="eggy-plan-save" id="eggyPlanSave">Save $35.88 per year</div></div><div class="eggy-plan-credits"><div><b>2,000 AI credits / month</b><br><span>Credits refresh each month while Career Pro is active.</span></div><span id="eggyPlanValue">Best value</span></div><div class="eggy-plan-features"><div><span class="eggy-plan-check">✓</span><strong>Free ATS + CV extraction</strong> — 0 credits</div><div><span class="eggy-plan-check">✓</span><strong>AI Resume Optimizer</strong> — 100 credits</div><div><span class="eggy-plan-check">✓</span><strong>AI Cover Letter</strong> — 50 credits</div><div><span class="eggy-plan-check">✓</span><strong>Section Regeneration</strong> — 20 credits</div><div><span class="eggy-plan-check">✓</span><strong>AI PDF Summarizer</strong> — 25 credits</div><div><span class="eggy-plan-check">✓</span><strong>PDF & DOCX export</strong> — 0 credits</div></div><button class="eggy-plan-continue" id="eggyPlanContinue" type="button">Continue with Yearly</button><div class="eggy-plan-status" id="eggyPlanStatus"></div><div class="eggy-plan-note">Your selected billing amount is shown before payment.</div></div></div>`;
    document.body.appendChild(x);
    x.querySelector('.eggy-plan-close').onclick=close;
    x.addEventListener('click',e=>{if(e.target===x)close()});
    x.querySelectorAll('[data-plan]').forEach(b=>b.onclick=()=>select(b.dataset.plan));
    x.querySelector('#eggyPlanContinue').onclick=continueCheckout;
  }
  function status(msg,type){const e=document.getElementById('eggyPlanStatus');if(!e)return;e.textContent=msg||'';e.className='eggy-plan-status'+(msg?' show '+(type||''):'')}
  function select(plan){selected=plan==='monthly'?'monthly':'annual';document.querySelectorAll('#eggyPlanOverlay [data-plan]').forEach(b=>b.classList.toggle('active',b.dataset.plan===selected));const annual=selected==='annual';document.getElementById('eggyPlanAmount').textContent=annual?'$4':'$6.99';document.getElementById('eggyPlanBilled').textContent=annual?'$48 USD billed annually':'$6.99 USD billed monthly';document.getElementById('eggyPlanSave').style.display=annual?'inline-block':'none';document.getElementById('eggyPlanValue').textContent=annual?'Best value':'Monthly plan';document.getElementById('eggyPlanContinue').textContent=annual?'Continue with Yearly':'Continue with Monthly';status('','')}
  async function recoverAccount(){try{if(!window.EggyAccount?.isSignedIn?.())return false;const r=await EggyAccount.fetch(API+'/api/billing/reconcile-account');let d={};try{d=await r.json()}catch(_){d={}}if(!r.ok||!d.success||!d.active)return false;const a=await EggyAccount.me(true);EggyAccount.renderHeader?.();return !!a?.career_pro?.active}catch(_){return false}}
  async function open(opts){
    opts=opts||{}; target=opts.target||'/career-pro.html';
    try{const a=await window.EggyAccount?.me(true);if(a?.career_pro?.active){location.href=target;return}if(await recoverAccount()){location.href=target;return}}catch(_){}
    ensure();select('annual');document.getElementById('eggyPlanOverlay').classList.add('show');document.body.style.overflow='hidden';
  }
  function close(){const e=document.getElementById('eggyPlanOverlay');if(e)e.classList.remove('show');document.body.style.overflow=''}
  async function continueCheckout(){const btn=document.getElementById('eggyPlanContinue');try{
    if(!window.EggyAccount)throw Error('Account system is still loading. Please try again.');
    await EggyAccount.requireAuth('login');
    const a=await EggyAccount.me(true);if(a?.career_pro?.active){close();location.href=target;return}
    if(await recoverAccount()){close();location.href=target;return}
    btn.disabled=true;btn.textContent='Opening secure checkout…';status('Preparing your '+(selected==='annual'?'yearly':'monthly')+' Career Pro checkout…','');
    const r=await EggyAccount.fetch(API+'/api/billing/checkout-session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({plan:selected==='annual'?'yearly':'monthly'})});
    let text='';try{text=await r.text()}catch(_){}let d={};if(text){try{d=JSON.parse(text)}catch(_){throw Error('The payment service returned an unexpected response. Please try again in a moment.')}}if(!r.ok||!d.success||!d.checkout_url||!d.session_id)throw Error(d.error||'Could not start checkout.');
    localStorage.setItem(CHECKOUT_KEY,d.session_id);localStorage.setItem(CHECKOUT_KEY+'_plan',selected);localStorage.setItem(CHECKOUT_KEY+'_target',target);location.assign(d.checkout_url);
  }catch(e){if(e.message!=='Sign in was cancelled.')status(e.message||'Could not start checkout.','error');btn.disabled=false;btn.textContent=selected==='annual'?'Continue with Yearly':'Continue with Monthly'}}
  document.addEventListener('click',async e=>{const a=e.target.closest('a[href*="career-pro.html"]');if(!a||a.dataset.eggyNoPlan==='1')return;e.preventDefault();await open({target:a.getAttribute('href')||'/career-pro.html'})});
  document.addEventListener('keydown',e=>{if(e.key==='Escape')close()});
  document.addEventListener('DOMContentLoaded',ensure);
  window.EggyCareerPlans={open,close,select,recoverAccount};
})();
