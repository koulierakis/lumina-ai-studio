import { useEffect, useState } from 'react';
import { apiGet } from '../lib/api';

const PHASES=['START','EXECUTION','RETURN'];

export default function ExerciseFactory(){
  const [packs,setPacks]=useState([]);
  const [identity,setIdentity]=useState('');
  const [providers,setProviders]=useState([]);
  const [error,setError]=useState('');
  useEffect(()=>{(async()=>{
    try{
      const [p,pr]=await Promise.all([apiGet('/identity-packs'),apiGet('/providers')]);
      const packList=Array.isArray(p)?p:(p?.items||p?.packs||[]);
      setPacks(packList);
      if(packList.length) setIdentity(packList[0].id);
      setProviders(pr?.providers||pr?.statuses||[]);
    }catch(e){setError(e?.message||'Could not load Factory prerequisites.')}
  })()},[]);
  const poseConditioningReady=providers.some(p=>p?.available && (p?.capabilities?.pose_conditioning || p?.supports_pose_conditioning));
  return <div className="min-h-screen p-8 text-white" data-testid="exercise-factory">
    <div className="max-w-6xl mx-auto">
      <div className="text-xs uppercase tracking-[0.25em] text-white/45">Athletico · Lumina Motion Engine</div>
      <h1 className="font-display text-4xl mt-2">ATHLETICO EXERCISE FACTORY</h1>
      <div className="mt-8 grid gap-4 md:grid-cols-3">
        <div className="rounded-xl border border-white/10 bg-white/[0.03] p-5"><div className="text-white/50 text-xs uppercase">Exercise</div><div className="mt-2 text-xl">Bodyweight Squat</div></div>
        <div className="rounded-xl border border-white/10 bg-white/[0.03] p-5"><div className="text-white/50 text-xs uppercase">Movement Family</div><div className="mt-2 text-xl">SQUAT_PATTERN</div></div>
        <label className="rounded-xl border border-white/10 bg-white/[0.03] p-5"><span className="text-white/50 text-xs uppercase">Identity Pack</span>
          <select value={identity} onChange={e=>setIdentity(e.target.value)} className="mt-2 w-full bg-black/40 border border-white/10 rounded p-2">
            <option value="">Select existing Identity Pack</option>{packs.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
      </div>
      {error && <div className="mt-5 rounded border border-red-500/30 p-3 text-red-200">{error}</div>}
      <div className="mt-8 grid gap-5 md:grid-cols-3">
        {PHASES.map(phase=><section key={phase} className="rounded-xl border border-white/10 bg-white/[0.03] p-5" data-testid={'factory-phase-'+phase.toLowerCase()}>
          <div className="flex justify-between"><h2 className="text-xl">{phase}</h2><span className="text-xs text-white/45">PENDING</span></div>
          <div className="mt-4 aspect-square rounded-lg border border-dashed border-white/15 flex items-center justify-center text-center text-white/35 px-4">Canonical pose preview will be served by the Factory API.</div>
          <div className="mt-4 text-sm text-white/50">No generated image yet.</div>
          <div className="mt-3 flex gap-2"><button disabled className="px-3 py-2 rounded bg-white/5 text-white/30">RETRY PHASE</button><button disabled className="px-3 py-2 rounded bg-white/5 text-white/30">APPROVE</button></div>
        </section>)}
      </div>
      <button disabled={!identity || !poseConditioningReady} title={!poseConditioningReady?'No configured image provider currently advertises verified pose-conditioning support.':''} className="mt-8 px-5 py-3 rounded-lg bg-white/10 disabled:opacity-40">GENERATE TEST</button>
      {!poseConditioningReady && <p className="mt-3 text-sm text-amber-200/80">Real generation is intentionally blocked: no configured Lumina image provider currently advertises verified pose-conditioning capability. No output is being faked.</p>}
    </div>
  </div>
}
