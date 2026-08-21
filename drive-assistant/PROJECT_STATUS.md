# LUMINA Drive Assistant — Project Status

Source of truth: `feature/lumina-drive-assistant`

## Implemented
- Browser-only mobile-first UI; no APK, Expo or native installation required.
- Live browser GPS with high-accuracy watch mode and GPS error handling.
- Live speed, trip distance, elapsed time and average-speed tracking.
- OpenStreetMap map via Leaflet.
- Destination geocoding in Greece via Nominatim.
- Route calculation and route steps via OSRM.
- Two-stage navigation flow: **Οδηγίες → route preview → Έναρξη**.
- Route preview shows destination, distance, estimated duration and full route geometry before navigation starts.
- Active turn-by-turn navigation with Greek maneuver phrasing.
- Automatic rerouting when the vehicle deviates materially from the active route.
- Destination arrival detection and explicit **Τέλος διαδρομής** control.
- Greek text-to-speech guidance via Web Speech API.
- One-shot Greek voice commands plus optional hands-free mode when supported by the mobile browser.
- Hands-free command protection with wake word **LUMINA** so ordinary in-car conversation is not intentionally treated as a command.
- Voice-test control before a trip.
- Nearby POI search for pharmacies, fuel, restaurants, gyms, parking, hospitals, EV charging, supermarkets, cafes, police and banks using OpenStreetMap/Overpass.
- Nearby mapped speed-camera lookup via OpenStreetMap/Overpass.
- Nearby mapped `maxspeed` lookup with overspeed warning.
- Mapped road-work, pedestrian-crossing, railway-crossing and traffic-calming awareness.
- Weather-driving alerts via Open-Meteo.
- Route-geometry sharp-turn heuristic.
- Free Drive mode.
- Screen Wake Lock while navigation or Free Drive is active, with re-request after returning to the page.
- Navigation session persistence in local storage so an active destination/trip can be reconstructed if the browser page is recreated after interruption.
- Visibility/pageshow recovery hooks for returning from a phone call or temporary Android background state: GPS is ensured, Wake Lock is re-requested and hands-free listening is restarted when allowed by the browser.
- Day/night visual mode.
- Persistent user alert settings.
- Runtime System Monitor showing real browser capability state.
- Driver-safe responsive UI with portrait/landscape adaptation and safe-area support.
- Mobile virtual-keyboard viewport handling via `interactive-widget=resizes-content`.
- Search-field mobile keyboard optimization via `inputmode=search` and `enterkeyhint=go`.
- PWA scope/id hardening and unrestricted orientation so portrait/landscape responsive layouts can both operate.
- Browser manifest and service-worker application shell for degraded/offline reopening of core UI assets.
- Service-worker shell cache upgraded to `lumina-drive-v5` for the road-test build.
- Online/offline state handling without fabricated live feeds.

## Validation
- Dedicated LUMINA Drive GitHub Actions validation includes JavaScript syntax checks for `app-v2.js` and `sw.js`.
- Automated smoke gates cover GPS, Greek browser voice, routing, geocoding, OSM safety/POI data, weather, automatic rerouting, Wake Lock, route preview/start, hands-free state, session persistence, call/background recovery hooks, manifest, service worker, mobile viewport integration and PWA orientation/scope.
- Browser deployment is performed from branch pushes through GitHub Pages Actions.

## Deployment
- Repository visibility permits GitHub Pages on the current GitHub plan.
- GitHub Pages source is **GitHub Actions**.
- The `github-pages` environment branch-protection blocker has been removed.
- LUMINA Drive Assistant workflow run **#64** completed successfully after the environment fix.
- The road-test build automatically triggers the same validate → deploy pipeline.

## Data-source constraints
- A phone browser cannot physically detect radio radar without dedicated hardware; enforcement warnings are map/database based.
- Public OSM/Nominatim/Overpass/OSRM services are suitable for prototype use but are rate-limited and should later be proxied or replaced for production reliability.
- Live traffic/community incidents require a real provider/API and are intentionally not fabricated.
- Road speed limits depend on OSM coverage and may be missing or stale.
- Android/browser background execution and Web Speech recognition can be suspended by the operating system; LUMINA can restore state when the page returns but cannot force itself to the foreground after a call.
- Floating-window / split-screen behavior is controlled by Android/browser capabilities, not by the web page itself.
- Offline shell caching does not make online routing/map/data APIs available without connectivity.

## Tomorrow's road-test gates
1. Confirm the latest GitHub Pages road-test deployment is green.
2. Verify real Android Chrome GPS permission and accuracy.
3. Test **Οδηγίες → preview → Έναρξη** with a real destination.
4. Test Greek speech instructions and timing of maneuver alerts.
5. Test Hands-free ON with wake word **LUMINA** and normal passenger conversation.
6. Test incoming phone call → return to browser → route/GPS/Wake Lock recovery.
7. Test screen staying awake during active navigation and Free Drive.
8. Review every visible control, map zoom, portrait/landscape appearance and driving ergonomics.
9. Record any route/POI/safety-data gaps observed on the road.
