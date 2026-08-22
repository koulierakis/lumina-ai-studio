# LUMINA Drive Assistant — Project Status

Source of truth: `feature/lumina-drive-assistant`

## Current autonomous completion state

Implemented and code-validated surfaces include browser GPS/watch mode, live browser speed, Free Drive, Leaflet/OpenStreetMap map, Greek destination search/autocomplete, route preview, navigation start/stop, OSRM driving routes, Valhalla pedestrian routes, turn-by-turn maneuver rendering, Greek TTS, one-shot voice commands, optional browser hands-free recognition, rerouting, mapped OSM speed limits/cameras, POIs, Open-Meteo weather alerts, trip computer, day/night UI, Wake Lock, persisted navigation session, mobile visibility/pageshow recovery, PWA/service-worker shell, offline/degraded reopening, and System Monitor.

## Latest hardening pass

- Service-worker cache and HTML asset version are aligned on build `v26`.
- The service worker caches the application shell including `index.html`, `drive-completion.js`, and `road-safety.js`, while keeping app assets network-first/no-store with cached fallback.
- Navigation reload persistence is no longer erased on every page load. Legacy state is cleared once when upgrading to build 26; normal reloads preserve the active session.
- Free Drive on/off state is persisted coherently.
- Arrival now transitions out of active navigation after the arrival state is reached.
- Restored walking mode has a direct `LuminaWalkingRouter` path and cannot silently fall back to driving solely because the helper mode store was stale.
- Added verified road-safety awareness using live OpenStreetMap/Overpass data for mapped road works, railway level crossings, generic mapped hazards, and traffic-calming points. These are explicitly map/database observations, not radar detection or fabricated live incidents.
- System Monitor now actively probes routing (OSRM), geocoding (Nominatim), weather (Open-Meteo), and OSM/Overpass availability instead of hard-coding remote services as READY.
- The default/legacy repository branch can no longer deploy Drive Pages and overwrite the canonical Drive build. GitHub Pages deployment ownership is restricted to `feature/lumina-drive-assistant`.
- The Drive Pages workflow syntax-checks all major JavaScript modules and smoke-gates GPS, voice APIs, routing/data providers, rerouting, Wake Lock, session migration, walking router, verified safety layer, service-worker cache coherence, and required deployed assets before Pages deployment.

## Data-source boundaries

- No mock road-safety feed is used as real data.
- Browser GPS speed depends on phone/browser GPS availability and quality.
- Speed limits, fixed cameras, road works and hazards depend on OpenStreetMap/Overpass coverage and may be absent or stale.
- Public OSRM/Nominatim/Overpass/Valhalla/Open-Meteo endpoints are suitable for the current browser prototype but are public services with availability/rate-limit constraints.
- A browser cannot physically detect police radar without dedicated hardware or a legitimate provider feed.
- Live community traffic/police reports are not fabricated when no real provider is connected.
- Offline shell support keeps the core UI available; live routing, map tiles not already cached, POIs, safety updates and weather still require connectivity.
- Web Speech recognition, Wake Lock and background execution remain browser/Android capability dependent.

## Remaining real-device acceptance gates

Only a physical mobile road test can conclusively verify: GPS accuracy and live speed while moving, real maneuver timing, rerouting after an actual deviation, Greek TTS audibility, microphone permission and recognition quality, hands-free behavior in the target browser, Wake Lock/background-return behavior, actual local OSM speed-limit/camera/safety coverage, and Android Chrome stability during a real trip.
