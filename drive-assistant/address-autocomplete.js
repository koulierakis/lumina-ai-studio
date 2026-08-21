(() => {
  const input=document.getElementById('destinationInput');
  if(!input)return;
  const wrap=input.closest('.search-row');
  if(!wrap)return;
  wrap.classList.add('search-row-autocomplete');
  const menu=document.createElement('div');
  menu.id='destinationSuggestions';menu.className='destination-suggestions hidden';menu.setAttribute('role','listbox');wrap.appendChild(menu);

  let timer=null,controller=null,results=[],active=-1;
  const cache=new Map();
  const esc=s=>String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const norm=s=>String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('el-GR').trim();
  const locality=a=>a.city||a.town||a.village||a.municipality||a.county||a.state_district||a.state||'';
  const hide=()=>{menu.classList.add('hidden');menu.innerHTML='';results=[];active=-1;};
  const rad=v=>v*Math.PI/180;
  const distance=(a,b)=>{const R=6371e3,p1=rad(a.lat),p2=rad(b.lat),dp=rad(b.lat-a.lat),dl=rad(b.lng-a.lng),x=Math.sin(dp/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;return 2*R*Math.atan2(Math.sqrt(x),Math.sqrt(1-x));};

  function fromNominatim(item){
    const a=item.address||{},road=a.road||a.pedestrian||'',city=locality(a),name=road||a.city||a.town||a.village||item.name||item.display_name?.split(',')[0]||'';
    return{lat:+item.lat,lng:+item.lon,road,name,city,countrycode:String(a.country_code||'gr').toLowerCase(),display:item.display_name||[name,city].filter(Boolean).join(', '),kind:road?'road':'place'};
  }
  function fromPhoton(feature){
    const p=feature.properties||{},c=feature.geometry?.coordinates||[],road=p.street||((['residential','primary','secondary','tertiary'].includes(p.osm_value))?p.name:'')||'',city=p.city||p.town||p.village||p.district||p.county||p.state||'',name=road||p.name||city||'';
    return{lat:+c[1],lng:+c[0],road,name,city,countrycode:String(p.countrycode||'').toLowerCase(),display:[name,city,p.state].filter(Boolean).join(', '),kind:road?'road':'place'};
  }
  const searchable=x=>norm([x.road,x.name,x.city,x.display].filter(Boolean).join(' '));
  const matches=(x,q)=>searchable(x).includes(norm(q));
  const score=(x,q)=>{const nq=norm(q),r=norm(x.road||x.name),c=norm(x.city);if(x.kind==='road'&&r===nq)return 0;if(x.kind==='road'&&r.startsWith(nq))return 1;if(x.kind==='road'&&r.includes(nq))return 2;if(c.startsWith(nq))return 3;if(c.includes(nq))return 4;return 8;};

  function render(items,q){
    const seen=new Set();
    results=items.filter(x=>x.countrycode==='gr'&&Number.isFinite(x.lat)&&Number.isFinite(x.lng)&&matches(x,q)).filter(x=>{
      const key=`${norm(x.road||x.name)}|${norm(x.city)}|${x.kind}`;
      if(seen.has(key))return false;seen.add(key);return true;
    }).sort((a,b)=>score(a,q)-score(b,q)||norm(a.road||a.name).localeCompare(norm(b.road||b.name),'el')||norm(a.city).localeCompare(norm(b.city),'el')).slice(0,30);
    active=-1;
    if(!results.length){menu.innerHTML='<div class="destination-empty">Δεν βρέθηκαν σχετικές επιλογές. Συνέχισε να γράφεις ή πρόσθεσε πόλη.</div>';menu.classList.remove('hidden');return;}
    menu.innerHTML=results.map((x,i)=>{const road=x.road||x.name,city=x.city||'Ελλάδα';return`<button type="button" class="destination-suggestion" role="option" data-index="${i}" aria-selected="false"><span class="suggestion-pin">⌖</span><span class="suggestion-copy"><small class="suggestion-road">${esc(road)}</small><strong class="suggestion-city">${esc(city)}</strong></span></button>`;}).join('');
    menu.classList.remove('hidden');
  }
  const select=i=>{const x=results[i];if(!x)return;input.value=[x.road||x.name,x.city].filter(Boolean).join(', ');input.dataset.selectedLat=String(x.lat);input.dataset.selectedLng=String(x.lng);input.dataset.selectedName=x.display||input.value;input.dispatchEvent(new Event('change',{bubbles:true}));hide();input.focus();};

  async function photon(q,signal){
    const u=new URL('https://photon.komoot.io/api/');u.searchParams.set('q',q);u.searchParams.set('lang','el');u.searchParams.set('limit','30');
    const r=await fetch(u,{signal,headers:{Accept:'application/json'}});if(!r.ok)throw new Error('photon');
    const j=await r.json();return(j.features||[]).map(fromPhoton).filter(x=>x.countrycode==='gr'&&x.display);
  }
  async function nominatim(q,signal){
    const p=new URLSearchParams({format:'jsonv2',addressdetails:'1',countrycodes:'gr',limit:'30',dedupe:'0','accept-language':'el',q});
    const r=await fetch(`https://nominatim.openstreetmap.org/search?${p}`,{signal,headers:{Accept:'application/json'}});if(!r.ok)throw new Error('nominatim');
    const j=await r.json();return(Array.isArray(j)?j:[]).map(fromNominatim);
  }
  const regexEscape=s=>String(s).replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
  async function overpassRoads(q,signal){
    if(q.trim().length<4)return[];
    const needle=regexEscape(q.trim());
    const query=`[out:json][timeout:28];area[\"ISO3166-1\"=\"GR\"][boundary=administrative][admin_level=2]->.gr;(way(area.gr)[highway][name~\"${needle}\",i];);out tags center 180;node(area.gr)[place~\"city|town\"];out tags;`;
    const r=await fetch('https://overpass-api.de/api/interpreter',{method:'POST',body:query,signal,headers:{'Content-Type':'text/plain;charset=UTF-8'}});
    if(!r.ok)throw new Error('overpass');
    const j=await r.json();
    const towns=(j.elements||[]).filter(x=>x.type==='node'&&/^(city|town)$/.test(x.tags?.place||'')&&x.tags?.name&&Number.isFinite(x.lat)&&Number.isFinite(x.lon)).map(x=>({name:x.tags.name,lat:x.lat,lng:x.lon}));
    const roads=[];
    for(const x of (j.elements||[])){
      if(x.type!=='way'||!x.tags?.name||!x.center)continue;
      if(!norm(x.tags.name).includes(norm(q)))continue;
      const p={lat:+x.center.lat,lng:+x.center.lon};
      let nearest=null;
      for(const t of towns){const d=distance(p,t);if(!nearest||d<nearest.d)nearest={...t,d};}
      const city=nearest?.name||x.tags['addr:city']||x.tags['is_in:city']||'Ελλάδα';
      roads.push({lat:p.lat,lng:p.lng,road:x.tags.name,name:x.tags.name,city,countrycode:'gr',display:`${x.tags.name}, ${city}`,kind:'road'});
    }
    return roads;
  }

  async function query(value){
    const q=value.trim();if(q.length<3||!navigator.onLine)return hide();
    const key=norm(q);
    if(cache.has(key)){render(cache.get(key),q);return;}
    if(controller)controller.abort();controller=new AbortController();
    try{
      const jobs=[photon(q,controller.signal),nominatim(q,controller.signal)];
      if(q.length>=4)jobs.unshift(overpassRoads(q,controller.signal));
      const settled=await Promise.allSettled(jobs),merged=settled.flatMap(x=>x.status==='fulfilled'?x.value:[]);
      cache.set(key,merged);
      render(merged,q);
    }catch(e){if(e.name!=='AbortError')hide();}
  }
  input.addEventListener('input',()=>{delete input.dataset.selectedLat;delete input.dataset.selectedLng;delete input.dataset.selectedName;clearTimeout(timer);const v=input.value;if(v.trim().length<3)return hide();timer=setTimeout(()=>query(v),550);});
  input.addEventListener('keydown',e=>{if(menu.classList.contains('hidden')||!results.length)return;if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();active=e.key==='ArrowDown'?Math.min(results.length-1,active+1):Math.max(0,active-1);[...menu.querySelectorAll('.destination-suggestion')].forEach((b,i)=>{const on=i===active;b.classList.toggle('active',on);b.setAttribute('aria-selected',String(on));if(on)b.scrollIntoView({block:'nearest'});});}else if(e.key==='Enter'&&active>=0){e.preventDefault();e.stopPropagation();select(active);}else if(e.key==='Escape')hide();});
  menu.addEventListener('pointerdown',e=>{const b=e.target.closest('.destination-suggestion');if(!b)return;e.preventDefault();select(+b.dataset.index);});
  document.addEventListener('pointerdown',e=>{if(!wrap.contains(e.target))hide();});
})();