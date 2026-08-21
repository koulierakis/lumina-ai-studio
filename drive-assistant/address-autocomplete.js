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

  const hide = () => {
    menu.classList.add('hidden');
    menu.innerHTML = '';
    results = [];
    active = -1;
  };

  const labelFor = item => {
    const a = item.address || {};
    const main = a.road || a.pedestrian || a.neighbourhood || a.suburb || a.city || a.town || a.village || item.name || item.display_name?.split(',')[0] || 'Προορισμός';
    const place = a.city || a.town || a.village || a.municipality || a.county || '';
    return { main, place };
  };

  const select = index => {
    const item = results[index];
    if (!item) return;
    input.value = item.display_name || labelFor(item).main;
    input.dataset.selectedLat = item.lat || '';
    input.dataset.selectedLng = item.lon || '';
    input.dataset.selectedName = item.display_name || '';
    input.dispatchEvent(new Event('change', { bubbles: true }));
    hide();
    input.focus();
  };

  const render = items => {
    results = items.slice(0, 6);
    active = -1;
    if (!results.length) return hide();
    menu.innerHTML = results.map((item, i) => {
      const { main, place } = labelFor(item);
      const detail = item.display_name || '';
      return `<button type="button" class="destination-suggestion" role="option" data-index="${i}" aria-selected="false"><span class="suggestion-pin">⌖</span><span class="suggestion-copy"><strong>${escapeHtml(main)}</strong><small>${escapeHtml(place || detail)}</small></span></button>`;
    }).join('');
    menu.classList.remove('hidden');
  };

  const escapeHtml = s => String(s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  const query = async value => {
    const q = value.trim();
    if (q.length < 3 || !navigator.onLine) return hide();
    if (controller) controller.abort();
    controller = new AbortController();
    const params = new URLSearchParams({
      format: 'jsonv2',
      addressdetails: '1',
      countrycodes: 'gr',
      limit: '6',
      dedupe: '1',
      'accept-language': 'el',
      q
    });
    try {
      const r = await fetch(`https://nominatim.openstreetmap.org/search?${params}`, { signal: controller.signal, headers: { Accept: 'application/json' } });
      if (!r.ok) throw new Error('autocomplete');
      const data = await r.json();
      render(Array.isArray(data) ? data : []);
    } catch (e) {
      if (e.name !== 'AbortError') hide();
    }
  };

  input.addEventListener('input', () => {
    delete input.dataset.selectedLat;
    delete input.dataset.selectedLng;
    delete input.dataset.selectedName;
    clearTimeout(timer);
    const value = input.value;
    if (value.trim().length < 3) return hide();
    timer = setTimeout(() => query(value), 320);
  });

  input.addEventListener('keydown', e => {
    if (menu.classList.contains('hidden') || !results.length) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      active = e.key === 'ArrowDown' ? Math.min(results.length - 1, active + 1) : Math.max(0, active - 1);
      [...menu.querySelectorAll('.destination-suggestion')].forEach((b, i) => {
        const on = i === active;
        b.classList.toggle('active', on);
        b.setAttribute('aria-selected', String(on));
        if (on) b.scrollIntoView({ block: 'nearest' });
      });
    } else if (e.key === 'Enter' && active >= 0) {
      e.preventDefault();
      e.stopPropagation();
      select(active);
    } else if (e.key === 'Escape') {
      hide();
    }
  });

  menu.addEventListener('pointerdown', e => {
    const btn = e.target.closest('.destination-suggestion');
    if (!btn) return;
    e.preventDefault();
    select(Number(btn.dataset.index));
  });

  document.addEventListener('pointerdown', e => {
    if (!wrap.contains(e.target)) hide();
  });
})();