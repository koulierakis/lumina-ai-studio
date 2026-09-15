(() => {
  const input=document.getElementById('destinationInput');
  if(!input)return;
  const wrap=input.closest('.search-row');
  if(!wrap)return;
  wrap.classList.add('search-row-autocomplete');

  const menu=document.createElement('div');
  menu.id='destinationSuggestions';
  menu.className='destination-suggestions hidden';
  menu.setAttribute('role','listbox');
  wrap.appendChild(menu);

  let timer=null,controller=null,results=[],active=-1;
  const cache=new Map();
  const esc=s=>String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const norm=s=>String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('el-GR').trim();
  const hide=()=>{menu.classList.add('hidden');menu.innerHTML='';results=[];active=-1;};

  function fromPhoton(feature){
    const p=feature.properties||{},c=feature.geometry?.coordinates||[];
    const road=p.street||((['residential','primary','secondary','tertiary','living_street','unclassified'].includes(p.osm_value))?p.name:'')||'';
    const city=p.city||p.town||p.village||p.district||p.county||p.state||'';
    const name=road||p.name||city||'';
    return{lat:+c[1],lng:+c[0],road,name,city,countrycode:String(p.countrycode||'').toLowerCase(),display:[name,city,p.state].filter(Boolean).join(', '),kind:road?'road':'place'};
  }

  function fromNominatim(x){
    const a=x.address||{};
    const road=a.road||a.pedestrian||a.footway||a.path||a.residential||((x.addresstype==='road'||x.type==='road')?x.name:'')||'';
    const city=a.city||a.town||a.village||a.municipality||a.county||a.state_district||a.state||'';
    const name=road||x.name||String(x.display_name||'').split(',')[0]||city;
    return{lat:+x.lat,lng:+x.lon,road,name,city,countrycode:String(a.country_code||'').toLowerCase(),display:x.display_name||[name,city].filter(Boolean).join(', '),kind:road?'road':'place'};
  }

  const searchable=x=>norm([x.road,x.name,x.city,x.display].filter(Boolean).join(' '));
  const matches=(x,q)=>searchable(x).includes(norm(q));
  const score=(x,q)=>{const nq=norm(q),r=norm(x.road||x.name),c=norm(x.city);if(x.kind==='road'&&r===nq)return 0;if(x.kind==='road'&&r.startsWith(nq))return 1;if(x.kind==='road'&&r.includes(nq))return 2;if(c.startsWith(nq))return 3;if(c.includes(nq))return 4;return 8;};

  function render(items,q,{partial=false}={}){
    const seen=new Set();
    results=items.filter(x=>x.countrycode==='gr'&&Number.isFinite(x.lat)&&Number.isFinite(x.lng)&&matches(x,q)).filter(x=>{const key=`${norm(x.road||x.name)}|${norm(x.city)}|${x.kind}`;if(seen.has(key))return false;seen.add(key);return true;}).sort((a,b)=>score(a,q)-score(b,q)||norm(a.road||a.name).localeCompare(norm(b.road||b.name),'el')||norm(a.city).localeCompare(norm(b.city),'el')).slice(0,40);
    active=-1;
    if(!results.length){menu.innerHTML=`<div class="destination-empty">${esc(partial?'Η υπηρεσία αναζήτησης δεν απάντησε. Δοκίμασε ξανά.':'Δεν βρέθηκαν σχετικές επιλογές. Συνέχισε να γράφεις ή πρόσθεσε πόλη.')}</div>`;menu.classList.remove('hidden');return;}
    menu.innerHTML=(partial?'<div class="destination-empty">Εμφανίζονται τα διαθέσιμα αποτελέσματα.</div>':'')+results.map((x,i)=>{const road=x.road||x.name,city=x.city||'Ελλάδα';return `<button type="button" class="destination-suggestion" role="option" data-index="${i}" aria-selected="false"><span class="suggestion-pin">⌖</span><span class="suggestion-copy"><small class="suggestion-road">${esc(road)}</small><strong class="suggestion-city">${esc(city)}</strong></span></button>`;}).join('');
    menu.classList.remove('hidden');
  }

  const select=i=>{const x=results[i];if(!x)return;input.value=[x.road||x.name,x.city].filter(Boolean).join(', ');input.dataset.selectedLat=String(x.lat);input.dataset.selectedLng=String(x.lng);input.dataset.selectedName=x.display||input.value;input.dispatchEvent(new Event('change',{bubbles:true}));hide();input.focus();};

  function routeSelectedDestination(){
    const lat=Number(input.dataset.selectedLat),lng=Number(input.dataset.selectedLng);
    if(!Number.isFinite(lat)||!Number.isFinite(lng))return false;
    const bridge=document.createElement('button');
    bridge.type='button';
    bridge.className='poi-route';
    bridge.dataset.lat=String(lat);
    bridge.dataset.lng=String(lng);
    bridge.dataset.name=input.dataset.selectedName||input.value||'Προορισμός';
    bridge.hidden=true;
    document.body.appendChild(bridge);
    bridge.click();
    bridge.remove();
    hide();
    return true;
  }

  async function photon(q,signal){
    const u=new URL('https://photon.komoot.io/api/');u.searchParams.set('q',q);u.searchParams.set('lang','el');u.searchParams.set('limit','30');
    const r=await fetch(u,{signal,headers:{Accept:'application/json'}});if(!r.ok)throw new Error('photon');
    const j=await r.json();return(j.features||[]).map(fromPhoton).filter(x=>x.countrycode==='gr'&&x.display);
  }

  async function nominatim(q,signal){
    const u=new URL('https://nominatim.openstreetmap.org/search');
    u.searchParams.set('q',q);u.searchParams.set('format','jsonv2');u.searchParams.set('addressdetails','1');u.searchParams.set('namedetails','1');u.searchParams.set('countrycodes','gr');u.searchParams.set('layer','address');u.searchParams.set('limit','40');u.searchParams.set('accept-language','el');
    const r=await fetch(u,{signal,headers:{Accept:'application/json'}});if(!r.ok)throw new Error(`nominatim-${r.status}`);
    const j=await r.json();return(j||[]).map(fromNominatim).filter(x=>x.countrycode==='gr'&&x.display);
  }

  async function query(value){
    const q=value.trim();if(q.length<3||!navigator.onLine)return hide();
    const key=norm(q);if(cache.has(key)){render(cache.get(key).items,q,{partial:cache.get(key).partial});return;}
    if(controller)controller.abort();controller=new AbortController();
    try{
      const calls=[photon(q,controller.signal)];
      if(q.length>=4)calls.push(nominatim(q,controller.signal));
      const settled=await Promise.allSettled(calls);if(controller.signal.aborted)return;
      const merged=[];let failures=0;
      for(const r of settled){if(r.status==='fulfilled')merged.push(...r.value);else failures++;}
      cache.set(key,{items:merged,partial:failures===settled.length});
      render(merged,q,{partial:failures===settled.length});
    }catch(e){if(e.name!=='AbortError')render([],q,{partial:true});}
  }

  input.addEventListener('input',()=>{delete input.dataset.selectedLat;delete input.dataset.selectedLng;delete input.dataset.selectedName;clearTimeout(timer);const v=input.value;if(v.trim().length<3)return hide();timer=setTimeout(()=>query(v),700);});
  input.addEventListener('keydown',e=>{if(menu.classList.contains('hidden')||!results.length)return;if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();active=e.key==='ArrowDown'?Math.min(results.length-1,active+1):Math.max(0,active-1);[...menu.querySelectorAll('.destination-suggestion')].forEach((b,i)=>{const on=i===active;b.classList.toggle('active',on);b.setAttribute('aria-selected',String(on));if(on)b.scrollIntoView({block:'nearest'});});}else if(e.key==='Enter'&&active>=0){e.preventDefault();e.stopPropagation();select(active);}else if(e.key==='Escape')hide();});
  input.addEventListener('keydown',e=>{if(e.key==='Enter'&&Number.isFinite(Number(input.dataset.selectedLat))&&Number.isFinite(Number(input.dataset.selectedLng))){e.preventDefault();e.stopImmediatePropagation();routeSelectedDestination();}},true);
  document.getElementById('routeBtn')?.addEventListener('click',e=>{if(Number.isFinite(Number(input.dataset.selectedLat))&&Number.isFinite(Number(input.dataset.selectedLng))){e.preventDefault();e.stopImmediatePropagation();routeSelectedDestination();}},true);
  menu.addEventListener('pointerdown',e=>{const b=e.target.closest('.destination-suggestion');if(!b)return;e.preventDefault();select(+b.dataset.index);});
  document.addEventListener('pointerdown',e=>{if(!wrap.contains(e.target))hide();});
})();