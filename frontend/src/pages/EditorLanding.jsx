import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiGet } from '../lib/api';
import AuthImage from '../components/AuthImage';
import { Wand2 } from 'lucide-react';

export default function EditorLanding() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const nav = useNavigate();

  useEffect(() => {
    apiGet('/gallery').then((data) => {
      setItems(data);
      setLoading(false);
    });
  }, []);

  return (
    <div className="h-full w-full overflow-y-auto p-10">
      <div className="mb-8">
        <h2 className="font-display text-4xl text-white tracking-tight">AI Image Editor</h2>
        <p className="text-white/50 text-sm mt-1">Choose an image from your Gallery to open the professional editor.</p>
      </div>

      {loading && <p className="text-white/40 text-sm">Loading…</p>}
      {!loading && items.length === 0 && (
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
