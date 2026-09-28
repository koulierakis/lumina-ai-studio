/**
 * navigation.js - OSRM Routing & Navigation Guidance Engine
 */

export class NavigationEngine {
    constructor() {
        this.currentRoute = null;
        this.steps = [];
        this.currentStepIndex = 0;
        this.destination = null;
    }

    // Υπολογισμός διαδρομής μέσω δωρεάν OSRM API
    async calculateRoute(startLat, startLon, destLat, destLon) {
        const url = `https://router.project-osrm.org/route/v1/driving/${startLon},${startLat};${destLon},${destLat}?overview=full&geometries=geojson&steps=true`;

        try {
            const res = await fetch(url);
            const data = await res.json();

            if (data.code !== 'Ok' || !data.routes || data.routes.length === 0) {
                throw new Error('Δεν βρέθηκε διαδρομή');
            }

            this.currentRoute = data.routes[0];
            this.steps = this.currentRoute.legs[0].steps;
            this.currentStepIndex = 0;
            this.destination = { lat: destLat, lon: destLon };

            // Μετατροπή των GeoJSON coordinates σε [lat, lon] για το Leaflet
            const latLngs = this.currentRoute.geometry.coordinates.map(coord => [coord[1], coord[0]]);

            return {
                latLngs,
                distanceKm: (this.currentRoute.distance / 1000).toFixed(1),
                durationMin: Math.round(this.currentRoute.duration / 60),
                steps: this.steps
            };
        } catch (error) {
            console.error('Route calculation failed:', error);
            return null;
        }
    }

    // Advance past a maneuver only after crossing it, allowing guidance at its location.
    updateProgress(currentLat, currentLon) {
        if (!this.steps.length) return null;
        while (this.currentStepIndex < this.steps.length - 1 &&
               ['depart', 'notification', 'new name', 'continue'].includes(this.steps[this.currentStepIndex].maneuver.type)) {
            this.currentStepIndex++;
        }
        const step = this.steps[this.currentStepIndex];
        const [lon, lat] = step.maneuver.location;
        const distance = this.getDistance(currentLat, currentLon, lat, lon);
        // GPS can drift: after the first close approach, move to the following maneuver.
        if (distance < 24 && this.currentStepIndex < this.steps.length - 1) {
            this.currentStepIndex++;
            return this.updateProgress(currentLat, currentLon);
        }
        return {
            stepIndex: this.currentStepIndex,
            distanceToNextTurn: Math.round(distance),
            instruction: this.translateInstruction(step),
            shouldSpeak: !['depart', 'notification', 'new name', 'continue'].includes(step.maneuver.type),
            type: step.maneuver.type,
            modifier: step.maneuver.modifier
        };
    }

    translateInstruction(step) {
        const maneuver = step.maneuver;
        const type = maneuver.type;
        const modifier = maneuver.modifier || '';
        const name = step.name ? ` στην οδό ${step.name}` : '';
        if (type === 'arrive') return 'Φτάσατε στον προορισμό σας';
        if (type === 'roundabout' || type === 'rotary' || type === 'roundabout turn') {
            const exit = Number.isInteger(maneuver.exit) ? ` και πάρτε την ${maneuver.exit}η έξοδο` : '';
            return `Μπείτε στον κυκλικό κόμβο${exit}${name}`;
        }
        if (type === 'merge') return `Ενωθείτε με την κυκλοφορία${name}`;
        if (type === 'fork') return modifier.includes('left') ? `Κρατήστε αριστερά${name}` : `Κρατήστε δεξιά${name}`;
        if (type === 'on ramp' || type === 'off ramp') return `Πάρτε τη ράμπα${name}`;
        if (type === 'uturn' || modifier === 'uturn') return `Κάντε αναστροφή${name}`;
        if (modifier.includes('right')) return `Στρίψτε δεξιά${name}`;
        if (modifier.includes('left')) return `Στρίψτε αριστερά${name}`;
        return `Συνεχίστε${name}`;
    }

    getDistance(lat1, lon1, lat2, lon2) {
        const R = 6371e3;
        const dLat = (lat2 - lat1) * Math.PI / 180;
        const dLon = (lon2 - lon1) * Math.PI / 180;
        const a = Math.sin(dLat/2) * Math.sin(dLat/2) +
                  Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
                  Math.sin(dLon/2) * Math.sin(dLon/2);
        return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
    }
}
