"""Add a minimal subscription control to the packaged Career Pro workspace."""
from pathlib import Path

STYLE = r'''<style id="careerSubscriptionStyle">
.sub-manage{border:1px solid #e5e7eb;background:#fff;color:#374151;border-radius:8px;padding:7px 10px;font-size:11px;font-weight:700;cursor:pointer;margin-right:8px}.sub-panel{position:fixed;inset:0;background:rgba(17,24,39,.55);z-index:10020;display:none;align-items:center;justify-content:center;padding:18px}.sub-panel.open{display:flex}.sub-box{width:min(460px,100%);background:#fff;border-radius:15px;border:1px solid #e5e7eb;padding:20px;box-shadow:0 22px 60px rgba(0,0,0,.22)}.sub-box h3{margin:0 0 6px}.sub-box p{color:#6b7280;font-size:12.5px;line-height:1.55}.sub-meta{background:#f9fafb;border:1px solid #e5e7eb;border-radius:9px;padding:11px;margin:12px 0;font-size:12px}.sub-actions{display:flex;gap:8px;justify-content:flex-end}.sub-actions button{border-radius:8px;padding:10px 12px;font-weight:800;cursor:pointer}.sub-keep{border:1px solid #e5e7eb;background:#fff}.sub-stop{border:0;background:#1a1a2e;color:#fff}.sub-stop:disabled{opacity:.55}.sub-msg{font-size:11.5px;margin-top:10px}.sub-msg.ok{color:#166534}.sub-msg.err{color:#991b1b}
</style>'''

HTML = r'''<div class="sub-panel" id="subscriptionPanel" aria-hidden="true"><div class="sub-box"><h3>Career Pro subscription</h3><p id="subscriptionCopy">Manage your future renewal. Stopping renewal does not end the Career Pro period you already paid for.</p><div class="sub-meta" id="subscriptionMeta">Loading subscription details…</div><div class="sub-actions"><button class="sub-keep" id="subscriptionClose" type="button">Close</button><button class="sub-stop" id="subscriptionStop" type="button">Stop Next Renewal</button></div><div class="sub-msg" id="subscriptionMsg"></div></div></div>'''

JS = r'''<script id="careerSubscriptionScript">
(function(){const API='https://eggypdf-backend-1.onrender.com',ACCOUNT_KEY='eggypdf_account_session';let state=null;const el=id=>document.getElementById(id);function getToken(){try{return JSON.parse(localStorage.getItem(ACCOUNT_KEY)||'null')?.access_token||''}catch(_){return''}}function hdr(json=false){let h={Authorization:'Bearer '+getToken()};if(json)h['Content-Type']='application/json';return h}function fmtDate(x){if(!x)return'End of current paid period';let d=new Date(x);return Number.isNaN(d.getTime())?x:d.toLocaleDateString(undefined,{year:'numeric',month:'short',day:'numeric'})}async function load(){let r=await fetch(API+'/api/billing/me',{headers:hdr()}),d=await r.json();if(!r.ok||!d.success)throw Error(d.error||'Could not load subscription.');state=d.career_pro?.entitlement||null;let plan=(state?.plan||'Career Pro').replace(/^./,c=>c.toUpperCase()),credits=d.credits?.balance;let parts=['Plan: '+plan];if(credits!==undefined&&credits!==null)parts.push('Credits: '+Number(credits).toLocaleString()+' / '+Number(d.credits?.monthly_allowance||2000).toLocaleString());if(state?.current_period_end)parts.push('Current period ends: '+fmtDate(state.current_period_end));if(state?.cancel_at_period_end)parts.push('Future renewal: stopped');el('subscriptionMeta').textContent=parts.join(' · ');el('subscriptionStop').style.display=state?.source==='dodo'?'inline-block':'none';if(state?.cancel_at_period_end){el('subscriptionStop').disabled=true;el('subscriptionStop').textContent='Renewal Already Stopped';el('subscriptionCopy').textContent='Career Pro stays active until '+fmtDate(state.access_ends_at||state.current_period_end)+'.'}}async function open(){el('subscriptionPanel').classList.add('open');el('subscriptionPanel').setAttribute('aria-hidden','false');el('subscriptionMsg').textContent='';try{await load()}catch(e){el('subscriptionMeta').textContent=e.message}}function close(){el('subscriptionPanel').classList.remove('open');el('subscriptionPanel').setAttribute('aria-hidden','true')}async function stop(){if(!state||state.source!=='dodo')return;let end=fmtDate(state.current_period_end);if(!confirm('Stop the next Career Pro renewal? Your current paid access will continue until '+end+'.'))return;let b=el('subscriptionStop');b.disabled=true;b.textContent='Stopping renewal…';el('subscriptionMsg').className='sub-msg';el('subscriptionMsg').textContent='';try{let r=await fetch(API+'/api/billing/subscription/cancel-renewal',{method:'POST',headers:hdr(true),body:'{}'}),d=await r.json();if(!r.ok||!d.success)throw Error(d.error||'Could not stop renewal.');el('subscriptionMsg').className='sub-msg ok';el('subscriptionMsg').textContent=d.message||'Future renewal is stopped.';await load()}catch(e){el('subscriptionMsg').className='sub-msg err';el('subscriptionMsg').textContent=e.message;b.disabled=false;b.textContent='Stop Next Renewal'}}window.addEventListener('DOMContentLoaded',()=>{let head=document.querySelector('.head'),back=head?.querySelector('.back');if(head&&back&&!document.getElementById('manageCareerSubscription')){let b=document.createElement('button');b.id='manageCareerSubscription';b.type='button';b.className='sub-manage';b.textContent='Subscription';b.onclick=open;head.insertBefore(b,back)}el('subscriptionClose').onclick=close;el('subscriptionStop').onclick=stop;el('subscriptionPanel').onclick=e=>{if(e.target===el('subscriptionPanel'))close()}})})();
</script>'''


def patch(path):
    p=Path(path); s=p.read_text()
    if 'careerSubscriptionStyle' not in s:
        s=s.replace('</head>',STYLE+'</head>',1)
    if 'careerSubscriptionScript' not in s:
        s=s.replace('</body>',HTML+JS+'</body>',1)
    p.write_text(s)


def validate(path):
    s=Path(path).read_text()
    assert 'id="subscriptionPanel"' in s
    assert 'Stop Next Renewal' in s
    assert '/api/billing/subscription/cancel-renewal' in s
    assert 'Cancel anytime' not in s


if __name__=='__main__':
    import sys
    patch(sys.argv[1]); validate(sys.argv[1])
