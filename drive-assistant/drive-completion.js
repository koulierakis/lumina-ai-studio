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
    stop: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="7" y="7" width="10" height="10" rx="1.5"/></svg>',
    straight: '<svg viewBox="0 0 32 32" aria-hidden="true"><path d="M16 27V7M9 14l7-7 7 7"/></svg>',
    right: '<svg viewBox="0 0 32 32" aria-hidden="true"><path d="M9 26V17a6 6 0 0 1 6-6h9M19 6l5 5-5 5"/></svg>',
    left: '<svg viewBox="0 0 32 32" aria-hidden="true"><path d="M23 26V17a6 6 0 0 0-6-6H8M13 6l-5 5 5 5"/></svg>',
    slightRight: '<svg viewBox="0 0 32 32" aria-hidden="true"><path d="M10 26v-8c0-5 3-8 8-9h6M19 4l5 5-5 5"/></svg>',
    slightLeft: '<svg viewBox="0 0 32 32" aria-hidden="true"><path d="M22 26v-8c0-5-3-8-8-9H8M13 4L8 9l5 5"/></svg>',
    uturn: '<svg viewBox="0 0 32 32" aria-hidden="true"><path d="M23 27V15a7 7 0 0 0-14 0v5M4 16l5 5 5-5"/></svg>',
    roundabout: '<svg viewBox="0 0 32 32" aria-hidden="true"><path d="M12 8a9 9 0 1 1-2 14M8 13l4-5-6-1"/><path d="M21 11l5-4M24 6l2 1 1 2"/></svg>',
    arrive: '<svg viewBox="0 0 32 32" aria-hidden="true"><path d="M8 27V5M9 6h13l-3 5 3 5H9"/></svg>'
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
    style.textContent='.drive-vector-icon{display:grid!important;place-items:center;width:22px!important;height:22px!important;line-height:1!important;color:currentColor}.drive-vector-icon svg{width:22px;height:22px;display:block}.home-tool>.drive-vector-icon{width:23px!important;height:23px!important}.home-tool>.drive-vector-icon svg{width:23px;height:23px}.nav-tool>.drive-vector-icon{width:20px!important;height:20px!important}.nav-tool>.drive-vector-icon svg{width:20px;height:20px}.nav-mini .drive-vector-icon svg{width:19px;height:19px}.maneuver-card{grid-template-columns:58px minmax(0,1fr) auto!important;display:grid!important}.maneuver-card.hidden{display:none!important}.maneuver-symbol{width:52px;height:52px;border-radius:16px;background:linear-gradient(145deg,rgba(87,221,209,.24),rgba(87,221,209,.08));border:1px solid rgba(87,221,209,.3);display:grid;place-items:center;color:#8cf2e8;box-shadow:inset 0 1px 0 rgba(255,255,255,.08)}.maneuver-symbol .drive-vector-icon,.maneuver-symbol .drive-vector-icon svg{width:34px!important;height:34px!important}.maneuver-card>div{min-width:0}.maneuver-card #maneuverDistance{font-size:16px;font-weight:900;color:#fff;white-space:nowrap}.maneuver-card #maneuverText{display:block;white-space:normal;line-height:1.15}.maneuver-card .maneuver-prefix{display:block;color:#8fa2b9;font-size:10px;font-weight:800;margin-bottom:2px}@media(max-width:380px){.maneuver-card{grid-template-columns:50px minmax(0,1fr) auto!important;gap:8px!important}.maneuver-symbol{width:46px;height:46px;border-radius:14px}.maneuver-symbol .drive-vector-icon,.maneuver-symbol .drive-vector-icon svg{width:30px!important;height:30px!important}.maneuver-card #maneuverDistance{font-size:14px}}';
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

  function maneuverKind(text=''){
    const t=String(text).toLocaleLowerCase('el-GR');
    if(t.includes('άφιξη')||t.includes('φτάν'))return'arrive';
    if(t.includes('αναστροφ'))return'uturn';
    if(t.includes('κυκλικ'))return'roundabout';
    if(t.includes('ελαφρά')&&t.includes('δεξ'))return'slightRight';
    if(t.includes('ελαφρά')&&t.includes('αριστερ'))return'slightLeft';
    if(t.includes('δεξ'))return'right';
    if(t.includes('αριστερ'))return'left';
    return'straight';
  }

  function enhanceManeuverCard(){
    const card=$('#maneuverCard'),text=$('#maneuverText'),distance=$('#maneuverDistance');
    if(!card||!text||!distance)return;
    let symbol=card.querySelector('.maneuver-symbol');
    if(!symbol){symbol=document.createElement('div');symbol.className='maneuver-symbol';symbol.setAttribute('aria-hidden','true');card.insertBefore(symbol,card.firstChild)}
    const copy=text.parentElement;
    let prefix=copy?.querySelector('.maneuver-prefix');
    const originalSmall=copy?.querySelector('small');
    if(originalSmall)originalSmall.textContent='ΕΠΟΜΕΝΗ ΟΔΗΓΙΑ';
    if(copy&&!prefix){prefix=document.createElement('span');prefix.className='maneuver-prefix';prefix.textContent='Ακολουθεί';copy.insertBefore(prefix,text)}
    const refresh=()=>{const current=text.textContent||'';symbol.innerHTML=icon(maneuverKind(current));const d=distance.textContent?.trim();if(prefix)prefix.textContent=d&&d!=='—'?`Σε ${d}`:'Ακολουθεί'};
    new MutationObserver(refresh).observe(text,{childList:true,characterData:true,subtree:true});
    new MutationObserver(refresh).observe(distance,{childList:true,characterData:true,subtree:true});
    refresh();
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
  function bind(){installPremiumIconStyles();buildHomeToolbar();decorateNavToolbar();enhanceManeuverCard();loadGoogleAndPoi();const free=$('#freeDriveBtn');free?.addEventListener('click',()=>setTimeout(syncFreeDrive,0));$('#navStopBtn')?.addEventListener('click',()=>{if(freeDriveIsOn())safeClick(free);setTimeout(leaveFreeDriveUI,0)});const statusBtn=document.createElement('button');statusBtn.type='button';statusBtn.id='navStatusBtn';statusBtn.className='nav-mini';statusBtn.innerHTML=icon('speaker');statusBtn.setAttribute('aria-label','Κατάσταση οδήγησης');statusBtn.addEventListener('click',speakStatus);const dock=$('#navVoiceDock');if(dock&&!$('#navStatusBtn'))dock.appendChild(statusBtn);const mic=$('#navVoiceBtn');let timer=null;mic?.addEventListener('pointerdown',()=>{timer=setTimeout(reportDanger,900)});['pointerup','pointercancel','pointerleave'].forEach(ev=>mic?.addEventListener(ev,()=>{if(timer)clearTimeout(timer);timer=null}));syncFreeDrive();observeArrival()}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind,{once:true});else bind();
})();