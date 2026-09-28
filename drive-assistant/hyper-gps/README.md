# LUMINA Hyper GPS prototype

Mobile browser prototype adapted from the supplied Google AI Studio text. The source text omitted its entire `index.html`; the page here was reconstructed to match the supplied modules. Available at `/driver-assistant/hyper-gps/` when the FastAPI backend serves this repository. The existing Drive Assistant remains at `/driver-assistant/`.

Requires HTTPS for phone GPS and microphone, and online access for Leaflet, map tiles, Nominatim, Overpass and OSRM. No map API key is required for this personal prototype. Public endpoints have availability and usage limits and should be replaced with contracted services before broad release. Browser speech recognition support varies; text destination search is the fallback. The browser cannot guarantee background navigation, screen wake or persistent voice instructions when locked.

The source's five camera locations were illustrative and were removed. Its hard-coded 90 km/h speed limit was disabled because it is not derived from the road. Do not rely on this prototype for safety alerts.

On Android Chrome: open the deployed HTTPS `/driver-assistant/hyper-gps/`, permit location, then use Chrome menu → Add to Home screen. This creates a shortcut; it does not install an Android APK. Verify a real route outdoors on the phone before treating the navigation as usable.
