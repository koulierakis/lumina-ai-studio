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
- Nearby POI search for pharmacies, fuel, restaurants, gyms and parking using OpenStreetMap/Overpass.
- Nearby mapped speed-camera lookup via OpenStreetMap/Overpass.
- Nearby mapped `maxspeed` lookup with overspeed warning.
- Route-geometry sharp-turn heuristic.
- Free Drive mode.
- Day/night visual mode.
- Runtime System Monitor showing real browser capability state.
- Driver-safe, large-control responsive UI.

## Known limitations / data-source constraints
- A phone browser cannot physically detect police radar without dedicated hardware; enforcement warnings are map/database based.
- Public OSM/Nominatim/Overpass/OSRM services are rate-limited and should later be replaced or proxied for production reliability.
- Live community incident/traffic feeds require a provider/API and are not fabricated.
- Road speed limits depend on OSM coverage and may be missing or stale.
- Browser background execution and voice recognition behavior vary by Android browser/vendor.

## Validation gate
GitHub Actions workflow validates JavaScript syntax and presence of GPS, voice, routing, OSM POI/camera integrations before deployment.

## Publish gate
GitHub Pages deployment is configured from `drive-assistant/`. If repository Pages is permitted/enabled, successful Actions deployment provides the browser URL. If Pages is blocked by private-repository/account settings, use the same files unchanged on another static host.
