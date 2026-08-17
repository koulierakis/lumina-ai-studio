import { useEffect, useRef, useState } from 'react';
import { Gauge, LocateFixed, Navigation, ShieldAlert } from 'lucide-react';
import { apiPost } from '../lib/api';

export default function LuminaDrive() {
  const [position, setPosition] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [error, setError] = useState('');
  const [tracking, setTracking] = useState(false);
  const watchRef = useRef(null);

  const stop = () => {
    if (watchRef.current !== null && navigator.geolocation) navigator.geolocation.clearWatch(watchRef.current);
    watchRef.current = null;
    setTracking(false);
  };

  const evaluate = async (next) => {
    try {
      const result = await apiPost('/drive/evaluate', { position: next, hazards: [], warning_distance_m: 1000, speed_tolerance_kph: 3 });
      setAlerts(result || []);
    } catch (err) { setError(err?.message || 'Drive evaluation failed.'); }
  };

  const start = () => {
    if (!navigator.geolocation) { setError('Geolocation is not available in this browser.'); return; }
    setError(''); setTracking(true);
    watchRef.current = navigator.geolocation.watchPosition(
      (geo) => {
        const next = {
          latitude: geo.coords.latitude,
          longitude: geo.coords.longitude,
          speed_kph: Math.max(0, (geo.coords.speed || 0) * 3.6),
          heading_deg: Number.isFinite(geo.coords.heading) ? geo.coords.heading : null,
          accuracy_m: geo.coords.accuracy || null,
        };
        setPosition(next); evaluate(next);
      },
      (err) => { setError(err.message || 'Location permission failed.'); setTracking(false); },
      { enableHighAccuracy: true, maximumAge: 1000, timeout: 15000 },
    );
  };

  useEffect(() => () => stop(), []);

  return (
    <main className="min-h-screen w-full overflow-y-auto">
      <div className="mx-auto max-w-[1400px] p-6 sm:p-10">
        <header className="flex flex-col gap-5 border-b border-white/[0.07] pb-8 lg:flex-row lg:items-end lg:justify-between">
          <div><p className="text-[11px] uppercase tracking-[0.28em] text-gold">Driver safety assistant</p><h2 className="mt-2 font-display text-4xl tracking-tight text-white sm:text-5xl">LUMINA Drive</h2><p className="mt-2 max-w-3xl text-sm leading-relaxed text-white/50">Live location, speed-awareness and early warnings for speed limits, fixed cameras, curves, school zones, roadworks and road hazards.</p></div>
          <button onClick={tracking ? stop : start} className="inline-flex items-center gap-2 rounded-md bg-gold px-4 py-2.5 text-xs font-medium text-black"><LocateFixed className="h-4 w-4" />{tracking ? 'Stop tracking' : 'Start drive'}</button>
        </header>

        {error && <div className="mt-5 rounded-lg border border-red-400/20 bg-red-400/5 px-4 py-3 text-sm text-red-100">{error}</div>}

        <div className="mt-8 grid gap-6 lg:grid-cols-3">
          <section className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-6"><Gauge className="h-5 w-5 text-gold" /><div className="mt-4 text-[11px] uppercase tracking-[0.18em] text-white/35">Speed</div><div className="mt-1 font-display text-5xl text-white">{Math.round(position?.speed_kph || 0)}<span className="ml-2 text-base text-white/35">km/h</span></div></section>
          <section className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-6"><Navigation className="h-5 w-5 text-gold" /><div className="mt-4 text-[11px] uppercase tracking-[0.18em] text-white/35">Heading</div><div className="mt-1 font-display text-4xl text-white">{position?.heading_deg == null ? '—' : `${Math.round(position.heading_deg)}°`}</div><div className="mt-2 text-xs text-white/35">Accuracy {position?.accuracy_m ? `${Math.round(position.accuracy_m)} m` : '—'}</div></section>
          <section className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-6"><ShieldAlert className="h-5 w-5 text-gold" /><div className="mt-4 text-[11px] uppercase tracking-[0.18em] text-white/35">Active alerts</div><div className="mt-1 font-display text-4xl text-white">{alerts.length}</div><div className="mt-2 text-xs text-white/35">Warning horizon: 1 km</div></section>
        </div>

        <section className="mt-6 rounded-xl border border-white/[0.08] bg-white/[0.02] p-5"><h3 className="text-sm text-white">Safety warnings</h3><div className="mt-4 space-y-3">{alerts.map((alert) => <div key={alert.hazard_id} className="rounded-lg border border-gold/15 bg-gold/[0.03] px-4 py-3"><div className="flex justify-between gap-4"><span className="text-sm text-white/80">{alert.title}</span><span className="text-xs text-gold">{Math.round(alert.distance_m)} m</span></div><p className="mt-2 text-sm leading-relaxed text-white/55">{alert.message}</p></div>)}{!alerts.length && <p className="text-sm text-white/35">No active warnings. Live hazard and map data adapters will populate this panel.</p>}</div></section>

        <section className="mt-6 rounded-xl border border-white/[0.08] bg-black/15 p-5"><div className="text-[11px] uppercase tracking-[0.18em] text-white/30">Live position</div><code className="mt-3 block text-xs text-white/50">{position ? `${position.latitude.toFixed(6)}, ${position.longitude.toFixed(6)}` : 'Location not started'}</code></section>
      </div>
    </main>
  );
}
