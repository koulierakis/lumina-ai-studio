// LUMINA Drive Assistant completion layer
(() => {
  'use strict';
  const $ = s => document.querySelector(s);
  const SESSION_KEY = 'lumina-drive-session-v1';
  const safeClick = el => { if (el) el.click(); };
  let arrivalHandled = false;

  const ICONS = {
    drive: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 16h14l-1.2-5.1A2.5 2.5 0 0 0 15.4 9H8.6a2.5 2.5 0 0 0-2.4 1.9L5 16Z"/><path d="M4 16v2.2A1.8 1.8 0 0 0 5.8 20h.4A1.8 1.8 0 0 0 8 18.2V18h8v.2A1.8 1.8 0 0 0 17.8 20h.4a1.8 1.8 0 0 0 1.8-1.8V16"/><circle cx="7.5" cy="15" r="1"/><circle cx="16.5" cy="15" r="1"/></svg>',
    walk: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="13" cy="4.5" r="2"/><path d="m10.5 20 1.2-5.2-2-2.2-1.6 3.1-2.6-1.3 2.4-4.7a2 2 0 0 1 2.9-.8l2.3 1.6 2.1-2.1 1.5 1.6-2.8 2.8-2-1.3-.6 2.3 2.1 2.3 2.1 3.9"/></svg>',
    nearby: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21s6-5.3 6-11a6 6 0 1 0-12 0c0 5.7 6 11 6 11Z"/><circle cx="12" cy="10" r="2.2"/></svg>',
    free: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="7"/><path d="M12 5V2M12 22v-3M5 12H2M22 12h-3"/><circle cx="12" cy="12" r="2.3"/></svg>',
    mic: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M6.5 11.5a5.5 5.5 0 0 0 11 0M12 17v4M9 21h6"/></svg>',
    speaker: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 10v4h3l4 3V7L8 10H5Z"/><path d="M15 9.2a4 4 0 0 1 0 5.6M17.5 6.8a7.5 7.5 0 0 1 0 10.4"/></svg>',
    target: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2.2"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/></svg>',
    menu: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 7h14M5 12h14M5 17h14"/></svg>',
    stop: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="7" y="7" width="10" height="10" rx="1.5"/></svg>'
  };

  function icon(name) {
    const raw = ICONS[name] || '';
    const svg = raw.replace('<svg ', '<svg fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" ');
    return `<span class="drive-vector-icon">${svg}</span>`;
  }

  function installPremiumIconStyles(){
    if ($('#luminaPremiumIconStyles')) return;
    const style=document.createElement('style');
    style.id='luminaPremiumIconStyles';
    style.textContent='.drive-vector-icon{display:grid!important;place-items:center;width:22px!important;height:22px!important;line-height:1!important;color:currentColor}.drive-vector-icon svg{width:22px;height:22px;display:block}.home-tool>.drive-vector-icon{width:23px!important;height:23px!important}.home-tool>.drive-vector-icon svg{width:23px;height:23px}.nav-tool>.drive-vector-icon{width:20px!important;height:20px!important}.nav-tool>.drive-vector-icon svg{width:20px;height:20px}.nav-mini .drive-vector-icon svg{width:19px;height:19px}';
    document.head.appendChild(style);
  }

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
    if(drive){drive.classList.add('home-tool');drive.innerHTML=`${icon('drive')}<small>Αυτοκίνητο</small>`;bar.appendChild(drive)}
    if(walk){walk.classList.add('home-tool');walk.innerHTML=`${icon('walk')}<small>Περπάτημα</small>`;bar.appendChild(walk)}
    if(poi){poi.className='home-tool';poi.innerHTML=`${icon('nearby')}<small>Κοντά μου</small>`;bar.appendChild(poi)}
    if(free){free.className='home-tool';free.innerHTML=`${icon('free')}<small>Free Drive</small>`;bar.appendChild(free)}
    document.body.appendChild(bar);travel.classList.add('toolbar-source-hidden');actions.classList.add('toolbar-source-hidden');
  }

  function decorateNavToolbar(){
    const iconMap={navPoiBtn:'nearby',navVoiceBtn:'mic',navHandsFreeBtn:'speaker',navCenterBtn:'target',navSettingsBtn:'menu',navStopBtn:'stop'};
    Object.entries(iconMap).forEach(([id,name])=>{const button=$(`#${id}`);const span=button?.querySelector('span');if(span)span.outerHTML=icon(name)});
  }

  function setText(id,value){const el=$(id);if(el)el.textContent=value}
  function persistFreeDrive(on){try{const raw=JSON.parse(localStorage.getItem(SESSION_KEY)||'{}');raw.freeDrive=!!on;localStorage.setItem(SESSION_KEY,JSON.stringify(raw))}catch{}}
  function normalizeFreeDriveButton(on){const button=$('#freeDriveBtn');if(!button)return;button.classList.toggle('active',!!on);button.setAttribute('aria-pressed',String(!!on));const label=button.querySelector('small');if(label)label.textContent=on?'Free Drive ON':'Free Drive'}
  function enterFreeDriveUI(){document.body.classList.add('free-drive-active');$('#navCockpit')?.classList.remove('hidden');setText('#navDestination','Free Drive');setText('#navRoad',$('#roadName')?.textContent||'Τρέχουσα θέση');setText('#navSpeed',$('#speed')?.textContent||'0');setText('#navSpeedLimit',$('#speedLimit')?.textContent||'—');normalizeFreeDriveButton(true);persistFreeDrive(true);setTimeout(()=>window.dispatchEvent(new Event('resize')),100)}
  function leaveFreeDriveUI(){document.body.classList.remove('free-drive-active');normalizeFreeDriveButton(false);persistFreeDrive(false);if(!document.body.classList.contains('navigation-active'))$('#navCockpit')?.classList.add('hidden')}
  function freeDriveIsOn(){const b=$('#freeDriveBtn');return!!(b&&(b.getAttribute('aria-pressed')==='true'||b.classList.contains('active')))}
  function syncFreeDrive(){freeDriveIsOn()?enterFreeDriveUI():leaveFreeDriveUI()}
  function speakStatus(){const speed=$('#speed')?.textContent||'0',limit=$('#speedLimit')?.textContent||'άγνωστο',road=$('#roadName')?.textContent||'την τρέχουσα θέση';if(!('speechSynthesis'in window))return;speechSynthesis.cancel();const u=new SpeechSynthesisUtterance(`Τρέχουσα ταχύτητα ${speed} χιλιόμετρα την ώρα. Όριο ${limit}. Βρίσκεσαι σε ${road}.`);u.lang='el-GR';u.rate=.96;speechSynthesis.speak(u)}
  function reportDanger(){const list=$('#alertsList');if(list)list.insertAdjacentHTML('afterbegin','<div class="alert manual-danger"><span aria-hidden="true">!</span><div><b>Κίνδυνος</b><small>Χειροκίνητη οδηγική επισήμανση.</small></div></div>');if('vibrate'in navigator)navigator.vibrate([180,100,180])}
  function observeArrival(){const maneuver=$('#maneuverText');if(!maneuver||!window.MutationObserver)return;const check=()=>{const arrived=maneuver.textContent.trim()==='Άφιξη';if(!arrived){arrivalHandled=false;return}if(arrivalHandled)return;arrivalHandled=true;setTimeout(()=>{if(maneuver.textContent.trim()==='Άφιξη')safeClick($('#stopRouteBtn'))},2500)};new MutationObserver(check).observe(maneuver,{childList:true,characterData:true,subtree:true});check()}
  function bind(){installPremiumIconStyles();buildHomeToolbar();decorateNavToolbar();loadGoogleAndPoi();const free=$('#freeDriveBtn');free?.addEventListener('click',()=>setTimeout(syncFreeDrive,0));$('#navStopBtn')?.addEventListener('click',()=>{if(freeDriveIsOn())safeClick(free);setTimeout(leaveFreeDriveUI,0)});const statusBtn=document.createElement('button');statusBtn.type='button';statusBtn.id='navStatusBtn';statusBtn.className='nav-mini';statusBtn.innerHTML=icon('speaker');statusBtn.setAttribute('aria-label','Κατάσταση οδήγησης');statusBtn.addEventListener('click',speakStatus);const dock=$('#navVoiceDock');if(dock&&!$('#navStatusBtn'))dock.appendChild(statusBtn);const mic=$('#navVoiceBtn');let timer=null;mic?.addEventListener('pointerdown',()=>{timer=setTimeout(reportDanger,900)});['pointerup','pointercancel','pointerleave'].forEach(ev=>mic?.addEventListener(ev,()=>{if(timer)clearTimeout(timer);timer=null}));syncFreeDrive();observeArrival()}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind,{once:true});else bind();
})();