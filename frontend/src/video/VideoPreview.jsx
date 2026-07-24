// Video preview canvas — plays back the timeline visually.
// For MVP simplicity: shows the currently active clip only (transitions
// are still applied at export time via ffmpeg xfade in a future pass;
// preview crossfade is a visual approximation).
import { useEffect, useRef, useState } from 'react';
import { fetchMediaBlobUrl } from '../lib/api';
import { locateAt, cssFilterFor, kenBurnsTransform, effectiveDuration } from './model';

export default function VideoPreview({ state, currentTime, aspect, playing }) {
  const [assetUrls, setAssetUrls] = useState({});
  const videoRefs = useRef({});
  const [aspectRatioValue] = useState(() => {
    const [w, h] = aspect.split(':').map(Number);
    return w / h;
  });

  // Load blob URLs for every asset id
  useEffect(() => {
    let cancelled = false;
    const ids = Array.from(new Set((state.clips || []).map((c) => c.assetId)));
    const newIds = ids.filter((id) => !assetUrls[id]);
    if (newIds.length === 0) return;
    (async () => {
      const additions = {};
      for (const id of newIds) {
        try {
          additions[id] = await fetchMediaBlobUrl(id);
        } catch { /* ignore */ }
      }
      if (!cancelled) setAssetUrls((u) => ({ ...u, ...additions }));
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.clips.map((c) => c.assetId).join(',')]);

  const clips = state.clips || [];
  if (clips.length === 0) {
    return (
      <div className="w-full h-full flex items-center justify-center bg-black">
        <p className="text-white/40 text-sm">Add clips or photos to see a preview</p>
      </div>
    );
  }

  const { index, localTime } = locateAt(state, currentTime);
  const clip = clips[index];
  const dur = effectiveDuration(clip);
  const progress = Math.min(1, Math.max(0, localTime / dur));

  // Seek videos when currentTime changes
  useEffect(() => {
    if (!clip) return;
    if (clip.kind !== 'video') return;
    const v = videoRefs.current[clip.id];
    if (!v) return;
    const target = (clip.trimStart || 0) + localTime;
    if (playing) {
      if (Math.abs(v.currentTime - target) > 0.25) v.currentTime = target;
      if (v.paused) v.play().catch(() => {});
    } else {
      v.currentTime = target;
      if (!v.paused) v.pause();
    }
  }, [clip?.id, localTime, playing]);

  // Pause all other videos
  useEffect(() => {
    Object.entries(videoRefs.current).forEach(([id, v]) => {
      if (!v) return;
      if (id !== clip?.id && !v.paused) v.pause();
    });
  }, [clip?.id]);

  // Overlay text layers that intersect current time
  const overlays = (state.textOverlays || []).filter((t) => currentTime >= (t.start ?? 0) && currentTime <= (t.end ?? 3));

  return (
    <div className="w-full h-full flex items-center justify-center bg-black overflow-hidden">
      <div
        style={{
          aspectRatio: `${aspectRatioValue}`,
          maxWidth: '100%', maxHeight: '100%',
          position: 'relative', width: '100%',
        }}
        data-testid="video-preview"
      >
        {clips.map((c) => {
          const isActive = c.id === clip.id;
          if (c.kind === 'video') {
            return (
              <video
                key={c.id}
                ref={(el) => (videoRefs.current[c.id] = el)}
                src={assetUrls[c.assetId]}
                muted={!isActive}
                playsInline
                style={{
                  position: 'absolute', inset: 0, width: '100%', height: '100%',
                  objectFit: 'contain', background: 'black',
                  visibility: isActive ? 'visible' : 'hidden',
                  filter: isActive ? cssFilterFor(c) : 'none',
                }}
                data-testid={`preview-video-${c.id}`}
              />
            );
          }
          return isActive && (
            <img
              key={c.id}
              src={assetUrls[c.assetId]}
              alt=""
              style={{
                position: 'absolute', inset: 0, width: '100%', height: '100%',
                objectFit: 'contain',
                filter: cssFilterFor(c),
                transform: kenBurnsTransform(c.kenBurns, progress),
                transformOrigin: 'center center',
                transition: playing ? `transform ${dur}s linear` : 'none',
              }}
              data-testid={`preview-photo-${c.id}`}
            />
          );
        })}

        {overlays.map((t) => (
          <div
            key={t.id}
            style={{
              position: 'absolute',
              left: `${t.x}%`, top: `${t.y}%`,
              width: `${t.w}%`,
              color: t.color,
              fontFamily: t.fontFamily,
              fontSize: `${t.fontSize / 3}px`,
              fontWeight: t.bold ? 700 : 400,
              fontStyle: t.italic ? 'italic' : 'normal',
              textAlign: t.align,
              opacity: t.opacity / 100,
              textShadow: t.shadow?.on ? `${t.shadow.x}px ${t.shadow.y}px ${t.shadow.blur}px ${t.shadow.color}` : 'none',
              WebkitTextStroke: t.outline?.on ? `${t.outline.width}px ${t.outline.color}` : undefined,
              pointerEvents: 'none',
              transform: `rotate(${t.rotation || 0}deg)`,
            }}
          >
            {t.text}
          </div>
        ))}
      </div>
    </div>
  );
}
