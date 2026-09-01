import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..');
const read = (name) => fs.readFileSync(path.join(root, name), 'utf8');

const app = read('app-v2.js');
const completion = read('drive-completion.js');
const labels = read('map-labels.js');
const google = read('google-places.js');
const session = read('session-bootstrap.js');
const index = read('index.html');

// Real mobile GPS and live speed.
assert.match(app, /navigator\.geolocation\.watchPosition/);
assert.match(app, /coords\.speed/);
assert.match(app, /enableHighAccuracy\s*:\s*true/);

// Greek voice guidance and recognition.
assert.match(app, /SpeechSynthesisUtterance/);
assert.match(app, /\.lang\s*=\s*['"]el-GR['"]/);
assert.match(app, /SpeechRecognition|webkitSpeechRecognition/);
assert.match(app, /Σε \$\{Math\.round\(best\.d\/10\)\*10\} μέτρα/);

// Live next maneuver/distance and automatic rerouting.
assert.match(app, /maneuverDistance/);
assert.match(app, /checkRouteProgress/);
assert.match(app, /nearestRouteDistance/);
assert.match(app, /autoReroute/);
assert.match(app, /lastRerouteAt/);
assert.match(app, /buildRoute\(state\.destination,\{active:true,silent:true\}\)/);

// Navigation survives page visibility/return and persists session state.
assert.match(app, /visibilitychange/);
assert.match(app, /pageshow/);
assert.match(app, /saveSession/);
assert.match(app, /pendingRestore/);
assert.match(session, /lumina-drive-session-v1/);

// Road names are live map data, with Greek name preference when available.
assert.match(labels, /overpass-api/);
assert.match(labels, /name:el/);
assert.match(labels, /roadNames/);
assert.match(labels, /lumina-current-road/);

// Nationwide Greece destination search: null origin removes proximity bias.
assert.match(google, /region:'GR'/);
assert.match(google, /textSearch=async\(query,origin=currentPos\(\)\)/);
assert.match(google, /if\(origin\)request\.locationBias/);
assert.match(google, /source:'google'/);

// Mobile/PWA shell and navigation UI are required deployment assets.
assert.match(index, /viewport/i);
assert.match(index, /manifest\.webmanifest/);
assert.match(index, /app-v2\.js/);
assert.match(index, /drive-completion\.js/);
assert.match(completion, /maneuver-card/);
assert.match(completion, /Free Drive/);

console.log('PASS mobile GPS, Greek voice, maneuver, reroute, persistence, road labels, nationwide Google search');
console.log('REQUIRES REAL DRIVING TEST: GPS accuracy, turn timing, reroute timing, TTS audibility, microphone, background return, local map coverage');
