(()=>{
  'use strict';
  document.addEventListener('click',event=>{
    const button=event.target.closest?.('[data-start-search]');
    if(!button)return;
    const panel=document.querySelector('#nameSearchResults');
    const place=panel?.__places?.[Number(button.dataset.startSearch)];
    if(!place?.__assessment?.safe)return;
    const lat=Number(place.lat),lng=Number(place.lon);
    if(!Number.isFinite(lat)||!Number.isFinite(lng))return;
    event.preventDefault();
    event.stopImmediatePropagation();
    const proxy=document.createElement('button');
    proxy.type='button';
    proxy.className='poi-route';
    proxy.dataset.lat=String(lat);
    proxy.dataset.lng=String(lng);
    proxy.dataset.name=place.display_name||place.name||'Προορισμός';
    proxy.hidden=true;
    document.body.appendChild(proxy);
    proxy.click();
    proxy.remove();
    panel.classList.add('hidden');
  },true);
})();
