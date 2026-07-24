import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiDelete, apiGet, apiPatch, fetchMediaBlobUrl } from '../lib/api';
import AuthImage from '../components/AuthImage';
import { toast } from 'sonner';
import { Heart, Download, Trash2, X, Wand2 } from 'lucide-react';

async function downloadMedia(mediaId, name) {
  const blob = await apiGet(`/media/${mediaId}`, { responseType: 'blob' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

export default function Gallery() {
  const [items, setItems] = useState([]);
  const [filter, setFilter] = useState('all'); // all | favorites
  const [viewer, setViewer] = useState(null);
  const [loading, setLoading] = useState(true);
  const nav = useNavigate();

  const load = useCallback(async () => {
    setLoading(true);
    const params = filter === 'favorites' ? { favorite: true } : {};
    const data = await apiGet('/gallery', { params });
    setItems(data);
    setLoading(false);
  }, [filter]);

  useEffect(() => { load(); }, [load]);

  const toggleFav = async (item) => {
    const data = await apiPatch(`/gallery/${item.id}`, { favorite: !item.favorite });
    setItems((xs) => xs.map((x) => (x.id === item.id ? data : x)));
  };

  const remove = async (item) => {
    if (!window.confirm('Delete this image permanently?')) return;
    await apiDelete(`/gallery/${item.id}`);
    setItems((xs) => xs.filter((x) => x.id !== item.id));
    setViewer(null);
    toast.success('Deleted');
  };

  return (
    <div className="h-full w-full overflow-y-auto p-10">
      <div className="flex items-baseline justify-between mb-8">
        <div>
          <h2 className="font-display text-4xl text-white tracking-tight">Gallery</h2>
          <p className="text-white/50 text-sm mt-1">Your private collection of generated images</p>
        </div>
        <div className="flex gap-1 lumina-glass rounded-md p-1">
          {['all', 'favorites'].map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              data-testid={`filter-${f}`}
              className={`text-xs uppercase tracking-widest px-3 py-1.5 rounded transition-colors ${
                filter === f ? 'bg-gold text-black' : 'text-white/60 hover:text-white'
              }`}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      {loading && <p className="text-white/40 text-sm">Loading…</p>}
      {!loading && items.length === 0 && (
        <div className="h-[60vh] rounded-lg lumina-glass flex items-center justify-center">
          <div className="text-center">
            <h3 className="font-display text-2xl text-white mb-2">Nothing here yet</h3>
            <p className="text-white/40 text-sm">Generate your first image to fill the gallery</p>
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
        {items.map((it) => (
          <div
            key={it.id}
            className="group relative rounded-lg overflow-hidden border border-white/[0.06] bg-white/[0.02] cursor-pointer"
            onClick={() => setViewer(it)}
            data-testid={`gallery-item-${it.id}`}
          >
            <AuthImage mediaId={it.media_id} className="w-full h-full aspect-square object-cover" alt="" />
            <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/0 to-transparent opacity-0 group-hover:opacity-100 transition-opacity">
              <div className="absolute bottom-3 left-3 right-3 flex items-end justify-between">
                <div className="text-xs text-white/80 line-clamp-2 flex-1 pr-2">{it.prompt}</div>
                <div className="flex gap-1">
                  <button
                    onClick={(e) => { e.stopPropagation(); nav(`/studio/editor/${it.media_id}`); }}
                    className="p-2 rounded text-white/70 hover:text-gold bg-black/40"
                    title="Edit"
                    data-testid={`edit-${it.id}`}
                  >
                    <Wand2 strokeWidth={1.5} className="w-4 h-4" />
                  </button>
                  <button
                    onClick={(e) => { e.stopPropagation(); toggleFav(it); }}
                    className={`p-2 rounded ${it.favorite ? 'text-gold' : 'text-white/70'} hover:text-gold bg-black/40`}
                    title="Favorite"
                    data-testid={`fav-${it.id}`}
                  >
                    <Heart strokeWidth={1.5} className="w-4 h-4" fill={it.favorite ? '#D4AF37' : 'none'} />
                  </button>
                  <button
                    onClick={(e) => { e.stopPropagation(); downloadMedia(it.media_id, `lumina-${it.id}.png`); }}
                    className="p-2 rounded text-white/70 hover:text-gold bg-black/40"
                    title="Download"
                    data-testid={`dl-${it.id}`}
                  >
                    <Download strokeWidth={1.5} className="w-4 h-4" />
                  </button>
                </div>
              </div>
            </div>
            {it.favorite && (
              <div className="absolute top-2 right-2">
                <Heart strokeWidth={1.5} className="w-4 h-4 text-gold" fill="#D4AF37" />
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Full-screen viewer */}
      {viewer && (
        <div
          className="fixed inset-0 z-50 bg-black/95 flex items-center justify-center p-8"
          onClick={() => setViewer(null)}
          data-testid="viewer-overlay"
        >
          <button
            onClick={() => setViewer(null)}
            className="absolute top-6 right-6 text-white/60 hover:text-white p-2"
          >
            <X strokeWidth={1.5} className="w-6 h-6" />
          </button>
          <div className="max-w-[90vw] max-h-[80vh] flex flex-col items-center" onClick={(e) => e.stopPropagation()}>
            <AuthImage mediaId={viewer.media_id} className="max-w-full max-h-[70vh] object-contain rounded" alt="" />
            <div className="mt-4 flex items-center gap-3">
              <button
                onClick={() => nav(`/studio/editor/${viewer.media_id}`)}
                className="flex items-center gap-1.5 text-xs px-3 py-2 rounded bg-white/5 hover:bg-white/10 text-white transition-colors"
                data-testid="viewer-edit-btn"
              >
                <Wand2 strokeWidth={1.5} className="w-4 h-4" /> Edit
              </button>
              <button
                onClick={() => toggleFav(viewer)}
                className="flex items-center gap-1.5 text-xs px-3 py-2 rounded bg-white/5 hover:bg-white/10 text-white transition-colors"
              >
                <Heart strokeWidth={1.5} className="w-4 h-4" fill={viewer.favorite ? '#D4AF37' : 'none'} />
                {viewer.favorite ? 'Favorited' : 'Favorite'}
              </button>
              <button
                onClick={() => downloadMedia(viewer.media_id, `lumina-${viewer.id}.png`)}
                className="flex items-center gap-1.5 text-xs px-3 py-2 rounded bg-gold text-black font-medium hover:bg-gold-soft transition-colors"
              >
                <Download strokeWidth={1.5} className="w-4 h-4" /> Download
              </button>
              <button
                onClick={() => remove(viewer)}
                className="flex items-center gap-1.5 text-xs px-3 py-2 rounded bg-white/5 hover:bg-red-500/70 text-white transition-colors"
              >
                <Trash2 strokeWidth={1.5} className="w-4 h-4" /> Delete
              </button>
            </div>
            <div className="mt-4 max-w-2xl text-center">
              <p className="text-white/70 text-sm">{viewer.prompt}</p>
              <p className="text-white/40 text-xs mt-1">
                {viewer.scene && <>Scene: {viewer.scene} · </>}
                {viewer.outfit && <>Outfit: {viewer.outfit} · </>}
                {viewer.aspect_ratio} · {viewer.provider}
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
