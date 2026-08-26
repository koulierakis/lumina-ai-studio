(()=>{
'use strict';
function mask(v){if(!v)return'';return v.length>12?`${v.slice(0,7)}…${v.slice(-5)}`:'••••••••'}
function fieldStyle(){return'width:100%;box-sizing:border-box;padding:10px;border-radius:10px;border:1px solid rgba(255,255,255,.15);background:#111827;color:#fff'}
function buttonStyle(){return'padding:10px;border:0;border-radius:10px;font-weight:700'}
function mount(){
 const list=document.querySelector('.settings-list');if(!list||document.querySelector('#poiProviderSettings'))return;
 const google=localStorage.getItem('lumina-google-maps-api-key')||'',mapbox=localStorage.getItem('lumina-mapbox-public-token')||'';
 const row=document.createElement('div');row.id='poiProviderSettings';row.style.cssText='padding:12px 0;border-top:1px solid rgba(255,255,255,.08);display:grid;gap:12px';
 row.innerHTML=`<div style="display:grid;gap:8px"><strong style="font-size:14px">Mapbox — Σημεία ενδιαφέροντος</strong><small id="mapboxKeyStatus" style="opacity:.75">${mapbox?`Token αποθηκευμένο: ${mask(mapbox)} · κύρια πηγή POI`:'Δεν έχει αποθηκευτεί Mapbox token.'}</small><input id="mapboxKeyInput" type="password" autocomplete="off" placeholder="Mapbox public token (pk....)" style="${fieldStyle()}"><button id="mapboxKeySave" type="button" style="${buttonStyle()}">Αποθήκευση Mapbox token</button></div><div style="display:grid;gap:8px;border-top:1px solid rgba(255,255,255,.08);padding-top:12px"><strong style="font-size:14px">Google Places</strong><small id="googleKeyStatus" style="opacity:.75">${google?`Key αποθηκευμένο: ${mask(google)}`:'Δεν έχει αποθηκευτεί Google API key.'}</small><input id="googlePlacesKeyInput" type="password" autocomplete="off" placeholder="Google Maps API key" style="${fieldStyle()}"><button id="googlePlacesKeySave" type="button" style="${buttonStyle()}">Αποθήκευση Google key</button></div>`;
 list.appendChild(row);
 row.querySelector('#mapboxKeySave')?.addEventListener('click',()=>{const input=row.querySelector('#mapboxKeyInput'),v=String(input?.value||'').trim(),status=row.querySelector('#mapboxKeyStatus');if(!v)return;if(!v.startsWith('pk.')){status.textContent='Χρειάζεται public Mapbox token που αρχίζει από pk.';return}localStorage.setItem('lumina-mapbox-public-token',v);status.textContent=`Token αποθηκευμένο: ${mask(v)} · κύρια πηγή POI`;input.value=''});
 row.querySelector('#googlePlacesKeySave')?.addEventListener('click',()=>{const input=row.querySelector('#googlePlacesKeyInput'),v=String(input?.value||'').trim();if(!v)return;window.LuminaGooglePlaces?.saveKey?.(v);row.querySelector('#googleKeyStatus').textContent=`Key αποθηκευμένο: ${mask(v)}`;input.value=''});
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mount,{once:true});else mount();
})();
