(()=>{
  'use strict';
  function mask(v){if(!v)return'';return v.length>10?`${v.slice(0,6)}…${v.slice(-4)}`:'••••••••'}
  function loadMapboxPoiV2(){
    if(document.querySelector('script[data-lumina-mapbox-poi-v2]'))return;
    const s=document.createElement('script');s.src='mapbox-poi-v2.js?v=58';s.defer=true;s.dataset.luminaMapboxPoiV2='1';document.head.appendChild(s);
  }
  function mount(){
    loadMapboxPoiV2();
    const list=document.querySelector('.settings-list');if(!list||document.querySelector('#googlePlacesKeyRow'))return;
    const stored=localStorage.getItem('lumina-google-maps-api-key')||'';
    const row=document.createElement('div');row.id='googlePlacesKeyRow';row.style.cssText='padding:12px 0;border-top:1px solid rgba(255,255,255,.08);display:grid;gap:8px';
    row.innerHTML=`<strong style="font-size:14px">Google Places</strong><small id="googleKeyStatus" style="opacity:.75">${stored?`Key αποθηκευμένο: ${mask(stored)}`:'Δεν έχει αποθηκευτεί API key σε αυτή τη συσκευή.'}</small><input id="googlePlacesKeyInput" type="password" autocomplete="off" placeholder="Google Maps API key" style="width:100%;box-sizing:border-box;padding:10px;border-radius:10px;border:1px solid rgba(255,255,255,.15);background:#111827;color:#fff"><button id="googlePlacesKeySave" type="button" style="padding:10px;border:0;border-radius:10px;font-weight:700">Αποθήκευση key</button>`;
    list.appendChild(row);
    row.querySelector('#googlePlacesKeySave')?.addEventListener('click',()=>{const input=row.querySelector('#googlePlacesKeyInput'),v=String(input?.value||'').trim();if(!v)return;window.LuminaGooglePlaces?.saveKey?.(v);row.querySelector('#googleKeyStatus').textContent=`Key αποθηκευμένο: ${mask(v)} · Google Places ενεργό`;input.value='';});
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mount,{once:true});else mount();
})();