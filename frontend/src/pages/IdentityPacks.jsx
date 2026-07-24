import { useEffect, useRef, useState } from 'react';
import { apiDelete, apiGet, apiPatch, apiPost, uploadFormData } from '../lib/api';
import AuthImage from '../components/AuthImage';
import { toast } from 'sonner';
import { Plus, Trash2, Upload, Star, Check } from 'lucide-react';

export default function IdentityPacks() {
  const [packs, setPacks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const fileRef = useRef(null);

  const load = async () => {
    setLoading(true);
    try {
      const data = await apiGet('/identity-packs');
      setPacks(data);
      if (!selected && data.length) {
        setSelected(data[0]);
        localStorage.setItem('lumina_active_pack', data[0].id);
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const createPack = async (e) => {
    e.preventDefault();
    if (!newName.trim()) return;
    try {
      const data = await apiPost('/identity-packs', { name: newName.trim() });
      setNewName('');
      setCreating(false);
      toast.success('Identity Pack created');
      await load();
      setSelected(data);
      localStorage.setItem('lumina_active_pack', data.id);
    } catch (err) {
      toast.error(err?.response?.data?.detail || 'Failed to create');
    }
  };

  const uploadFiles = async (files) => {
    if (!selected) return;
    const fd = new FormData();
    Array.from(files).forEach((f) => fd.append('files', f));
    try {
      const data = await uploadFormData(`/identity-packs/${selected.id}/photos`, fd);
      setSelected(data);
      setPacks((p) => p.map((x) => (x.id === data.id ? data : x)));
      toast.success('Reference photos added');
    } catch (err) {
      toast.error(err?.response?.data?.detail || 'Upload failed');
    }
  };

  const removePhoto = async (photoId) => {
    if (!selected) return;
    const data = await apiDelete(`/identity-packs/${selected.id}/photos/${photoId}`);
    setSelected(data);
    setPacks((p) => p.map((x) => (x.id === data.id ? data : x)));
  };

  const setPrimary = async (photoId) => {
    if (!selected) return;
    const data = await apiPatch(`/identity-packs/${selected.id}`, { primary_photo_id: photoId });
    setSelected(data);
    setPacks((p) => p.map((x) => (x.id === data.id ? data : x)));
  };

  const removePack = async (id) => {
    if (!window.confirm('Permanently delete this Identity Pack and its photos?')) return;
    await apiDelete(`/identity-packs/${id}`);
    if (selected?.id === id) setSelected(null);
    toast.success('Pack deleted');
    await load();
  };

  const selectPack = (p) => {
    setSelected(p);
    localStorage.setItem('lumina_active_pack', p.id);
  };

  return (
    <div className="h-full w-full flex">
      {/* Left column: pack list */}
      <div className="w-72 shrink-0 border-r border-white/[0.06] bg-ink-950 h-full overflow-y-auto">
        <div className="px-6 py-6 flex items-center justify-between">
          <h2 className="font-display text-2xl text-white tracking-tight">Identity Packs</h2>
          <button
            data-testid="create-pack-open"
            onClick={() => setCreating(true)}
            className="text-white/70 hover:text-gold transition-colors p-1"
            title="New Pack"
          >
            <Plus strokeWidth={1.25} className="w-5 h-5" />
          </button>
        </div>

        {creating && (
          <form onSubmit={createPack} className="px-4 pb-4">
            <input
              autoFocus
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="Pack name"
              data-testid="new-pack-name"
              className="w-full bg-black/50 border border-white/10 rounded px-3 py-2 text-sm text-white placeholder:text-white/30 focus:border-gold/50 focus:ring-1 focus:ring-gold/40 outline-none"
            />
            <div className="flex gap-2 mt-2">
              <button type="submit" data-testid="create-pack-submit" className="text-xs px-3 py-1.5 rounded bg-gold text-black font-medium hover:bg-gold-soft transition-colors">
                Create
              </button>
              <button type="button" onClick={() => setCreating(false)} className="text-xs px-3 py-1.5 rounded bg-white/5 text-white/70 hover:bg-white/10 transition-colors">
                Cancel
              </button>
            </div>
          </form>
        )}

        <div className="px-2 pb-6 space-y-1">
          {loading && <div className="px-4 text-sm text-white/40">Loading…</div>}
          {!loading && packs.length === 0 && (
            <div className="px-4 py-8 text-center">
              <p className="text-white/40 text-sm">No packs yet</p>
              <p className="text-white/30 text-xs mt-1">Create one to begin</p>
            </div>
          )}
          {packs.map((p) => (
            <button
              key={p.id}
              onClick={() => selectPack(p)}
              data-testid={`pack-item-${p.id}`}
              className={`w-full text-left px-4 py-3 rounded-md flex items-center gap-3 group transition-colors border-l-2 ${
                selected?.id === p.id
                  ? 'bg-white/[0.04] border-gold text-white'
                  : 'border-transparent text-white/60 hover:text-white hover:bg-white/[0.02]'
              }`}
            >
              <div className="w-10 h-10 rounded overflow-hidden bg-white/5 shrink-0">
                {p.primary_photo_id ? (
                  <AuthImage mediaId={p.primary_photo_id} className="w-full h-full object-cover" alt="" />
                ) : null}
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-sm truncate">{p.name}</div>
                <div className="text-[11px] text-white/40">{p.photo_ids.length} / 5 refs</div>
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Right: pack detail */}
      <div className="flex-1 h-full overflow-y-auto">
        {!selected ? (
          <div className="h-full flex items-center justify-center">
            <div className="text-center max-w-md">
              <h3 className="font-display text-3xl text-white mb-3">Create your first Identity Pack</h3>
              <p className="text-white/50 text-sm leading-relaxed">
                Upload up to five reference photographs of yourself. These will be used to preserve
                your identity across every generation.
              </p>
            </div>
          </div>
        ) : (
          <div className="p-10 max-w-5xl">
            <div className="flex items-center justify-between mb-2">
              <h2 className="font-display text-4xl text-white tracking-tight" data-testid="pack-detail-name">{selected.name}</h2>
              <button
                onClick={() => removePack(selected.id)}
                data-testid="delete-pack-btn"
                className="text-white/50 hover:text-red-400 text-xs tracking-wide flex items-center gap-1.5 transition-colors"
              >
                <Trash2 strokeWidth={1.25} className="w-4 h-4" /> Delete Pack
              </button>
            </div>
            <p className="text-white/50 text-sm mb-8">
              {selected.photo_ids.length} of 5 reference photographs
            </p>

            <div
              className="border border-dashed border-white/10 rounded-lg p-8 mb-8 hover:border-gold/40 transition-colors cursor-pointer"
              onClick={() => fileRef.current?.click()}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                if (e.dataTransfer.files.length) uploadFiles(e.dataTransfer.files);
              }}
              data-testid="upload-dropzone"
            >
              <input
                ref={fileRef}
                type="file"
                multiple
                accept="image/png,image/jpeg,image/webp"
                className="hidden"
                onChange={(e) => e.target.files && uploadFiles(e.target.files)}
                data-testid="upload-input"
              />
              <div className="text-center">
                <Upload strokeWidth={1.25} className="w-8 h-8 mx-auto text-gold/70 mb-3" />
                <p className="text-white text-sm">Drop reference photos here, or click to browse</p>
                <p className="text-white/40 text-xs mt-1">
                  JPEG, PNG or WEBP · max 15MB each · up to 5 per pack
                </p>
              </div>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
              {selected.photo_ids.map((pid) => (
                <div key={pid} className="relative group aspect-square rounded overflow-hidden bg-white/5 border border-white/[0.06]">
                  <AuthImage mediaId={pid} className="w-full h-full object-cover" alt="" />
                  <div className="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center gap-2">
                    <button
                      onClick={() => setPrimary(pid)}
                      title="Set as primary"
                      className="p-2 rounded bg-white/10 hover:bg-gold hover:text-black text-white transition-colors"
                      data-testid={`set-primary-${pid}`}
                    >
                      {selected.primary_photo_id === pid ? <Check strokeWidth={1.5} className="w-4 h-4" /> : <Star strokeWidth={1.25} className="w-4 h-4" />}
                    </button>
                    <button
                      onClick={() => removePhoto(pid)}
                      title="Remove"
                      className="p-2 rounded bg-white/10 hover:bg-red-500 text-white transition-colors"
                      data-testid={`remove-photo-${pid}`}
                    >
                      <Trash2 strokeWidth={1.25} className="w-4 h-4" />
                    </button>
                  </div>
                  {selected.primary_photo_id === pid && (
                    <div className="absolute top-2 left-2 bg-gold text-black text-[10px] px-2 py-0.5 rounded uppercase tracking-widest font-medium">
                      Primary
                    </div>
                  )}
                </div>
              ))}
            </div>

            <div className="mt-10 lumina-glass rounded-lg p-6">
              <h4 className="text-white text-sm font-medium tracking-wide mb-2">Reference photo guidance</h4>
              <ul className="text-white/50 text-sm space-y-1 list-disc list-inside">
                <li>Clear, unfiltered face · natural lighting · no sunglasses</li>
                <li>Multiple angles: front, three-quarter, left / right profile</li>
                <li>Include at least one full-body photograph</li>
                <li>Consistent age and appearance across all references</li>
              </ul>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
