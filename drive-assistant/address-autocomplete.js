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
  let townIndex=null;
  let townIndexPromise=null;

  const OVERPASS_ENDPOINTS=[
    'https://overpass-api.de/api/interpreter',
    'https://overpass.kumi.systems/api/interpreter'
  ];

  const esc=s=>String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const norm=s=>String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('el-GR').trim();
  const hide=()=>{menu.classList.add('hidden');menu.innerHTML='';results=[];active=-1;};
  const rad=v=>v*Math.PI/180;
  const distance=(a,b)=>{const R=6371e3,p1=rad(a.lat),p2=rad(b.lat),dp=rad(b.lat-a.lat),dl=rad(b.lng-a.lng),x=Math.sin(dp/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;return 2*R*Math.atan2(Math.sqrt(x),Math.sqrt(1-x));};
  const regexEscape=s=>String(s).replace(/[.*+?^${}()|[\]\\]/g,'\\$&');

  function fromPhoton(feature){
    const p=feature.properties||{},c=feature.geometry?.coordinates||[];
    const road=p.street||((['residential','primary','secondary','tertiary'].includes(p.osm_value))?p.name:'')||'';
    const city=p.city||p.town||p.village||p.district||p.county||p.state||'';
    const name=road||p.name||city||'';
    return{lat:+c[1],lng:+c[0],road,name,city,countrycode:String(p.countrycode||'').toLowerCase(),display:[name,city,p.state].filter(Boolean).join(', '),kind:road?'road':'place'};
  }

  const searchable=x=>norm([x.road,x.name,x.city,x.display].filter(Boolean).join(' '));
  const matches=(x,q)=>searchable(x).includes(norm(q));
  const score=(x,q)=>{
    const nq=norm(q),r=norm(x.road||x.name),c=norm(x.city);
    if(x.kind==='road'&&r===nq)return 0;
    if(x.kind==='road'&&r.startsWith(nq))return 1;
    if(x.kind==='road'&&r.includes(nq))return 2;
    if(c.startsWith(nq))return 3;
    if(c.includes(nq))return 4;
    return 8;
  };

  function render(items,q,{nationwideFailed=false}={}){
    const seen=new Set();
    results=items.filter(x=>x.countrycode==='gr'&&Number.isFinite(x.lat)&&Number.isFinite(x.lng)&&matches(x,q)).filter(x=>{
      const key=`${norm(x.road||x.name)}|${norm(x.city)}|${x.kind}`;
      if(seen.has(key))return false;
      seen.add(key);
      return true;
    }).sort((a,b)=>score(a,q)-score(b,q)||norm(a.road||a.name).localeCompare(norm(b.road||b.name),'el')||norm(a.city).localeCompare(norm(b.city),'el')).slice(0,40);
    active=-1;
    if(!results.length){
      const text=nationwideFailed?'Η πανελλαδική αναζήτηση δρόμων δεν απάντησε. Δοκίμασε ξανά σε λίγα δευτερόλεπτα.':'Δεν βρέθηκαν σχετικές επιλογές. Συνέχισε να γράφεις ή πρόσθεσε πόλη.';
      menu.innerHTML=`<div class="destination-empty">${esc(text)}</div>`;
      menu.classList.remove('hidden');
      return;
    }
    const warning=nationwideFailed?'<div class="destination-empty">Μερικά αποτελέσματα μόνο — η πανελλαδική υπηρεσία δρόμων δεν απάντησε.</div>':'';
    menu.innerHTML=warning+results.map((x,i)=>{const road=x.road||x.name,city=x.city||'Ελλάδα';return `<button type="button" class="destination-suggestion" role="option" data-index="${i}" aria-selected="false"><span class="suggestion-pin">⌖</span><span class="suggestion-copy"><small class="suggestion-road">${esc(road)}</small><strong class="suggestion-city">${esc(city)}</strong></span></button>`;}).join('');
    menu.classList.remove('hidden');
  }

  const select=i=>{const x=results[i];if(!x)return;input.value=[x.road||x.name,x.city].filter(Boolean).join(', ');input.dataset.selectedLat=String(x.lat);input.dataset.selectedLng=String(x.lng);input.dataset.selectedName=x.display||input.value;input.dispatchEvent(new Event('change',{bubbles:true}));hide();input.focus();};

  async function photon(q,signal){
    const u=new URL('https://photon.komoot.io/api/');u.searchParams.set('q',q);u.searchParams.set('lang','el');u.searchParams.set('limit','30');
    const r=await fetch(u,{signal,headers:{Accept:'application/json'}});if(!r.ok)throw new Error('photon');
    const j=await r.json();return(j.features||[]).map(fromPhoton).filter(x=>x.countrycode==='gr'&&x.display);
  }

  async function fetchOverpass(query,signal){
    let lastError=null;
    for(const endpoint of OVERPASS_ENDPOINTS){
      try{
        const body=`data=${encodeURIComponent(query)}`;
        const r=await fetch(endpoint,{method:'POST',body,signal,headers:{'Content-Type':'application/x-www-form-urlencoded;charset=UTF-8','Accept':'application/json'}});
        if(!r.ok)throw new Error(`overpass-${r.status}`);
        return await r.json();
      }catch(e){
        if(e.name==='AbortError')throw e;
        lastError=e;
      }
    }
    throw lastError||new Error('overpass-unavailable');
  }

  async function loadTownIndex(signal){
    if(townIndex)return townIndex;
    if(townIndexPromise)return townIndexPromise;
    const q='[out:json][timeout:20];area["ISO3166-1"="GR"][boundary=administrative][admin_level=2]->.gr;node(area.gr)[place~"city|town"];out body qt;';
    townIndexPromise=fetchOverpass(q,signal).then(j=>{
      townIndex=(j.elements||[]).filter(x=>x.type==='node'&&/^(city|town)$/.test(x.tags?.place||'')&&x.tags?.name&&Number.isFinite(x.lat)&&Number.isFinite(x.lon)).map(x=>({name:x.tags.name,lat:+x.lat,lng:+x.lon}));
      return townIndex;
    }).finally(()=>{townIndexPromise=null;});
    return townIndexPromise;
  }

  async function overpassRoads(q,signal){
    if(q.trim().length<4)return[];
    const needle=regexEscape(q.trim());
    const roadQuery=`[out:json][timeout:20];area["ISO3166-1"="GR"][boundary=administrative][admin_level=2]->.gr;way(area.gr)[highway][name~"${needle}",i];out tags center 250 qt;`;
    const [roadJson,towns]=await Promise.all([fetchOverpass(roadQuery,signal),loadTownIndex(signal)]);
    const roads=[];
    for(const x of (roadJson.elements||[])){
      if(x.type!=='way'||!x.tags?.name||!x.center)continue;
      if(!norm(x.tags.name).includes(norm(q)))continue;
      const p={lat:+x.center.lat,lng:+x.center.lon};
      if(!Number.isFinite(p.lat)||!Number.isFinite(p.lng))continue;
      let nearest=null;
      for(const t of towns){const d=distance(p,t);if(!nearest||d<nearest.d)nearest={...t,d};}
      const taggedCity=x.tags['addr:city']||x.tags['is_in:city']||x.tags['is_in:town']||'';
      const city=taggedCity||nearest?.name||'Ελλάδα';
      roads.push({lat:p.lat,lng:p.lng,road:x.tags.name,name:x.tags.name,city,countrycode:'gr',display:`${x.tags.name}, ${city}`,kind:'road'});
    }
    return roads;
  }

  async function query(value){
    const q=value.trim();if(q.length<3||!navigator.onLine)return hide();
    const key=norm(q);
    if(cache.has(key)){render(cache.get(key).items,q,{nationwideFailed:cache.get(key).nationwideFailed});return;}
    if(controller)controller.abort();controller=new AbortController();
    try{
      if(q.length>=4){
        const [roadsResult,photonResult]=await Promise.allSettled([overpassRoads(q,controller.signal),photon(q,controller.signal)]);
        if(controller.signal.aborted)return;
        const nationwideFailed=roadsResult.status!=='fulfilled';
        const roadItems=roadsResult.status==='fulfilled'?roadsResult.value:[];
        const photonItems=photonResult.status==='fulfilled'?photonResult.value:[];
        const merged=[...roadItems,...photonItems];
        cache.set(key,{items:merged,nationwideFailed});
        render(merged,q,{nationwideFailed});
      }else{
        const items=await photon(q,controller.signal);if(controller.signal.aborted)return;
        cache.set(key,{items,nationwideFailed:false});render(items,q);
      }
    }catch(e){if(e.name!=='AbortError')render([],q,{nationwideFailed:q.length>=4});}
  }

  input.addEventListener('input',()=>{delete input.dataset.selectedLat;delete input.dataset.selectedLng;delete input.dataset.selectedName;clearTimeout(timer);const v=input.value;if(v.trim().length<3)return hide();timer=setTimeout(()=>query(v),650);});
  input.addEventListener('keydown',e=>{if(menu.classList.contains('hidden')||!results.length)return;if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();active=e.key==='ArrowDown'?Math.min(results.length-1,active+1):Math.max(0,active-1);[...menu.querySelectorAll('.destination-suggestion')].forEach((b,i)=>{const on=i===active;b.classList.toggle('active',on);b.setAttribute('aria-selected',String(on));if(on)b.scrollIntoView({block:'nearest'});});}else if(e.key==='Enter'&&active>=0){e.preventDefault();e.stopPropagation();select(active);}else if(e.key==='Escape')hide();});
  menu.addEventListener('pointerdown',e=>{const b=e.target.closest('.destination-suggestion');if(!b)return;e.preventDefault();select(+b.dataset.index);});
  document.addEventListener('pointerdown',e=>{if(!wrap.contains(e.target))hide();});
})();