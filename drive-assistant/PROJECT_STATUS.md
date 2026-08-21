# LUMINA Drive Assistant — Project Status

Source of truth: `feature/lumina-drive-assistant`

## Implemented
- Browser-only mobile-first UI; no APK, Expo or native installation required.
- Live browser GPS with high-accuracy watch mode and GPS error handling.
- Live speed, trip distance, elapsed time and average-speed tracking.
- OpenStreetMap map via Leaflet.
- Destination geocoding via Nominatim.
- Turn-by-turn route geometry and route steps via OSRM.
- Automatic rerouting when the vehicle deviates materially from the active route.
- Destination arrival detection.
- Greek text-to-speech guidance via Web Speech API.
- Greek voice-command input when supported by the mobile browser.
- Nearby POI search for pharmacies, fuel, restaurants, gyms, parking, hospitals, EV charging, supermarkets, cafes, police and banks using OpenStreetMap/Overpass.
- Nearby mapped speed-camera lookup via OpenStreetMap/Overpass.
- Nearby mapped `maxspeed` lookup with overspeed warning.
- Mapped road-work, pedestrian-crossing, railway-crossing and traffic-calming awareness.
- Weather-driving alerts via Open-Meteo.
- Route-geometry sharp-turn heuristic.
- Free Drive mode.
- Screen Wake Lock support where the browser exposes it.
- Day/night visual mode.
- Persistent user alert settings.
- Runtime System Monitor showing real browser capability state.
- Driver-safe responsive UI with portrait/landscape adaptation and safe-area support.
- Browser manifest and service-worker application shell for degraded/offline reopening of core UI assets.
- Online/offline state handling without fabricated live feeds.

## Validation
- Dedicated LUMINA Drive GitHub Actions validation: PASS.
- JavaScript syntax: PASS for `app-v2.js` and `sw.js`.
- Automated smoke gates: PASS for GPS, Greek browser voice, routing, geocoding, OSM safety/POI data, weather, automatic rerouting, Wake Lock, manifest, service worker and mobile viewport integration.
- Pull-request deployment is intentionally skipped; browser deployment is performed only from branch pushes.

## Deployment
- Repository visibility was changed to permit GitHub Pages on the current GitHub plan.
- GitHub Pages source has been set to **GitHub Actions** by the repository owner.
- Deployment workflow has been corrected so PR validation cannot attempt a Pages deployment.
- A fresh branch-push deployment has been triggered; HTTPS URL verification remains the active deployment gate.

## Data-source constraints
- A phone browser cannot physically detect radio radar without dedicated hardware; enforcement warnings are map/database based.
- Public OSM/Nominatim/Overpass/OSRM services are suitable for prototype use but are rate-limited and should later be proxied or replaced for production reliability.
- Live traffic/community incidents require a real provider/API and are intentionally not fabricated.
- Road speed limits depend on OSM coverage and may be missing or stale.
- Browser background execution and voice recognition behavior vary by Android browser/vendor.
- Offline shell caching does not make online routing/map/data APIs available without connectivity.

## Remaining gates
1. Confirm branch-push GitHub Pages deployment PASS and HTTPS browser URL.
2. Real Android Chrome GPS permission/accuracy test.
3. Real Greek speech output/input test on device.
4. Real route/POI/safety-warning road test.
5. Optional production traffic/community incident provider selection.
6. Later LUMINA tool integration when desktop access is available.
