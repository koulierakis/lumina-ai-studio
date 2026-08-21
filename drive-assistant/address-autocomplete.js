(() => {
  const input = document.getElementById('destinationInput');
  if (!input) return;
  const wrap = input.closest('.search-row');
  if (!wrap) return;
  wrap.classList.add('search-row-autocomplete');

  const menu = document.createElement('div');
  menu.id = 'destinationSuggestions';
  menu.className = 'destination-suggestions hidden';
  menu.setAttribute('role', 'listbox');
  wrap.appendChild(menu);

  let timer = null;
  let controller = null;
  let results = [];
  let active = -1;

  const escapeHtml = s => String(s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const norm = s => String(s || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('el-GR');
  const locality = a => a.city || a.town || a.village || a.municipality || a.county || a.state_district || a.state || '';
  const labelFor = item => {
    const a = item.address || {};
    const main = a.road || a.pedestrian || a.place || a.neighbourhood || a.suburb || a.city || a.town || a.village || item.name || item.display_name?.split(',')[0] || 'Προορισμός';
    const place = locality(a);
    return { main, place };
  };
  const hide = () => { menu.classList.add('hidden'); menu.innerHTML=''; results=[]; active=-1; };
  const select = index => {
    const item = results[index];
    if (!item) return;
    const {main, place}=labelFor(item);
    input.value = item.display_name || [main,place].filter(Boolean).join(', ');
    input.dataset.selectedLat = item.lat || '';
    input.dataset.selectedLng = item.lon || '';
    input.dataset.selectedName = item.display_name || input.value;
    input.dispatchEvent(new Event('change',{bubbles:true}));
    hide(); input.focus();
  };
  const render = items => {
    results = items.slice(0, 12); active=-1;
    if (!results.length) return hide();
    menu.innerHTML = results.map((item,i)=>{
      const {main,place}=labelFor(item);
      const type = item.type === 'city' || item.type === 'town' || item.type === 'village' ? 'Πόλη / περιοχή' : (item.address?.road ? 'Οδός' : 'Τοποθεσία');
      return `<button type="button" class="destination-suggestion" role="option" data-index="${i}" aria-selected="false"><span class="suggestion-pin">⌖</span><span class="suggestion-copy"><strong>${escapeHtml(main)}</strong><small>${escapeHtml([place,type].filter(Boolean).join(' · '))}</small></span></button>`;
    }).join('');
    menu.classList.remove('hidden');
  };

  async function fetchNominatim(q, signal) {
    const params = new URLSearchParams({format:'jsonv2',addressdetails:'1',countrycodes:'gr',limit:'20',dedupe:'0','accept-language':'el',q});
    const r = await fetch(`https://nominatim.openstreetmap.org/search?${params}`, {signal,headers:{Accept:'application/json'}});
    if (!r.ok) throw new Error('autocomplete');
    return r.json();
  }

  const query = async value => {
    const q=value.trim();
    if(q.length<3||!navigator.onLine)return hide();
    if(controller)controller.abort();
    controller=new AbortController();
    try{
      const data=await fetchNominatim(q,controller.signal);
      const seen=new Set();
      const unique=(Array.isArray(data)?data:[]).filter(item=>{
        const {main,place}=labelFor(item);
        const key=`${norm(main)}|${norm(place)}|${Number(item.lat).toFixed(4)}|${Number(item.lon).toFixed(4)}`;
        if(seen.has(key))return false; seen.add(key); return true;
      });
      unique.sort((a,b)=>{
        const A=labelFor(a),B=labelFor(b);
        const am=norm(A.main),bm=norm(B.main), nq=norm(q);
        const ap=am.startsWith(nq)?0:1,bp=bm.startsWith(nq)?0:1;
        return ap-bp || am.localeCompare(bm,'el') || norm(A.place).localeCompare(norm(B.place),'el');
      });
      render(unique);
    }catch(e){if(e.name!=='AbortError')hide();}
  };

  input.addEventListener('input',()=>{
    delete input.dataset.selectedLat; delete input.dataset.selectedLng; delete input.dataset.selectedName;
    clearTimeout(timer); const value=input.value;
    if(value.trim().length<3)return hide();
    timer=setTimeout(()=>query(value),420);
  });
  input.addEventListener('keydown',e=>{
    if(menu.classList.contains('hidden')||!results.length)return;
    if(e.key==='ArrowDown'||e.key==='ArrowUp'){
      e.preventDefault(); active=e.key==='ArrowDown'?Math.min(results.length-1,active+1):Math.max(0,active-1);
      [...menu.querySelectorAll('.destination-suggestion')].forEach((b,i)=>{const on=i===active;b.classList.toggle('active',on);b.setAttribute('aria-selected',String(on));if(on)b.scrollIntoView({block:'nearest'});});
    }else if(e.key==='Enter'&&active>=0){e.preventDefault();e.stopPropagation();select(active);}else if(e.key==='Escape'){hide();}
  });
  menu.addEventListener('pointerdown',e=>{const btn=e.target.closest('.destination-suggestion');if(!btn)return;e.preventDefault();select(Number(btn.dataset.index));});
  document.addEventListener('pointerdown',e=>{if(!wrap.contains(e.target))hide();});
})();