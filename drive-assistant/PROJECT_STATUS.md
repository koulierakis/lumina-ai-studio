# LUMINA Drive Assistant — Project Status

Source of truth: `feature/lumina-drive-assistant`

## Implemented
- Mobile-first browser UI; no APK/native installation required.
- Live browser GPS via Geolocation API.
- Live speed display and trip distance/time/average-speed tracking.
- OpenStreetMap map via Leaflet.
- Destination geocoding via Nominatim.
- Turn-by-turn route geometry and route steps via OSRM.
- Greek text-to-speech guidance via Web Speech API.
- Greek voice-command input when supported by the mobile browser.
- Nearby POI search for pharmacies, fuel, restaurants, gyms, parking, hospitals, EV charging, supermarkets, cafes, police and banks using OpenStreetMap/Overpass.
- Nearby mapped speed-camera lookup via OpenStreetMap/Overpass.
- Nearby mapped `maxspeed` lookup with overspeed warning.
- Mapped road-work, pedestrian-crossing, railway-crossing and traffic-calming awareness.
- Weather-driving alerts via Open-Meteo.
- Route-geometry sharp-turn heuristic.
- Free Drive mode.
- Day/night visual mode.
- Runtime System Monitor showing real browser capability state.
- Driver-safe, large-control responsive UI with portrait/landscape adaptation and safe-area support.
- Browser manifest and service-worker application shell for degraded/offline reopening of core UI assets.
- Online/offline presentation hook in the mobile shell.

## Validation
- GitHub Actions checks JavaScript syntax for application and service worker.
- Automated smoke gates assert GPS, Greek browser voice, routing, geocoding, OSM safety/POI data, weather, manifest, service worker and mobile viewport integration.
- Validation explicitly rejects fabricated live-traffic claims and physical radar-detector claims.

## Known limitations / data-source constraints
- A phone browser cannot physically detect police radar without dedicated hardware; enforcement warnings are map/database based.
- Public OSM/Nominatim/Overpass/OSRM services are rate-limited and should later be replaced or proxied for production reliability.
- Live community incident/traffic feeds require a provider/API and are not fabricated.
- Road speed limits depend on OSM coverage and may be missing or stale.
- Browser background execution and voice recognition behavior vary by Android browser/vendor.
- Offline shell caching does not make online routing/map/data APIs available without connectivity.

## Remaining verification gates
1. Confirm CI execution for latest branch commits.
2. Confirm hosted build reflects latest GitHub milestone.
3. Real Android Chrome GPS permission/accuracy test.
4. Real Greek speech output/input test on device.
5. Real route/POI/safety-warning road test.
6. Select production-grade traffic/community incident provider if live traffic is required.
7. Final integration contract for later LUMINA tool embedding.
