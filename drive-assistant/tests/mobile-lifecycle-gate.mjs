import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..');
const read = (name) => fs.readFileSync(path.join(root, name), 'utf8');

const app = read('app-v2.js');
const completion = read('drive-completion.js');
const sessionBootstrap = read('session-bootstrap.js');

// Active navigation must persist enough state to rebuild the route after a
// phone call, backgrounding, browser suspension or page return.
assert.match(app, /function saveSession\(\)/);
assert.match(app, /active:state\.routeActive/);
assert.match(app, /destination:state\.destination/);
assert.match(app, /travelMode:state\.travelMode/);
assert.match(app, /if\(s\.active&&s\.destination\?\.lat&&s\.destination\?\.lng\)/);
assert.match(app, /state\.pendingRestore=true/);

// Returning to the foreground must restart the GPS stream and reacquire the
// screen wake lock where the browser supports it.
assert.match(app, /visibilitychange/);
assert.match(app, /document\.visibilityState===['"]visible['"]/);
assert.match(app, /ensureGPS\(\)/);
assert.match(app, /requestWakeLock\(\)/);
assert.match(app, /pageshow/);

// Once a fresh GPS fix exists, a persisted route must be rebuilt from the
// current phone position instead of continuing from stale coordinates.
assert.match(app, /state\.pendingRestore&&state\.destination&&navigator\.onLine/);
assert.match(app, /buildRoute\(state\.destination,\{active:true,silent:true\}\)/);
assert.match(app, /Η διαδρομή επανήλθε/);

// Hands-free voice is intentionally disabled after a full app reload so the
// microphone cannot silently restart without a fresh user/browser session.
assert.match(sessionBootstrap, /s\.handsFree\s*=\s*false/);

// Reaching the destination must transition out of active navigation instead
// of leaving the cockpit in a false still-navigating state.
assert.match(completion, /function observeArrival\(\)/);
assert.match(completion, /maneuver\.textContent\.trim\(\)===['"]Άφιξη['"]/);
assert.match(completion, /safeClick\(\$\(['"]#stopRouteBtn['"]\)\)/);

console.log('PASS mobile lifecycle: persisted route, foreground recovery, fresh-GPS rebuild, safe voice restart, arrival stop');
console.log('REQUIRES REAL DRIVING TEST: Android phone call/background return and browser-specific lifecycle behavior');
