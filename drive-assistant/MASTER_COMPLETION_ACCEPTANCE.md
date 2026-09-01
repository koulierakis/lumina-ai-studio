# LUMINA Drive — Master Completion Acceptance

Branch: `work/lumina-master-completion`

## Automated gates

The master-completion branch must run the following before any automated acceptance claim:

- JavaScript syntax checks for the core mobile Drive files.
- `tests/mobile-feature-gate.mjs` for GPS, live speed, Greek voice, live maneuver distance, rerouting, persistence, road labels, nationwide Greece destination search and navigation POI visibility.
- `tests/mobile-lifecycle-gate.mjs` for route persistence, foreground recovery, fresh-GPS route rebuild, safe hands-free restart and arrival stop.
- `tests/production-smoke.mjs` for live destination-search and POI provider availability.
- `tests/runtime-services-smoke.mjs` for live routing and weather services.

## Navigation POI rule

Ambient map POIs are visible during normal browsing and Free Drive exploration, but the ambient POI layer is removed while `navigation-active` is set. The same layer is restored automatically when active navigation ends. Explicit destination/route markers are not part of this ambient layer.

## READY rule

Automated PASS is not enough for final READY.

`AI GPS READY: NO` remains mandatory until a physical Android driving test verifies GPS accuracy while moving, maneuver timing, real route deviation/rerouting, Greek voice audibility, microphone/voice recognition, phone-call/background return, Wake Lock behavior, and representative local road/POI/safety coverage.

Final mobile-only items that cannot be proven in CI are marked `REQUIRES REAL DRIVING TEST`.
