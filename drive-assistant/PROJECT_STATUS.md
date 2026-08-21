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
- Latest GitHub Actions validation: PASS.
- JavaScript syntax: PASS for `app-v2.js` and `sw.js`.
- Automated smoke gates: PASS for GPS, Greek browser voice, routing, geocoding, OSM safety/POI data, weather, automatic rerouting, Wake Lock, manifest, service worker and mobile viewport integration.

## Current deployment blocker
The GitHub Pages deployment workflow is correctly configured, but this private repository does not currently have a GitHub Pages site enabled. GitHub Actions attempted to enable it automatically and GitHub rejected that operation with `Resource not accessible by integration`. One repository-owner action is required in GitHub Settings: enable Pages and select **GitHub Actions** as the source. After that, the existing workflow can deploy the browser build without code changes.

## Data-source constraints
- A phone browser cannot physically detect radio radar without dedicated hardware; enforcement warnings are map/database based.
- Public OSM/Nominatim/Overpass/OSRM services are suitable for prototype use but are rate-limited and should later be proxied or replaced for production reliability.
- Live traffic/community incidents require a real provider/API and are intentionally not fabricated.
- Road speed limits depend on OSM coverage and may be missing or stale.
- Browser background execution and voice recognition behavior vary by Android browser/vendor.
- Offline shell caching does not make online routing/map/data APIs available without connectivity.

## Remaining gates after Pages is enabled
1. GitHub Pages deployment PASS and HTTPS browser URL.
2. Real Android Chrome GPS permission/accuracy test.
3. Real Greek speech output/input test on device.
4. Real route/POI/safety-warning road test.
5. Optional production traffic/community incident provider selection.
6. Later LUMINA tool integration when desktop access is available.
