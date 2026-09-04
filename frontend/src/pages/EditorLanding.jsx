import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiGet } from '../lib/api';
import AuthImage from '../components/AuthImage';
import { Wand2 } from 'lucide-react';

export default function EditorLanding() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const nav = useNavigate();

  useEffect(() => {
    let cancelled = false;

    async function loadGallery() {
      setLoading(true);
      setLoadError('');
      try {
        const data = await apiGet('/gallery');
        if (!cancelled) setItems(Array.isArray(data) ? data : []);
      } catch (err) {
        if (!cancelled) {
          setItems([]);
          setLoadError(err?.message || 'Gallery is temporarily unavailable.');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    loadGallery();
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="h-full w-full overflow-y-auto p-10">
      <div className="mb-8">
        <h2 className="font-display text-4xl text-white tracking-tight">AI Image Editor</h2>
        <p className="text-white/50 text-sm mt-1">Choose an image from your Gallery to open the professional editor.</p>
      </div>

      {loading && <p className="text-white/40 text-sm">Loading…</p>}
      {!loading && loadError && (
        <div className="lumina-glass rounded-lg p-6 mb-6 border border-amber-400/20">
          <p className="text-amber-200 text-sm">{loadError}</p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="mt-3 text-xs px-3 py-1.5 rounded bg-white/5 text-white/70 hover:bg-white/10 transition-colors"
          >
            Retry
          </button>
        </div>
      )}
      {!loading && !loadError && items.length === 0 && (
        <div className="lumina-glass rounded-lg p-10 text-center">
          <Wand2 strokeWidth={1} className="w-8 h-8 mx-auto text-gold/70 mb-3" />
          <h3 className="font-display text-2xl text-white mb-2">Nothing to edit yet</h3>
          <p className="text-white/40 text-sm">Generate an image first, then return here.</p>
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
        {items.map((it) => (
          <button
            key={it.id}
            onClick={() => nav(`/studio/editor/${it.media_id}`)}
            data-testid={`edit-${it.id}`}
            className="group relative aspect-square rounded-lg overflow-hidden border border-white/[0.06] bg-white/[0.02] hover:border-gold/40 transition-colors"
          >
            <AuthImage mediaId={it.media_id} className="w-full h-full object-cover" alt="" />
            <div className="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
              <div className="flex items-center gap-2 text-sm text-gold">
                <Wand2 strokeWidth={1.25} className="w-4 h-4" /> Open in Editor
              </div>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
