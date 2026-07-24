// Simple timeline component: draggable clip strip with trim + split + delete.
import { useMemo } from 'react';
import { effectiveDuration, totalDuration } from './model';

const PX_PER_SEC = 40;

export default function Timeline({
  state, currentTime, setCurrentTime, selectedClipId, setSelectedClipId,
  onReorder, onDeleteClip, onDuplicateClip, onSplit, onTrim,
}) {
  const total = totalDuration(state);
  const width = Math.max(600, total * PX_PER_SEC);

  // Compute clip x offsets
  const layout = useMemo(() => {
    let acc = 0;
    return (state.clips || []).map((c) => {
      const w = effectiveDuration(c) * PX_PER_SEC;
      const item = { c, x: acc, w };
      acc += w;
      return item;
    });
  }, [state.clips]);

  const seekAt = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const px = e.clientX - rect.left;
    setCurrentTime(Math.max(0, Math.min(total, px / PX_PER_SEC)));
  };

  return (
    <div className="w-full overflow-x-auto overflow-y-hidden bg-ink-900 border-t border-white/[0.06]">
      <div style={{ width, minHeight: 140 }} className="relative">
        {/* Time ruler */}
        <div className="h-6 flex items-end text-[10px] text-white/40 select-none" onClick={seekAt} data-testid="timeline-ruler">
          {Array.from({ length: Math.ceil(total) + 1 }).map((_, i) => (
            <div key={i} style={{ position: 'absolute', left: i * PX_PER_SEC, top: 0, height: '100%' }} className="border-l border-white/10 pl-1">
              {i}s
            </div>
          ))}
        </div>

        {/* Video clip track */}
        <div className="relative h-16 bg-white/[0.02] mt-2" data-testid="video-track">
          {layout.map(({ c, x, w }, idx) => (
            <ClipItem
              key={c.id}
              clip={c}
              x={x}
              w={w}
              selected={selectedClipId === c.id}
              onSelect={() => setSelectedClipId(c.id)}
              onDelete={() => onDeleteClip(c.id)}
              onDuplicate={() => onDuplicateClip(c.id)}
              onTrim={(deltaStart, deltaEnd) => onTrim(c.id, deltaStart, deltaEnd)}
              onMoveUp={() => onReorder(idx, -1)}
              onMoveDown={() => onReorder(idx, +1)}
            />
          ))}
        </div>

        {/* Text overlay track */}
        <div className="relative h-6 bg-white/[0.02] mt-2 flex items-center pl-2 text-[11px] text-white/50" data-testid="text-track">
          Text overlays
          {(state.textOverlays || []).map((t) => (
            <div key={t.id} style={{ position: 'absolute', left: t.start * PX_PER_SEC, width: Math.max(40, (t.end - t.start) * PX_PER_SEC), top: 2 }}
              className="h-5 bg-gold/20 border border-gold/60 rounded text-[10px] px-2 text-gold truncate flex items-center">
              {t.text}
            </div>
          ))}
        </div>

        {/* Audio tracks */}
        <div className="relative h-4 bg-white/[0.02] mt-1 text-[10px] text-white/40 pl-2 flex items-center" data-testid="music-track">
          {state.music ? `Music (vol ${state.music.volume ?? 60}%)` : 'Music track (empty)'}
        </div>
        <div className="relative h-4 bg-white/[0.02] mt-1 text-[10px] text-white/40 pl-2 flex items-center" data-testid="voice-track">
          {state.voiceover ? `Voice-over (vol ${state.voiceover.volume ?? 100}%)` : 'Voice-over track (empty)'}
        </div>

        {/* Playhead */}
        <div
          data-testid="playhead"
          style={{ position: 'absolute', top: 0, bottom: 0, left: currentTime * PX_PER_SEC, width: 2, background: '#D4AF37', pointerEvents: 'none' }}
        />
      </div>
    </div>
  );
}

function ClipItem({ clip, x, w, selected, onSelect, onDelete, onDuplicate, onTrim, onMoveUp, onMoveDown }) {
  return (
    <div
      style={{ position: 'absolute', left: x, width: w, top: 0, bottom: 0 }}
      onClick={onSelect}
      data-testid={`clip-${clip.id}`}
      className={`rounded overflow-hidden border cursor-pointer ${
        selected ? 'border-gold' : 'border-white/10 hover:border-white/25'
      } bg-white/5 flex items-center justify-between px-2`}
    >
      <div className="text-[10px] text-white/70 truncate">
        {clip.kind === 'photo' ? '🖼 Photo' : '🎬 Video'} · {effectiveDuration(clip).toFixed(1)}s
        {clip.transition !== 'none' && <span className="text-gold/80"> · {clip.transition}</span>}
      </div>
      {selected && (
        <div className="flex gap-1">
          {clip.kind === 'video' && (
            <>
              <button onClick={(e) => { e.stopPropagation(); onTrim(0.5, 0); }} title="Trim start +0.5s" className="text-[9px] px-1 rounded bg-white/10 hover:bg-white/20 text-white/70">‹|</button>
              <button onClick={(e) => { e.stopPropagation(); onTrim(0, -0.5); }} title="Trim end -0.5s" className="text-[9px] px-1 rounded bg-white/10 hover:bg-white/20 text-white/70">|›</button>
            </>
          )}
          <button onClick={(e) => { e.stopPropagation(); onMoveUp(); }} title="Move left" className="text-[9px] px-1 rounded bg-white/10 hover:bg-white/20 text-white/70">◀</button>
          <button onClick={(e) => { e.stopPropagation(); onMoveDown(); }} title="Move right" className="text-[9px] px-1 rounded bg-white/10 hover:bg-white/20 text-white/70">▶</button>
          <button onClick={(e) => { e.stopPropagation(); onDuplicate(); }} title="Duplicate" className="text-[9px] px-1 rounded bg-white/10 hover:bg-white/20 text-white/70">⧉</button>
          <button onClick={(e) => { e.stopPropagation(); onDelete(); }} title="Delete" className="text-[9px] px-1 rounded bg-red-500/40 hover:bg-red-500/60 text-white">✕</button>
        </div>
      )}
    </div>
  );
}
