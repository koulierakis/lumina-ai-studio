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

    // Έλεγχος της τρέχουσας θέσης σε σχέση με το επόμενο βήμα στροφής
    updateProgress(currentLat, currentLon) {
        if (!this.steps || this.steps.length === 0 || this.currentStepIndex >= this.steps.length) {
            return null;
        }

        const currentStep = this.steps[this.currentStepIndex];
        const stepLocation = currentStep.maneuver.location; // [lon, lat]
        const distanceToStep = this.getDistance(currentLat, currentLon, stepLocation[1], stepLocation[0]);

        // Αν πλησιάσαμε τη στροφή στα 30 μέτρα, πάμε στο επόμενο βήμα
        if (distanceToStep < 30 && this.currentStepIndex < this.steps.length - 1) {
            this.currentStepIndex++;
        }

        const next = this.steps[this.currentStepIndex].maneuver.location;
        const nextDistance = this.getDistance(currentLat, currentLon, next[1], next[0]);
        return {
            distanceToNextTurn: Math.round(nextDistance),
            instruction: this.translateInstruction(this.steps[this.currentStepIndex]),
            type: this.steps[this.currentStepIndex].maneuver.type,
            modifier: this.steps[this.currentStepIndex].maneuver.modifier
        };
    }

    translateInstruction(step) {
        const maneuver = step.maneuver;
        const type = maneuver.type;
        const modifier = maneuver.modifier || '';
        const name = step.name ? `στην ${step.name}` : '';

        if (type === 'depart') return `Ξεκινήστε την πορεία σας ${name}`;
        if (type === 'arrive') return 'Φτάσατε στον προορισμό σας';
        if (type === 'turn') {
            if (modifier.includes('right')) return `Στρίψτε δεξιά ${name}`;
            if (modifier.includes('left')) return `Στρίψτε αριστερά ${name}`;
        }
        if (type === 'roundabout') return `Μπείτε στον κυκλικό κόμβο και πάρτε την έξοδο`;

        return `Συνεχίστε ευθεία ${name}`;
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
