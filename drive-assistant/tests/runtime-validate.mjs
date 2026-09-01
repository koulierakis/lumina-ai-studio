import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));

function run(name) {
  const file = path.join(here, name);
  const result = spawnSync(process.execPath, [file], {
    encoding: 'utf8',
    stdio: 'pipe',
    timeout: 120000,
  });
  return {
    name,
    passed: result.status === 0,
    status: result.status,
    stdout: (result.stdout || '').slice(-12000),
    stderr: (result.stderr || '').slice(-6000),
  };
}

const featureGate = run('mobile-feature-gate.mjs');
const lifecycleGate = run('mobile-lifecycle-gate.mjs');
const productionSmoke = run('production-smoke.mjs');
const runtimeServicesSmoke = run('runtime-services-smoke.mjs');
const automatedGatePassed = featureGate.passed && lifecycleGate.passed && productionSmoke.passed && runtimeServicesSmoke.passed;

const report = {
  mobile_only: true,
  feature_gate_passed: featureGate.passed,
  lifecycle_gate_passed: lifecycleGate.passed,
  production_smoke_passed: productionSmoke.passed,
  runtime_services_smoke_passed: runtimeServicesSmoke.passed,
  automated_gate_passed: automatedGatePassed,
  requires_real_driving_test: true,
  real_driving_checks: [
    'GPS accuracy and live speed while moving',
    'live distance to next maneuver and instruction timing',
    'rerouting after a real route deviation',
    'Greek TTS audibility in the target phone/browser',
    'microphone permission, one-shot voice and hands-free recognition',
    'navigation recovery after phone call/background/return where Android browser allows',
    'Wake Lock behavior',
    'local road-name, POI, speed-limit, camera and road-safety coverage',
  ],
  ai_gps_ready: false,
  checks: [featureGate, lifecycleGate, productionSmoke, runtimeServicesSmoke],
};

console.log(JSON.stringify(report, null, 2));
console.log(`\nAI GPS AUTOMATED GATE: ${automatedGatePassed ? 'PASS' : 'FAIL'}`);
console.log('AI GPS READY: NO');
console.log('REQUIRES REAL DRIVING TEST before READY can become YES.');
process.exit(automatedGatePassed ? 0 : 1);
