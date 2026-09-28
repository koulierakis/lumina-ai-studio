/**
 * poi.js - Smart Points of Interest (POI) Finder
 */

export const PoiService = {
    // Αναζήτηση κοντινών POIs με βάση τις συντεταγμένες
    async findNearby(lat, lon, category) {
        const radius = 10000; // 10 χλμ ακτίνα
        let tag = '';

        switch (category) {
            case 'fuel': tag = 'amenity=fuel'; break;
            case 'pharmacy': tag = 'amenity=pharmacy'; break;
            case 'hotel': tag = 'tourism=hotel'; break;
            case 'restaurant': tag = 'amenity=restaurant'; break;
            case 'cafe': tag = 'amenity=cafe'; break;
            case 'museum': tag = 'tourism=museum'; break;
            case 'sports': tag = 'leisure=sports_centre'; break;
            case 'gym': tag = 'leisure=fitness_centre'; break;
            case 'hospital': tag = 'amenity=hospital'; break;
            case 'clinic': tag = 'amenity=clinic'; break;
            case 'railway': tag = 'railway=station'; break;
            case 'airport': tag = 'aeroway=aerodrome'; break;
            case 'port': tag = 'harbour=yes'; break;
            default: tag = 'amenity=fuel';
        }

        const overpassQuery = `
            [out:json];
            (
              node[${tag}](around:${radius},${lat},${lon});
              way[${tag}](around:${radius},${lat},${lon});
            );
            out center;
        `;

        const url = `https://overpass-api.de/api/interpreter?data=${encodeURIComponent(overpassQuery)}`;

        try {
            const response = await fetch(url);
            if (!response.ok) throw new Error(`Overpass ${response.status}`);
            const data = await response.json();

            return (data.elements || []).map(el => ({
                id: el.id,
                name: (el.tags?.name) || this.getDefaultName(category),
                lat: el.lat ?? el.center?.lat,
                lon: el.lon ?? el.center?.lon,
                category: category
            })).filter(poi => Number.isFinite(poi.lat) && Number.isFinite(poi.lon))
                .sort((a, b) => this.distanceMeters(lat, lon, a.lat, a.lon) - this.distanceMeters(lat, lon, b.lat, b.lon));
        } catch (error) {
            console.error('POI Fetch error:', error);
            return [];
        }
    },

    distanceMeters(lat1, lon1, lat2, lon2) {
        const rad = Math.PI / 180;
        const dLat = (lat2 - lat1) * rad;
        const dLon = (lon2 - lon1) * rad;
        const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLon / 2) ** 2;
        return 6371000 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    },

    // Αναζήτηση τοποθεσίας με κείμενο (Geocoding)
    async geocodeLocation(query) {
        const url = `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(query)}&limit=1`;
        try {
            const res = await fetch(url, { headers: { 'Accept-Language': 'el, en' } });
            const data = await res.json();
            if (data && data.length > 0) {
                return {
                    name: data[0].display_name,
                    lat: parseFloat(data[0].lat),
                    lon: parseFloat(data[0].lon)
                };
            }
            return null;
        } catch (e) {
            console.error('Geocoding error:', e);
            return null;
        }
    },

    getDefaultName(category) {
        const names = {
            fuel: 'Πρατήριο Καυσίμων',
            pharmacy: 'Φαρμακείο',
            hotel: 'Ξενοδοχείο',
            restaurant: 'Εστιατόριο',
            cafe: 'Καφέ', museum: 'Μουσείο', sports: 'Αθλητική εγκατάσταση',
            gym: 'Γυμναστήριο', hospital: 'Νοσοκομείο', clinic: 'Κέντρο υγείας',
            railway: 'Σιδηροδρομικός σταθμός', airport: 'Αεροδρόμιο', port: 'Λιμάνι'
        };
        return names[category] || 'Σημείο Ενδιαφέροντος';
    }
};
