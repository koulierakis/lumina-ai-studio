# LUMINA Hyper GPS prototype

Mobile browser prototype adapted from the supplied Google AI Studio text. The source text omitted its entire `index.html`; the page here was reconstructed to match the supplied modules. Available at `/driver-assistant/hyper-gps/` when the FastAPI backend serves this repository. The existing Drive Assistant remains at `/driver-assistant/`.

Requires HTTPS for phone GPS and microphone, and online access for Leaflet, map tiles, Nominatim, Overpass and OSRM. No map API key is required for this personal prototype. Public endpoints have availability and usage limits and should be replaced with contracted services before broad release. Browser speech recognition support varies; text destination search is the fallback. The browser cannot guarantee background navigation, screen wake or persistent voice instructions when locked.

The source's five camera locations were illustrative and were removed. Its hard-coded 90 km/h speed limit was disabled because it is not derived from the road. Do not rely on this prototype for safety alerts.

On Android Chrome: open the deployed HTTPS `/driver-assistant/hyper-gps/`, permit location, then use Chrome menu → Add to Home screen. This creates a shortcut; it does not install an Android APK. Verify a real route outdoors on the phone before treating the navigation as usable.

Address suggestions use the public Photon demo with a 450 ms debounce and Greek results. Its availability is not guaranteed; one-shot Nominatim search remains the full-address fallback on submit. When a query contains a house number, a street-only suggestion is never treated as an exact house coordinate. The Photon service receives text typed into the search field.

The optional `Τζούλι ON` control keeps speech recognition active while this browser page is foregrounded. A command is acted on only after the wake word, or for eight seconds after saying the wake word alone. The microphone button accepts the next utterance directly. Speech recognition cannot identify the speaker and browser background or lock-screen listening is not guaranteed. Chrome may send audio to its speech-recognition service.

The assistant speaks the nearest POI's mapped name and straight-line distance, then asks before routing. A brief answer window accepts «ναι», «ξεκίνα» or «όχι» after the spoken question. The route distance is calculated separately by OSRM after confirmation. During speech output the microphone is paused to avoid hearing its own answer. Male and female voice choices select distinct Greek voices only when the device supplies them; otherwise the available Greek system voice is used. A browser cannot guarantee two Greek voices on every phone. The UI reports the available voice support. The foreground wake mode is keyword gating after transcription and does not provide an offline, system-wide wake-word engine.
