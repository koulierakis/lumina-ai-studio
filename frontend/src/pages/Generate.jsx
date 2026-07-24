import { useEffect, useState } from 'react';
import { apiGet, apiPost } from '../lib/api';
import AuthImage from '../components/AuthImage';
import { toast } from 'sonner';
import { Sparkles, Loader2, Download, ImageIcon } from 'lucide-react';

const SCENES = [
  'Chania Old Town', 'Venetian Harbor', 'Cretan village', 'Marina',
  'Airport', 'Ferry', 'Luxury Hotel', 'Restaurant', 'Café', 'Delicatessen',
  'Olive Grove', 'Winery', 'Beach', 'Modern Office', 'Luxury Residence',
];

const OUTFITS = [
  'White T-shirt', 'Navy Polo', 'White Linen Shirt', 'Light Blue Oxford Shirt',
  'Jeans', 'Chinos', 'Blazer', 'Jacket over Shoulder',
];

const RATIOS = ['1:1', '16:9', '9:16', '4:5', '3:2'];

async function download(mediaId, name) {
  const blob = await apiGet(`/media/${mediaId}`, { responseType: 'blob' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

function normalizeOutputMediaIds(payload) {
  const raw =
    payload?.output_media_ids ??
    payload?.output_media_id ??
    payload?.media_ids ??
    payload?.media?.map?.((item) => item?.id ?? item?.media_id);
  const values = Array.isArray(raw) ? raw : raw ? [raw] : [];
  return values
    .map((item) => {
      if (typeof item === 'string') return item;
      if (item && typeof item === 'object') return item.id || item.media_id || '';
      return '';
    })
    .filter(Boolean);
}

export default function Generate() {
  const [packs, setPacks] = useState([]);
  const [packId, setPackId] = useState(localStorage.getItem('lumina_active_pack') || '');
  const [prompt, setPrompt] = useState('Cinematic photograph of the person walking through the location, natural mid-morning light');
  const [negative, setNegative] = useState('cartoon, illustration, deformed, extra fingers, plastic skin');
  const [scene, setScene] = useState('Chania Old Town');
  const [outfit, setOutfit] = useState('White Linen Shirt');
  const [aspect, setAspect] = useState('4:5');
  const [count, setCount] = useState(2);
  const [job, setJob] = useState(null);
  const [outputMediaIds, setOutputMediaIds] = useState([]);
  const [running, setRunning] = useState(false);
  const [providers, setProviders] = useState([]);
  const [provider, setProvider] = useState('');

  useEffect(() => {
    apiGet('/providers').then((data) => {
      setProviders(data.providers || []);
      setProvider(data.active || '');
    }).catch(() => {});
    apiGet('/identity-packs').then((data) => {
      setPacks(data);
      if (!packId && data.length) setPackId(data[0].id);
    }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (packId) localStorage.setItem('lumina_active_pack', packId);
  }, [packId]);

  // Poll job status
  useEffect(() => {
    if (!job || job.status === 'completed' || job.status === 'failed') return;
    const t = setInterval(async () => {
      try {
        const data = await apiGet(`/jobs/${job.id}`);
        setJob(data);
        const ids = normalizeOutputMediaIds(data);
        if (data.status === 'completed') setOutputMediaIds(ids);
        if (data.status === 'completed') {
          setRunning(false);
          toast.success('Generation complete');
        }
        if (data.status === 'failed') {
          setRunning(false);
          toast.error(data.error || 'Generation failed');
        }
      } catch (err) {
        if (process.env.NODE_ENV !== 'production') {
          // eslint-disable-next-line no-console
          console.error('Job poll failed', err);
        }
      }
    }, 1500);
    return () => clearInterval(t);
  }, [job]);

  const run = async () => {
    if (!prompt.trim()) {
      toast.error('Prompt required');
      return;
    }
    if (!packId) {
      toast.error('Select an Identity Pack first');
      return;
    }
    setRunning(true);
    setOutputMediaIds([]);
    setJob({ id: 'pending', status: 'queued', output_media_ids: [] });
    try {
      const data = await apiPost('/generate', {
        identity_pack_id: packId,
        prompt,
        negative_prompt: negative,
        scene,
        outfit,
        aspect_ratio: aspect,
        count,
        provider: provider || undefined,
      });
      setJob(data);
      setOutputMediaIds(normalizeOutputMediaIds(data));
    } catch (err) {
      setRunning(false);
      setOutputMediaIds([]);
      setJob(null);
      toast.error(err?.message || 'Failed to start');
    }
  };

  const gridCols = outputMediaIds.length === 1 ? 'grid-cols-1' : 'grid-cols-2';
  const activePack = packs.find((p) => p.id === packId);
  const showResults = job?.status === 'completed' && outputMediaIds.length > 0;

  return (
    <div className="h-full w-full flex">
      {/* Center canvas */}
      <div className="flex-1 h-full overflow-y-auto p-10">
        <div className="flex items-baseline justify-between mb-8">
          <div>
            <h2 className="font-display text-4xl text-white tracking-tight">New Generation</h2>
            <p className="text-white/50 text-sm mt-1">
              Identity-preserving photography through{' '}
              <span className="text-gold">{provider || 'automatic provider selection'}</span>
            </p>
          </div>
          {activePack && (
            <div className="text-right">
              <div className="text-[11px] uppercase tracking-[0.2em] text-white/40">Active identity</div>
              <div className="text-white text-sm" data-testid="active-pack-label">{activePack.name}</div>
            </div>
          )}
        </div>

        {!job && (
          <div className="h-[60vh] rounded-lg lumina-glass flex items-center justify-center">
            <div className="text-center max-w-md px-8">
              <ImageIcon strokeWidth={1} className="w-12 h-12 mx-auto text-white/20 mb-4" />
              <h3 className="font-display text-2xl text-white mb-2">Your canvas awaits</h3>
              <p className="text-white/50 text-sm">
                Set your prompt on the right, then press <span className="text-gold">Generate</span> to place your
                identity into any scene.
              </p>
            </div>
          </div>
        )}

        {job && !showResults && (
          <div className="h-[60vh] rounded-lg lumina-glass flex flex-col items-center justify-center relative overflow-hidden">
            <div className="absolute inset-0 opacity-30" style={{
              background: 'radial-gradient(circle at 50% 50%, rgba(212,175,55,0.18) 0%, transparent 60%)',
            }} />
            <Loader2 strokeWidth={1.25} className="w-10 h-10 text-gold animate-spin mb-6" />
            <p className="font-display text-2xl text-white mb-1" data-testid="job-status">{
              job.status === 'processing' ? 'Rendering your scene…' :
              job.status === 'failed' ? 'Generation failed' :
              'Preparing generation…'
            }</p>
            <p className="text-white/40 text-sm">This usually takes 15–45 seconds per image</p>
          </div>
        )}

        {showResults && (
          <div className={`grid ${gridCols} gap-4`} data-testid="results-grid">
            {outputMediaIds.map((mid, i) => (
              <div key={mid} className="relative group rounded-lg overflow-hidden bg-white/[0.02] border border-white/[0.06]">
                <AuthImage mediaId={mid} className="w-full h-auto block" alt={`result-${i}`} />
                <div className="absolute inset-x-0 bottom-0 p-3 bg-gradient-to-t from-black/80 to-transparent opacity-0 group-hover:opacity-100 transition-opacity flex justify-end">
                  <button
                    onClick={() => download(mid, `lumina-${job.id}-${i + 1}.png`)}
                    data-testid={`download-${mid}`}
                    className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded bg-white/10 hover:bg-gold hover:text-black text-white transition-colors"
                  >
                    <Download strokeWidth={1.5} className="w-3.5 h-3.5" /> Download
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Right control panel */}
      <div className="w-96 shrink-0 border-l border-white/[0.06] h-full overflow-y-auto bg-ink-950">
        <div className="p-6 space-y-6">
          <div>
            <label className="block text-[11px] uppercase tracking-[0.2em] text-white/50 mb-2">AI Provider</label>
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              data-testid="provider-select"
              className="w-full bg-black/50 border border-white/10 rounded px-3 py-2.5 text-sm text-white focus:border-gold/50 focus:ring-1 focus:ring-gold/40 outline-none"
            >
              <option value="">Automatic fallback</option>
              {providers.map((item) => (
                <option key={item.name} value={item.name} disabled={!item.configured}>
                  {item.name}{item.configured ? (item.healthy ? ' — ready' : ' — unavailable') : ' — no credentials'}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-[11px] uppercase tracking-[0.2em] text-white/50 mb-2">Identity Pack</label>
            <select
              value={packId}
              onChange={(e) => setPackId(e.target.value)}
              data-testid="pack-select"
              className="w-full bg-black/50 border border-white/10 rounded px-3 py-2.5 text-sm text-white focus:border-gold/50 focus:ring-1 focus:ring-gold/40 outline-none"
            >
              <option value="">— select pack —</option>
              {packs.map((p) => (
                <option key={p.id} value={p.id}>{p.name} ({p.photo_ids.length} refs)</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-[11px] uppercase tracking-[0.2em] text-white/50 mb-2">Prompt</label>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              data-testid="prompt-input"
              rows={4}
              className="w-full bg-black/50 border border-white/10 rounded px-3 py-2.5 text-sm text-white placeholder:text-white/30 focus:border-gold/50 focus:ring-1 focus:ring-gold/40 outline-none resize-none"
              placeholder="Describe the photograph…"
            />
          </div>

          <div>
            <label className="block text-[11px] uppercase tracking-[0.2em] text-white/50 mb-2">Negative</label>
            <input
              value={negative}
              onChange={(e) => setNegative(e.target.value)}
              data-testid="negative-input"
              className="w-full bg-black/50 border border-white/10 rounded px-3 py-2 text-sm text-white placeholder:text-white/30 focus:border-gold/50 focus:ring-1 focus:ring-gold/40 outline-none"
              placeholder="things to avoid"
            />
          </div>

          <div>
            <label className="block text-[11px] uppercase tracking-[0.2em] text-white/50 mb-2">Scene</label>
            <div className="flex flex-wrap gap-1.5">
              {SCENES.map((s) => (
                <button
                  key={s}
                  onClick={() => setScene(s)}
                  data-testid={`scene-${s.replace(/\s+/g, '-').toLowerCase()}`}
                  className={`text-[11px] px-2.5 py-1.5 rounded border transition-colors ${
                    scene === s
                      ? 'bg-gold/15 border-gold/60 text-gold'
                      : 'bg-white/[0.02] border-white/10 text-white/60 hover:text-white hover:border-white/20'
                  }`}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="block text-[11px] uppercase tracking-[0.2em] text-white/50 mb-2">Outfit</label>
            <div className="flex flex-wrap gap-1.5">
              {OUTFITS.map((o) => (
                <button
                  key={o}
                  onClick={() => setOutfit(o)}
                  className={`text-[11px] px-2.5 py-1.5 rounded border transition-colors ${
                    outfit === o
                      ? 'bg-gold/15 border-gold/60 text-gold'
                      : 'bg-white/[0.02] border-white/10 text-white/60 hover:text-white hover:border-white/20'
                  }`}
                >
                  {o}
                </button>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-[11px] uppercase tracking-[0.2em] text-white/50 mb-2">Aspect</label>
              <div className="flex flex-wrap gap-1.5">
                {RATIOS.map((r) => (
                  <button
                    key={r}
                    onClick={() => setAspect(r)}
                    data-testid={`ratio-${r.replace(':', 'x')}`}
                    className={`text-xs px-2 py-1.5 rounded border transition-colors ${
                      aspect === r
                        ? 'bg-gold/15 border-gold/60 text-gold'
                        : 'bg-white/[0.02] border-white/10 text-white/60 hover:text-white'
                    }`}
                  >
                    {r}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <label className="block text-[11px] uppercase tracking-[0.2em] text-white/50 mb-2">Outputs</label>
              <div className="flex gap-1.5">
                {[1, 2, 3, 4].map((n) => (
                  <button
                    key={n}
                    onClick={() => setCount(n)}
                    data-testid={`count-${n}`}
                    className={`flex-1 text-sm py-1.5 rounded border transition-colors ${
                      count === n
                        ? 'bg-gold/15 border-gold/60 text-gold'
                        : 'bg-white/[0.02] border-white/10 text-white/60 hover:text-white'
                    }`}
                  >
                    {n}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <button
            onClick={run}
            disabled={running}
            data-testid="generate-btn"
            className="w-full flex items-center justify-center gap-2 bg-gold text-black font-medium py-3 rounded hover:bg-gold-soft disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {running ? <Loader2 strokeWidth={1.5} className="w-4 h-4 animate-spin" /> : <Sparkles strokeWidth={1.5} className="w-4 h-4" />}
            {running ? 'Generating…' : 'Generate'}
          </button>
        </div>
      </div>
    </div>
  );
}
