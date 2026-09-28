/**
 * map.js - Hypercar Map Engine (Leaflet integration)
 */

export class MapEngine {
    constructor(mapContainerId) {
        this.map = null;
        this.userMarker = null;
        this.routeLayer = null;
        this.poiLayerGroup = null;
        this.tileLayer = null;
        this.isNight = true;

        this.initMap(mapContainerId);
    }

    initMap(containerId) {
        // Αρχικοποίηση στο κέντρο της Αθήνας (προεπιλογή μέχρι να ληφθεί GPS)
        this.map = L.map(containerId, {
            zoomControl: false,
            attributionControl: true
        }).setView([37.9838, 23.7275], 16);

        this.poiLayerGroup = L.layerGroup().addTo(this.map);
        this.setMapTheme(true);

        // Custom High-Tech User Marker
        const userIcon = L.divIcon({
            className: 'custom-user-marker',
            html: `
                <div style="
                    width: 24px; height: 24px;
                    background: #00f3ff;
                    border: 3px solid #ffffff;
                    border-radius: 50%;
                    box-shadow: 0 0 20px #00f3ff, 0 0 40px #00f3ff;
                    position: relative;">
                    <div style="
                        position: absolute; top:-8px; left:6px;
                        width:0; height:0;
                        border-left: 6px solid transparent;
                        border-right: 6px solid transparent;
                        border-bottom: 10px solid #00f3ff;"></div>
                </div>
            `,
            iconSize: [24, 24],
            iconAnchor: [12, 12]
        });

        this.userMarker = L.marker([37.9838, 23.7275], { icon: userIcon }).addTo(this.map);
    }

    setMapTheme(isNight) {
        this.isNight = isNight;
        if (this.tileLayer) this.map.removeLayer(this.tileLayer);

        // Dark OLED Tiles (CartoDB DarkMatter) vs Day Tiles (CartoDB Positron)
        const tileUrl = isNight
            ? 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
            : 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png';

        this.tileLayer = L.tileLayer(tileUrl, { maxZoom: 19, attribution: '&copy; OpenStreetMap contributors &copy; CARTO' }).addTo(this.map);
    }

    updateUserLocation(lat, lon, heading) {
        if (this.userMarker) {
            this.userMarker.setLatLng([lat, lon]);
            this.map.panTo([lat, lon], { animate: true, duration: 1 });
        }
    }

    drawNeonRoute(coordinates) {
        if (this.routeLayer) this.map.removeLayer(this.routeLayer);

        // Φωτεινή Neon γραμμή διαδρομής
        this.routeLayer = L.polyline(coordinates, {
            color: '#00f3ff',
            weight: 6,
            opacity: 0.9,
            lineJoin: 'round',
            dashArray: null
        }).addTo(this.map);

        this.map.fitBounds(this.routeLayer.getBounds(), { padding: [50, 50] });
    }

    clearRoute() {
        if (this.routeLayer) {
            this.map.removeLayer(this.routeLayer);
            this.routeLayer = null;
        }
    }

    renderPOIs(pois, onSelectPOI) {
        this.poiLayerGroup.clearLayers();

        pois.forEach(poi => {
            const iconHtml = `
                <div style="
                    background: #ffb700; color: #000;
                    width: 32px; height: 32px;
                    border-radius: 50%;
                    display:flex; justify-content:center; align-items:center;
                    box-shadow: 0 0 15px #ffb700; font-weight:bold; font-size:14px;">
                    <i class="fa-solid fa-location-dot"></i>
                </div>
            `;
            const icon = L.divIcon({ html: iconHtml, className: 'poi-icon', iconSize: [32, 32] });
            const marker = L.marker([poi.lat, poi.lon], { icon }).addTo(this.poiLayerGroup);

            marker.bindPopup(`
                <div style="font-family: 'Rajdhani', sans-serif; color: #000;">
                    <b>Σημείο ενδιαφέροντος</b><br>
                    <button id="poi-nav-${poi.id}" style="
                        margin-top: 5px; background: #000; color: #00f3ff;
                        border: none; padding: 4px 8px; border-radius: 4px; font-weight: bold; cursor: pointer;">
                        Πλοήγηση εδώ
                    </button>
                </div>
            `);

            marker.on('popupopen', () => {
                document.getElementById(`poi-nav-${poi.id}`).onclick = () => {
                    onSelectPOI(poi);
                };
            });
        });
    }
}
