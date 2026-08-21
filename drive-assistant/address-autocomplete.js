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
  const esc=s=>String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const norm=s=>String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('el-GR').trim();
  const locality=a=>a.city||a.town||a.village||a.municipality||a.county||a.state_district||a.state||'';
  const hide=()=>{menu.classList.add('hidden');menu.innerHTML='';results=[];active=-1;};

  function fromNominatim(item){
    const a=item.address||{};
    const road=a.road||a.pedestrian||'';
    const city=locality(a);
    const name=road||a.city||a.town||a.village||item.name||item.display_name?.split(',')[0]||'';
    return {lat:+item.lat,lng:+item.lon,road,name,city,display:item.display_name||[name,city].filter(Boolean).join(', '),kind:road?'road':'place'};
  }
  function fromPhoton(feature){
    const p=feature.properties||{},c=feature.geometry?.coordinates||[];
    const road=p.street||((p.osm_value==='residential'||p.osm_value==='primary'||p.osm_value==='secondary'||p.osm_value==='tertiary')?p.name:'')||'';
    const city=p.city||p.town||p.village||p.district||p.county||p.state||'';
    const name=road||p.name||city||'';
    return {lat:+c[1],lng:+c[0],road,name,city,display:[name,city,p.state].filter(Boolean).join(', '),kind:road?'road':'place'};
  }
  const searchable=x=>norm([x.road,x.name,x.city,x.display].filter(Boolean).join(' '));
  const matches=(x,q)=>searchable(x).includes(norm(q));
  const score=(x,q)=>{
    const nq=norm(q),r=norm(x.road||x.name),c=norm(x.city);
    if(r.startsWith(nq))return 0;
    if(r.includes(nq))return 1;
    if(c.startsWith(nq))return 2;
    if(c.includes(nq))return 3;
    return 9;
  };

  function render(items,q){
    const seen=new Set();
    results=items.filter(x=>Number.isFinite(x.lat)&&Number.isFinite(x.lng)&&matches(x,q)).filter(x=>{
      const key=`${norm(x.road||x.name)}|${norm(x.city)}|${x.lat.toFixed(4)}|${x.lng.toFixed(4)}`;
      if(seen.has(key))return false;seen.add(key);return true;
    }).sort((a,b)=>score(a,q)-score(b,q)||norm(a.road||a.name).localeCompare(norm(b.road||b.name),'el')||norm(a.city).localeCompare(norm(b.city),'el')).slice(0,14);
    active=-1;
    if(!results.length){menu.innerHTML='<div class="destination-empty">Δεν βρέθηκαν σχετικές επιλογές. Συνέχισε να γράφεις ή πρόσθεσε πόλη.</div>';menu.classList.remove('hidden');return;}
    menu.innerHTML=results.map((x,i)=>{
      const road=x.road||x.name;
      const city=x.city||'Ελλάδα';
      return `<button type="button" class="destination-suggestion" role="option" data-index="${i}" aria-selected="false"><span class="suggestion-pin">⌖</span><span class="suggestion-copy"><small class="suggestion-road">${esc(road)}</small><strong class="suggestion-city">${esc(city)}</strong></span></button>`;
    }).join('');
    menu.classList.remove('hidden');
  }

  const select=i=>{
    const x=results[i];if(!x)return;
    input.value=[x.road||x.name,x.city].filter(Boolean).join(', ');
    input.dataset.selectedLat=String(x.lat);
    input.dataset.selectedLng=String(x.lng);
    input.dataset.selectedName=x.display||input.value;
    input.dispatchEvent(new Event('change',{bubbles:true}));
    hide();input.focus();
  };

  async function photon(q,signal){
    const u=new URL('https://photon.komoot.io/api/');
    u.searchParams.set('q',q);u.searchParams.set('lang','el');u.searchParams.set('limit','30');
    const r=await fetch(u,{signal,headers:{Accept:'application/json'}});if(!r.ok)throw new Error('photon');
    const j=await r.json();return (j.features||[]).map(fromPhoton).filter(x=>x.display).filter(x=>/greece|ελλαδ|gr/i.test(JSON.stringify(j))||true);
  }
  async function nominatim(q,signal){
    const p=new URLSearchParams({format:'jsonv2',addressdetails:'1',countrycodes:'gr',limit:'30',dedupe:'0','accept-language':'el',q});
    const r=await fetch(`https://nominatim.openstreetmap.org/search?${p}`,{signal,headers:{Accept:'application/json'}});if(!r.ok)throw new Error('nominatim');
    const j=await r.json();return (Array.isArray(j)?j:[]).map(fromNominatim);
  }

  async function query(value){
    const q=value.trim();if(q.length<3||!navigator.onLine)return hide();
    if(controller)controller.abort();controller=new AbortController();
    try{
      const settled=await Promise.allSettled([photon(q,controller.signal),nominatim(q,controller.signal)]);
      const merged=settled.flatMap(x=>x.status==='fulfilled'?x.value:[]);
      render(merged,q);
    }catch(e){if(e.name!=='AbortError')hide();}
  }

  input.addEventListener('input',()=>{
    delete input.dataset.selectedLat;delete input.dataset.selectedLng;delete input.dataset.selectedName;
    clearTimeout(timer);const v=input.value;if(v.trim().length<3)return hide();timer=setTimeout(()=>query(v),350);
  });
  input.addEventListener('keydown',e=>{
    if(menu.classList.contains('hidden')||!results.length)return;
    if(e.key==='ArrowDown'||e.key==='ArrowUp'){
      e.preventDefault();active=e.key==='ArrowDown'?Math.min(results.length-1,active+1):Math.max(0,active-1);
      [...menu.querySelectorAll('.destination-suggestion')].forEach((b,i)=>{const on=i===active;b.classList.toggle('active',on);b.setAttribute('aria-selected',String(on));if(on)b.scrollIntoView({block:'nearest'});});
    }else if(e.key==='Enter'&&active>=0){e.preventDefault();e.stopPropagation();select(active);}else if(e.key==='Escape')hide();
  });
  menu.addEventListener('pointerdown',e=>{const b=e.target.closest('.destination-suggestion');if(!b)return;e.preventDefault();select(+b.dataset.index);});
  document.addEventListener('pointerdown',e=>{if(!wrap.contains(e.target))hide();});
})();