(()=>{
  'use strict';
  function mask(v){if(!v)return'';return v.length>12?`${v.slice(0,7)}…${v.slice(-5)}`:'••••••••'}
  function mount(){
    const list=document.querySelector('.settings-list');if(!list||document.querySelector('#mapboxKeyRow'))return;
    const stored=localStorage.getItem('lumina-mapbox-public-token')||'';
    const row=document.createElement('div');row.id='mapboxKeyRow';row.style.cssText='padding:12px 0;border-top:1px solid rgba(255,255,255,.08);display:grid;gap:8px';
    row.innerHTML=`<strong style="font-size:14px">Mapbox — Σημεία ενδιαφέροντος</strong><small id="mapboxKeyStatus" style="opacity:.75">${stored?`Token αποθηκευμένο: ${mask(stored)} · Mapbox ενεργό`:'Δεν έχει αποθηκευτεί Mapbox token σε αυτή τη συσκευή.'}</small><input id="mapboxKeyInput" type="password" autocomplete="off" placeholder="Mapbox public token (pk....)" style="width:100%;box-sizing:border-box;padding:10px;border-radius:10px;border:1px solid rgba(255,255,255,.15);background:#111827;color:#fff"><button id="mapboxKeySave" type="button" style="padding:10px;border:0;border-radius:10px;font-weight:700">Αποθήκευση Mapbox token</button>`;
    list.appendChild(row);
    row.querySelector('#mapboxKeySave')?.addEventListener('click',()=>{const input=row.querySelector('#mapboxKeyInput'),v=String(input?.value||'').trim();if(!v)return;if(!v.startsWith('pk.')){row.querySelector('#mapboxKeyStatus').textContent='Χρειάζεται public Mapbox token που αρχίζει από pk.';return}window.LuminaMapboxPlaces?.saveKey?.(v);row.querySelector('#mapboxKeyStatus').textContent=`Token αποθηκευμένο: ${mask(v)} · Mapbox ενεργό για όλα τα POI`;input.value='';});
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mount,{once:true});else mount();
})();
