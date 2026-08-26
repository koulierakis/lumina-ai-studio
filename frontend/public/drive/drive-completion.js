// LUMINA Drive Assistant completion layer
(() => {
  'use strict';
  const $ = s => document.querySelector(s);
  const SESSION_KEY = 'lumina-drive-session-v1';
  const safeClick = el => { if (el) el.click(); };
  let arrivalHandled = false;

  function loadScript(src, marker) {
    if (document.querySelector(`script[${marker}]`)) return Promise.resolve();
    return new Promise((resolve,reject)=>{const script=document.createElement('script');script.src=src;script.async=false;script.setAttribute(marker,'1');script.onload=resolve;script.onerror=reject;document.head.appendChild(script)});
  }
  async function loadGoogleAndPoi() {
    try{await loadScript('./google-places.js?v=49','data-lumina-google-places');await loadScript('./google-key-settings.js?v=49','data-lumina-google-key-settings')}catch(e){console.warn('LUMINA Google bootstrap failed',e)}
    if (document.querySelector('script[data-lumina-poi-enhanced]')) return;
    const script = document.createElement('script');
    script.src = './poi-enhanced.js?v=49';
    script.async = true;
    script.dataset.luminaPoiEnhanced = '1';
    document.head.appendChild(script);
  }

  function buildHomeToolbar(){
    if ($('#homeToolbar')) return;
    const travel=$('.travel-mode');
    const actions=$('.home-actions');
    if(!travel||!actions)return;
    const bar=document.createElement('nav');
    bar.id='homeToolbar';bar.className='home-toolbar pretrip-ui';bar.setAttribute('aria-label','Κύρια εργαλεία Drive');
    const drive=travel.querySelector('[data-travel-mode="drive"]'),walk=travel.querySelector('[data-travel-mode="walk"]'),poi=$('#poiOpenBtn'),free=$('#freeDriveBtn');
    if(drive){drive.classList.add('home-tool');drive.innerHTML='<span>🚗</span><small>Αυτοκίνητο</small>';bar.appendChild(drive)}
    if(walk){walk.classList.add('home-tool');walk.innerHTML='<span>🚶</span><small>Περπάτημα</small>';bar.appendChild(walk)}
    if(poi){poi.className='home-tool';poi.innerHTML='<span>📍</span><small>Κοντά μου</small>';bar.appendChild(poi)}
    if(free){free.className='home-tool';free.innerHTML='<span>◎</span><small>Free Drive</small>';bar.appendChild(free)}
    document.body.appendChild(bar);travel.classList.add('toolbar-source-hidden');actions.classList.add('toolbar-source-hidden');
  }
  function setText(id,value){const el=$(id);if(el)el.textContent=value}
  function persistFreeDrive(on){try{const raw=JSON.parse(localStorage.getItem(SESSION_KEY)||'{}');raw.freeDrive=!!on;localStorage.setItem(SESSION_KEY,JSON.stringify(raw))}catch{}}
  function normalizeFreeDriveButton(on){const button=$('#freeDriveBtn');if(!button)return;button.classList.toggle('active',!!on);button.setAttribute('aria-pressed',String(!!on));const label=button.querySelector('small');if(label)label.textContent=on?'Free Drive ON':'Free Drive'}
  function enterFreeDriveUI(){document.body.classList.add('free-drive-active');$('#navCockpit')?.classList.remove('hidden');setText('#navDestination','Free Drive');setText('#navRoad',$('#roadName')?.textContent||'Τρέχουσα θέση');setText('#navSpeed',$('#speed')?.textContent||'0');setText('#navSpeedLimit',$('#speedLimit')?.textContent||'—');normalizeFreeDriveButton(true);persistFreeDrive(true);setTimeout(()=>window.dispatchEvent(new Event('resize')),100)}
  function leaveFreeDriveUI(){document.body.classList.remove('free-drive-active');normalizeFreeDriveButton(false);persistFreeDrive(false);if(!document.body.classList.contains('navigation-active'))$('#navCockpit')?.classList.add('hidden')}
  function freeDriveIsOn(){const b=$('#freeDriveBtn');return!!(b&&(b.getAttribute('aria-pressed')==='true'||b.classList.contains('active')))}
  function syncFreeDrive(){freeDriveIsOn()?enterFreeDriveUI():leaveFreeDriveUI()}
  function speakStatus(){const speed=$('#speed')?.textContent||'0',limit=$('#speedLimit')?.textContent||'άγνωστο',road=$('#roadName')?.textContent||'την τρέχουσα θέση';if(!('speechSynthesis'in window))return;speechSynthesis.cancel();const u=new SpeechSynthesisUtterance(`Τρέχουσα ταχύτητα ${speed} χιλιόμετρα την ώρα. Όριο ${limit}. Βρίσκεσαι σε ${road}.`);u.lang='el-GR';u.rate=.96;speechSynthesis.speak(u)}
  function reportDanger(){const list=$('#alertsList');if(list)list.insertAdjacentHTML('afterbegin','<div class="alert manual-danger"><span>⚠️</span><div><b>Κίνδυνος</b><small>Χειροκίνητη οδηγική επισήμανση.</small></div></div>');if('vibrate'in navigator)navigator.vibrate([180,100,180])}
  function observeArrival(){const maneuver=$('#maneuverText');if(!maneuver||!window.MutationObserver)return;const check=()=>{const arrived=maneuver.textContent.trim()==='Άφιξη';if(!arrived){arrivalHandled=false;return}if(arrivalHandled)return;arrivalHandled=true;setTimeout(()=>{if(maneuver.textContent.trim()==='Άφιξη')safeClick($('#stopRouteBtn'))},2500)};new MutationObserver(check).observe(maneuver,{childList:true,characterData:true,subtree:true});check()}
  function bind(){buildHomeToolbar();loadGoogleAndPoi();const free=$('#freeDriveBtn');free?.addEventListener('click',()=>setTimeout(syncFreeDrive,0));$('#navStopBtn')?.addEventListener('click',()=>{if(freeDriveIsOn())safeClick(free);setTimeout(leaveFreeDriveUI,0)});const statusBtn=document.createElement('button');statusBtn.type='button';statusBtn.id='navStatusBtn';statusBtn.className='nav-mini';statusBtn.textContent='🔊';statusBtn.setAttribute('aria-label','Κατάσταση οδήγησης');statusBtn.addEventListener('click',speakStatus);const dock=$('#navVoiceDock');if(dock&&!$('#navStatusBtn'))dock.appendChild(statusBtn);const mic=$('#navVoiceBtn');let timer=null;mic?.addEventListener('pointerdown',()=>{timer=setTimeout(reportDanger,900)});['pointerup','pointercancel','pointerleave'].forEach(ev=>mic?.addEventListener(ev,()=>{if(timer)clearTimeout(timer);timer=null}));syncFreeDrive();observeArrival()}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind,{once:true});else bind();
})();