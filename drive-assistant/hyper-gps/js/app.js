/**
 * app.js - Main Application Orchestrator
 */

import { MapEngine } from './map.js';
import { VoiceAssistant } from './voice.js';
import { NavigationEngine } from './navigation.js';
import { PoiService } from './poi.js';
import { StorageService } from './storage.js';
import { createAddressAutocomplete } from './autocomplete.js';

class LuminaGpsApp {
    constructor() {
        this.currentLocation = { lat: 37.9838, lon: 23.7275, speed: 0, heading: 0 };
        this.speedLimit = null;
        this.isNavigating = false;
        this.isHudActive = false;
        this.pendingRoute = null;

        this.initModules();
        this.bindEvents();
        this.startGeolocationTracking();
    }

    initModules() {
        this.mapEngine = new MapEngine('map');
        this.hasPosition = false;
        this.lastSpokenStep = -1;
        this.spokenManeuvers = new Set();
        this.navEngine = new NavigationEngine();

        this.voice = new VoiceAssistant(
            (cmd) => this.handleVoiceCommand(cmd),
            (isListening, text) => this.updateVoiceStatus(isListening, text)
        );

        this.renderFavoritesModal();
        this.autocomplete = createAddressAutocomplete(
            document.getElementById('destination-input'),
            document.getElementById('destination-suggestions'),
            { onSelect: place => { this.selectedDestination = place; },
              onStatus: message => this.setStatus(message),
              getLocation: () => this.hasPosition ? this.currentLocation : null }
        );
    }

    bindEvents() {
        // Κουμπί Μικροφώνου
        document.getElementById('btn-voice-mic').onclick = () => {
            this.voice.toggleListening();
        };

        document.getElementById('btn-wake-mode').onclick = () => {
            const enabled = this.voice.toggleWakeMode();
            document.getElementById('btn-wake-mode').setAttribute('aria-pressed', String(enabled));
            document.getElementById('btn-wake-mode').textContent = enabled ? 'Τζούλι ON' : 'Τζούλι OFF';
        };

        const voiceChoice = document.getElementById('voice-choice');
        voiceChoice.value = this.voice.voicePreference;
        voiceChoice.onchange = () => this.voice.setVoicePreference(voiceChoice.value);
        const refreshVoices = () => {
            const voices = this.voice.availableGreekVoices();
            const male = voices.some(v => /nestoras|male|ανδρ/i.test(v.name));
            const female = voices.some(v => /athina|female|γυναικ/i.test(v.name));
            document.getElementById('voice-availability').textContent = male && female ? 'Δύο ελληνικές φωνές διαθέσιμες' : voices.length ? 'Οι φωνές εξαρτώνται από τη συσκευή' : 'Δεν βρέθηκε ελληνική φωνή στη συσκευή';
        };
        refreshVoices();
        if (this.voice.synthesis) this.voice.synthesis.addEventListener?.('voiceschanged', refreshVoices);

        document.getElementById('destination-form').onsubmit = async (event) => {
            event.preventDefault();
            const destination = document.getElementById('destination-input').value.trim();
            if (!this.hasPosition) return this.setStatus('Ενεργοποίησε την τοποθεσία πριν ζητήσεις διαδρομή.');
            if (!destination) return;
            this.autocomplete.hide();
            this.setStatus('Αναζήτηση προορισμού…');
            const location = this.selectedDestination || await PoiService.geocodeLocation(destination);
            if (!location) return this.setStatus('Δεν βρέθηκε ο προορισμός. Δοκίμασε πλήρη διεύθυνση.');
            await this.startNavigation(location.lat, location.lon, destination);
        };

        // HUD Mirror Mode Toggle
        document.getElementById('btn-hud-mode').onclick = () => {
            this.isHudActive = !this.isHudActive;
            document.getElementById('app-container').classList.toggle('hud-mode', this.isHudActive);
        };

        // Recenter Button
        document.getElementById('btn-recenter').onclick = () => {
            this.mapEngine.followUser = true;
            this.mapEngine.updateUserLocation(this.currentLocation.lat, this.currentLocation.lon);
        };

        // Day/Night Theme Toggle
        document.getElementById('btn-theme-toggle').onclick = () => {
            const isNight = !this.mapEngine.isNight;
            this.mapEngine.setMapTheme(isNight);
            document.body.className = isNight ? 'theme-night' : 'theme-day';
        };

        // Cancel Navigation
        document.getElementById('btn-cancel-nav').onclick = () => this.cancelNavigation();

        // Favorites Modal Toggle
        document.getElementById('btn-favorites').onclick = () => {
            document.getElementById('favorites-modal').classList.remove('hidden');
        };
        document.getElementById('btn-close-favs').onclick = () => {
            document.getElementById('favorites-modal').classList.add('hidden');
        };

        // Save Current Location to Favorites
        document.getElementById('btn-save-current-loc').onclick = () => {
            const name = document.getElementById('fav-name-input').value.trim();
            if (name) {
                StorageService.saveFavorite('custom', {
                    id: 'fav_' + Date.now(),
                    name,
                    lat: this.currentLocation.lat,
                    lon: this.currentLocation.lon
                });
                document.getElementById('fav-name-input').value = '';
                this.renderFavoritesModal();
            }
        };
    }

    // Geolocation Real-Time Tracking
    startGeolocationTracking() {
        if ('geolocation' in navigator) {
            navigator.geolocation.watchPosition(
                (pos) => this.handlePositionUpdate(pos),
                (err) => this.setStatus(`Δεν είναι διαθέσιμο το GPS (${err.message}). Χρειάζεται HTTPS και άδεια τοποθεσίας.`),
                { enableHighAccuracy: true, maximumAge: 1000 }
            );
        } else this.setStatus('Η συσκευή δεν υποστηρίζει τοποθεσία.');
    }

    setStatus(message) { document.getElementById('gps-status').textContent = message; }

    handlePositionUpdate(pos) {
        const { latitude, longitude, speed, heading } = pos.coords;
        this.hasPosition = true;
        this.setStatus('GPS ενεργό · Η διαδρομή χρειάζεται σύνδεση στο διαδίκτυο.');
        this.currentLocation.lat = latitude;
        this.currentLocation.lon = longitude;

        // Speed σε KM/H (το GPS επιστρέφει m/s)
        const speedKmh = speed ? Math.round(speed * 3.6) : 0;
        this.currentLocation.speed = speedKmh;

        // 1. Ενημέρωση Ταχυμέτρου
        const speedEl = document.getElementById('speed-display');
        speedEl.textContent = speedKmh < 10 ? `0${speedKmh}` : speedKmh;

        // 2. Έλεγχος Υπέρβασης Ορίου
        const speedBox = document.querySelector('.speed-box');
        if (this.speedLimit != null && speedKmh > this.speedLimit) {
            speedBox.classList.add('overspeed');
        } else {
            speedBox.classList.remove('overspeed');
        }

        // 3. Ενημέρωση Χάρτη
        this.mapEngine.updateUserLocation(latitude, longitude, heading);

        // 4. Έλεγχος για Ραντάρ / Κάμερες
        // No verified camera or road speed-limit data is bundled.

        // 5. Ενημέρωση Πλοήγησης (αν είναι ενεργή)
        if (this.isNavigating) {
            this.updateTurnByTurn(latitude, longitude);
        }
    }

    // Φωνητικές Εντολές Router
    async handleVoiceCommand(cmd) {
        if (cmd.type === 'CONFIRM_ROUTE' || cmd.type === 'DECLINE_ROUTE') {
            const pending = this.pendingRoute;
            this.pendingRoute = null;
            if (!pending || Date.now() > pending.expiresAt) {
                this.voice.speak('Δεν υπάρχει διαδρομή προς επιβεβαίωση.');
                return;
            }
            if (cmd.type === 'CONFIRM_ROUTE') await this.startNavigation(pending.lat, pending.lon, pending.name);
            else this.voice.speak('Εντάξει, δεν ξεκινώ διαδρομή.');
            return;
        }
        this.pendingRoute = null;
        if (cmd.type === 'SEARCH_PLACE') {
            this.setStatus('Αναζήτηση συγκεκριμένου σημείου…');
            const places = await PoiService.searchPlaces(cmd.destination);
            const loc = places[0];
            this.showPlaceResults(places);
            if (loc) {
                this.mapEngine.renderPOIs(places, poi => this.startNavigation(poi.lat, poi.lon, poi.name));
                this.pendingRoute = places.length === 1 ? { ...loc, name: loc.name || cmd.destination, expiresAt: Date.now() + 25000 } : null;
                this.setStatus(`Βρέθηκαν ${places.length} αποτελέσματα. Διάλεξε το σωστό σημείο από τη λίστα.`);
                this.voice.speak(places.length > 1 ? `Βρήκα ${places.length} αποτελέσματα. Διάλεξε το σωστό σημείο από τη λίστα.` : `Βρήκα ${loc.name}. Να ξεκινήσω τη διαδρομή;`, { followup: places.length === 1 });
            } else {
                this.setStatus('Δεν βρέθηκε το συγκεκριμένο σημείο. Πρόσθεσε πόλη ή πλήρη ονομασία.');
                this.voice.speak('Δεν βρήκα το συγκεκριμένο σημείο. Δώσε πληρέστερη ονομασία ή πόλη.');
            }
        } else if (cmd.type === 'NAVIGATE') {
            const loc = await PoiService.geocodeLocation(cmd.destination);
            if (loc) {
                this.startNavigation(loc.lat, loc.lon, cmd.destination);
            } else {
                this.setStatus('Δεν βρέθηκε ο προορισμός.');
            }
        } else if (cmd.type === 'POI') {
            if (!this.hasPosition) {
                this.setStatus('Χρειάζεται άδεια τοποθεσίας για κοντινά σημεία.');
                this.voice.speak('Ενεργοποίησε την τοποθεσία για να βρω το κοντινότερο σημείο.');
                return;
            }
            this.setStatus('Αναζήτηση κοντινών σημείων…');
            const pois = await PoiService.findNearby(this.currentLocation.lat, this.currentLocation.lon, cmd.category);
            if (pois.length) {
                const nearest = pois[0];
                const distance = Math.round(PoiService.distanceMeters(this.currentLocation.lat, this.currentLocation.lon, nearest.lat, nearest.lon));
                this.mapEngine.renderPOIs(pois, poi => this.startNavigation(poi.lat, poi.lon, poi.name));
                this.setStatus(`Κοντινότερο: ${nearest.name}, ${distance} μ. Πάτησε Πλοήγηση εδώ.`);
                this.pendingRoute = { ...nearest, expiresAt: Date.now() + 25000 };
                const distanceText = distance >= 1000 ? `${(distance / 1000).toLocaleString('el-GR', { maximumFractionDigits: 1 })} χιλιόμετρα` : `${distance} μέτρα`;
                this.voice.speak(`Το κοντινότερο είναι ${nearest.name}, σε ${distanceText}. Να ξεκινήσω τη διαδρομή;`, { followup: true });
            } else {
                this.setStatus('Δεν βρέθηκαν κοντινά σημεία ή δεν απάντησε η υπηρεσία.');
                this.voice.speak('Δεν βρήκα κοντινό σημείο αυτή τη στιγμή.');
            }
        } else if (cmd.type === 'CANCEL_NAV') {
            this.cancelNavigation();
        }
    }

    showPlaceResults(places) {
        const list = document.getElementById('place-results');
        list.replaceChildren();
        for (const place of places) {
            const button = document.createElement('button');
            button.type = 'button';
            button.textContent = place.name;
            button.onclick = () => {
                this.pendingRoute = null;
                list.replaceChildren();
                this.startNavigation(place.lat, place.lon, place.name);
            };
            list.append(button);
        }
        list.classList.toggle('hidden', places.length === 0);
    }

    async startNavigation(destLat, destLon, title = 'Προορισμός') {
        if (!this.hasPosition) return this.setStatus('Χρειάζεται πρώτα άδεια τοποθεσίας.');
        this.setStatus('Υπολογισμός διαδρομής…');
        const routeData = await this.navEngine.calculateRoute(
            this.currentLocation.lat,
            this.currentLocation.lon,
            destLat,
            destLon
        );

        if (routeData) {
            this.isNavigating = true;
            this.spokenManeuvers.clear();
            this.setStatus('Η διαδρομή είναι έτοιμη. Έλεγξε τις οδικές σημάνσεις.');
            this.mapEngine.drawNeonRoute(routeData.latLngs);

            // Εμφάνιση Nav Banner & Ενημέρωση ETA
            document.getElementById('nav-banner').classList.remove('nav-hidden');
            document.getElementById('route-distance').textContent = `${routeData.distanceKm} km`;

            const etaTime = new Date(Date.now() + routeData.durationMin * 60000);
            document.getElementById('route-eta').textContent = etaTime.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

            this.voice.speak(`Ξεκινάει η πλοήγηση προς ${title}. Απόσταση ${routeData.distanceKm} χιλιόμετρα.`);
        } else this.setStatus('Αδυναμία υπολογισμού διαδρομής. Δοκίμασε ξανά αργότερα.');
    }

    updateTurnByTurn(lat, lon) {
        const progress = this.navEngine.updateProgress(lat, lon);
        if (progress) {
            document.getElementById('turn-distance').textContent = `${progress.distanceToNextTurn} m`;
            document.getElementById('turn-instruction').textContent = progress.instruction;

            // One advance notice and one near-maneuver reminder; no repeated straight-ahead speech.
            if (progress.shouldSpeak) {
                const distance = progress.distanceToNextTurn;
                const band = distance <= 120 ? 'near' : distance <= 1100 && distance >= 350 ? 'advance' : null;
                const key = `${progress.stepIndex}:${band}`;
                if (band && !this.spokenManeuvers.has(key)) {
                    this.spokenManeuvers.add(key);
                    const prefix = progress.type === 'arrive' ? '' :
                        distance > 1000 ? 'Σε περίπου ένα χιλιόμετρο, ' : `Σε ${Math.max(10, Math.round(distance / 10) * 10)} μέτρα, `;
                    this.voice.speak(`${prefix}${progress.instruction}`);
                }
            }
        }
    }

    cancelNavigation() {
        this.isNavigating = false;
        this.pendingRoute = null;
        this.lastSpokenStep = -1;
        this.spokenManeuvers.clear();
        this.mapEngine.clearRoute();
        document.getElementById('nav-banner').classList.add('nav-hidden');
        document.getElementById('route-eta').textContent = '--:--';
        document.getElementById('route-distance').textContent = '-- km';
        this.voice.speak('Η πλοήγηση ακυρώθηκε');
    }

    updateVoiceStatus(isListening, text) {
        const btn = document.getElementById('btn-voice-mic');
        const status = document.getElementById('voice-status');
        status.textContent = text;
        btn.classList.toggle('listening', isListening);
        const wakeButton = document.getElementById('btn-wake-mode');
        const enabled = Boolean(this.voice?.wakeEnabled);
        wakeButton.setAttribute('aria-pressed', String(enabled));
        wakeButton.textContent = enabled ? 'Τζούλι ON' : 'Τζούλι OFF';
    }

    renderFavoritesModal() {
        const favs = StorageService.getFavorites();
        const list = document.getElementById('favorites-list');
        list.innerHTML = '';

        favs.custom.forEach(item => {
            const row = document.createElement('div');
            row.className = 'fav-item-row';
            const label = document.createElement('span');
            label.textContent = item.name;
            const button = document.createElement('button');
            button.className = 'btn-neon-action';
            button.textContent = 'Πλοήγηση';
            row.append(label, button);
            row.querySelector('button').onclick = () => {
                document.getElementById('favorites-modal').classList.add('hidden');
                this.startNavigation(item.lat, item.lon, item.name);
            };
            list.appendChild(row);
        });

        // Quick buttons Home / Work
        document.querySelectorAll('.btn-fav-card').forEach(btn => {
            const key = btn.dataset.key;
            btn.onclick = () => {
                if (favs[key]) {
                    document.getElementById('favorites-modal').classList.add('hidden');
                    this.startNavigation(favs[key].lat, favs[key].lon, favs[key].name);
                } else {
                    StorageService.saveFavorite(key, {
                        name: key === 'home' ? 'Σπίτι' : 'Δουλειά',
                        lat: this.currentLocation.lat,
                        lon: this.currentLocation.lon
                    });
                    alert(`Η τρέχουσα τοποθεσία αποθηκεύτηκε ως ${key === 'home' ? 'Σπίτι' : 'Δουλειά'}!`);
                }
            };
        });
    }
}

// Εκκίνηση της εφαρμογής
window.addEventListener('DOMContentLoaded', () => {
    new LuminaGpsApp();
});
