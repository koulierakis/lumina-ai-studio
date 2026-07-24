import { useCallback } from 'react';

/** Reusable numeric slider with label, direct entry, and per-control reset. */
export default function Slider({
  label, value, min, max, step = 1, defaultValue = 0,
  onChange, onCommit, testid,
}) {
  const commit = useCallback(() => onCommit && onCommit(), [onCommit]);
  return (
    <div className="mb-4" data-testid={testid ? `slider-${testid}` : undefined}>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[11px] uppercase tracking-[0.2em] text-white/60">{label}</span>
        <div className="flex items-center gap-2">
          <input
            type="number"
            className="w-14 text-right bg-black/50 border border-white/10 rounded px-1.5 py-0.5 text-xs text-white focus:border-gold/50 focus:ring-1 focus:ring-gold/40 outline-none"
            value={value}
            min={min}
            max={max}
            step={step}
            onChange={(e) => onChange(Number(e.target.value))}
            onBlur={commit}
            data-testid={testid ? `input-${testid}` : undefined}
          />
          <button
            className="text-white/40 hover:text-gold text-[10px] uppercase tracking-widest"
            onClick={() => { onChange(defaultValue); commit(); }}
            title="Reset"
            data-testid={testid ? `reset-${testid}` : undefined}
          >
            reset
          </button>
        </div>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        onMouseUp={commit}
        onTouchEnd={commit}
        onKeyUp={commit}
        className="w-full accent-gold h-1 cursor-pointer"
      />
    </div>
  );
}
