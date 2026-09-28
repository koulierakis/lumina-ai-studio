/** Address suggestions use Photon, whose public demo supports search-as-you-type.
 * Keep this endpoint replaceable if usage grows beyond the demo allowance. */
export function createAddressAutocomplete(input, list, { onSelect, onStatus, getLocation }) {
    let timer;
    let controller;
    let results = [];
    let selected = null;
    let active = -1;
    const cache = new Map();

    const hide = () => {
        list.replaceChildren();
        list.classList.add('hidden');
        input.setAttribute('aria-expanded', 'false');
        active = -1;
    };
    const format = feature => {
        const p = feature.properties || {};
        const [lon, lat] = feature.geometry?.coordinates || [];
        const street = p.street || p.name || '';
        const number = p.housenumber || '';
        const city = p.city || p.town || p.village || p.county || '';
        return { lat: Number(lat), lon: Number(lon), street, number, city,
            label: [street, number, city, p.state].filter(Boolean).join(', ') };
    };
    const render = items => {
        results = items;
        list.replaceChildren();
        if (!items.length) {
            const message = document.createElement('div');
            message.className = 'suggestion-empty';
            message.textContent = 'Δεν βρέθηκαν προτάσεις. Γράψε πλήρη διεύθυνση και πάτησε Πορεία.';
            list.append(message);
        }
        items.forEach((place, index) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'address-suggestion';
            button.setAttribute('role', 'option');
            button.setAttribute('aria-selected', 'false');
            button.textContent = place.label;
            button.addEventListener('click', () => choose(index));
            list.append(button);
        });
        list.classList.remove('hidden');
        input.setAttribute('aria-expanded', 'true');
    };
    const choose = index => {
        const place = results[index];
        if (!place) return;
        if (!place.number && /\d/.test(input.dataset.originalQuery || '')) {
            hide();
            onStatus('Η πρόταση δείχνει μόνο την οδό. Κράτησα τη διεύθυνση που έγραψες για ακριβή αναζήτηση.');
            return;
        }
        selected = place;
        input.value = place.label;
        hide();
        onSelect(place);
    };
    const search = async query => {
        if (cache.has(query)) return render(cache.get(query));
        controller?.abort();
        const request = new AbortController();
        controller = request;
        const url = new URL('https://photon.komoot.io/api/');
        url.searchParams.set('q', query);
        url.searchParams.set('lang', 'el');
        url.searchParams.set('countrycode', 'GR');
        url.searchParams.set('limit', '8');
        const near = getLocation();
        if (near) {
            url.searchParams.set('lat', near.lat);
            url.searchParams.set('lon', near.lon);
        }
        try {
            const response = await fetch(url, { signal: request.signal, headers: { Accept: 'application/json' } });
            if (!response.ok) throw new Error(`Photon ${response.status}`);
            const data = await response.json();
            if (request.signal.aborted || input.value.trim() !== query) return;
            const places = (data.features || []).filter(f => f.properties?.countrycode?.toLowerCase() === 'gr')
                .map(format).filter(p => Number.isFinite(p.lat) && Number.isFinite(p.lon) && p.label);
            cache.set(query, places);
            render(places);
        } catch (error) {
            if (error.name !== 'AbortError' && input.value.trim() === query) {
                hide();
                onStatus('Οι προτάσεις δεν είναι διαθέσιμες. Γράψε πλήρη διεύθυνση και πάτησε Πορεία.');
            }
        }
    };
    input.addEventListener('input', () => {
        selected = null;
        onSelect(null);
        clearTimeout(timer);
        controller?.abort();
        const query = input.value.trim();
        input.dataset.originalQuery = query;
        if (query.length < 3) return hide();
        timer = setTimeout(() => search(query), 450);
    });
    input.addEventListener('keydown', event => {
        if (list.classList.contains('hidden')) return;
        if (event.key === 'Escape') return hide();
        if (!results.length) return;
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            active = event.key === 'ArrowDown' ? Math.min(active + 1, results.length - 1) : Math.max(active - 1, 0);
            [...list.querySelectorAll('button')].forEach((button, index) => {
                button.classList.toggle('active', index === active);
                button.setAttribute('aria-selected', String(index === active));
            });
        } else if (event.key === 'Enter' && active >= 0) {
            event.preventDefault();
            choose(active);
        }
    });
    document.addEventListener('pointerdown', event => {
        if (!input.contains(event.target) && !list.contains(event.target)) hide();
    });
    return { getSelected: () => selected, hide };
}
