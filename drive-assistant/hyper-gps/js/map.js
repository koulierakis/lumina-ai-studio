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
        this.followUser = true;

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

        // The public CARTO endpoint now displays API KEY REQUIRED tiles.
        // Reuse the OpenStreetMap basemap already used by Drive Assistant.
        this.map.getPane('tilePane').style.filter = isNight
            ? 'brightness(0.55) invert(1) hue-rotate(180deg)'
            : '';
        this.tileLayer = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            attribution: '&copy; OpenStreetMap contributors'
        }).addTo(this.map);
    }

    updateUserLocation(lat, lon, heading) {
        if (this.userMarker) {
            this.userMarker.setLatLng([lat, lon]);
            if (this.followUser) this.map.panTo([lat, lon], { animate: true, duration: 1 });
        }
    }

    drawNeonRoute(coordinates) {
        this.followUser = true;
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
        this.followUser = false;
        this.poiLayerGroup.clearLayers();
        let nearestMarker = null;
        pois.slice(0, 12).forEach((poi, index) => {
            const icon = L.divIcon({
                html: '<span style="display:grid;place-items:center;background:#ffb700;color:#000;width:32px;height:32px;border-radius:50%;font-weight:bold">⌖</span>',
                className: 'poi-icon', iconSize: [32, 32]
            });
            const marker = L.marker([poi.lat, poi.lon], { icon }).addTo(this.poiLayerGroup);
            const popup = document.createElement('div');
            const title = document.createElement('strong');
            title.textContent = poi.name;
            const button = document.createElement('button');
            button.type = 'button';
            button.textContent = 'Πλοήγηση εδώ';
            button.style.cssText = 'display:block;margin-top:8px;padding:6px;background:#111;color:#00f3ff;border:0;border-radius:4px';
            button.addEventListener('click', () => onSelectPOI(poi));
            popup.append(title, button);
            marker.bindPopup(popup);
            if (index === 0) nearestMarker = marker;
        });
        if (nearestMarker) {
            this.map.setView(nearestMarker.getLatLng(), Math.max(this.map.getZoom(), 16));
            nearestMarker.openPopup();
        }
    }
}
