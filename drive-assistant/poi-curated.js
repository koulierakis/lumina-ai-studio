(()=>{
'use strict';
const $=s=>document.querySelector(s);
const drawer=$('#poiDrawer'),cats=$('#poiCategories'),results=$('#poiResults'),title=$('#poiTitle'),back=$('#poiBackBtn');
const GROUPS={
  food:{label:'Φαγητό & Ποτό',items:[['restaurant','🍽️ Εστιατόρια'],['fast_food','🥙 Fast food'],['cafe','☕ Καφέ'],['bar','🍸 Bar / Pub'],['bakery','🥖 Φούρνοι']]},
  essentials:{label:'Χρήσιμα',items:[['pharmacy','💊 Φαρμακεία'],['fuel','⛽ Βενζινάδικα'],['parking','🅿️ Parking'],['supermarket','🛒 Supermarket'],['atm','💶 ATM']]},
  stay:{label:'Διαμονή',items:[['hotel','🏨 Ξενοδοχεία'],['guest_house','🛏️ Ξενώνες'],['camp_site','⛺ Camping']]},
  health:{label:'Υγεία & Ασφάλεια',items:[['hospital','🏥 Νοσοκομεία'],['clinic','🩺 Κλινικές'],['police','👮 Αστυνομία']]},
  leisure:{label:'Αναψυχή',items:[['beach','🏖️ Παραλίες'],['gym','🏋️ Γυμναστήρια'],['attraction','📍 Αξιοθέατα']]}
};
function root(){if(!cats||!results)return;title.textContent='Σημεία ενδιαφέροντος';back.classList.add('hidden');results.innerHTML='';cats.innerHTML=Object.entries(GROUPS).map(([k,g])=>`<button type="button" class="poi-category" data-curated-group="${k}"><strong>${g.label}</strong><span>${g.items.length} επιλογές</span></button>`).join('')}
function group(k){const g=GROUPS[k];if(!g||!cats)return;title.textContent=g.label;back.classList.remove('hidden');results.innerHTML='';cats.innerHTML=g.items.map(([t,l])=>`<button type="button" class="poi-item" data-curated-poi="${t}">${l}</button>`).join('')}
function open(){drawer?.classList.remove('hidden');root()}
function close(){drawer?.classList.add('hidden')}
document.addEventListener('click',e=>{
  const openBtn=e.target.closest?.('#poiOpenBtn,#navPoiBtn');
  const closeBtn=e.target.closest?.('#poiCloseBtn');
  const backBtn=e.target.closest?.('#poiBackBtn');
  const g=e.target.closest?.('[data-curated-group]');
  const p=e.target.closest?.('[data-curated-poi]');
  if(openBtn){e.preventDefault();e.stopImmediatePropagation();open();return}
  if(closeBtn){e.preventDefault();e.stopImmediatePropagation();close();return}
  if(backBtn){e.preventDefault();e.stopImmediatePropagation();root();return}
  if(g){e.preventDefault();e.stopImmediatePropagation();group(g.dataset.curatedGroup);return}
  if(p){e.preventDefault();e.stopImmediatePropagation();const type=p.dataset.curatedPoi;results.innerHTML='<div class="poi-loading busy"><span class="poi-spinner"></span><strong>Mapbox: αναζητώ κοντινά σημεία…</strong></div>';window.LuminaMapboxPOI?.run?.(type);return}
},true);
window.LuminaCuratedPOI={open,root,groups:GROUPS};
})();
