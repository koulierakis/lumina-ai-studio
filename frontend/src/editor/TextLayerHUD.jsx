import { useRef, useState } from 'react';
import { textLayerStyle } from './textLayers';

/**
 * On-canvas draggable/rotatable/resizable text layer.
 * All coordinates are in percent of the image (position independent of zoom).
 */
export default function TextLayerHUD({
  layer, selected, onSelect, onChange, onCommit, natW, natH, imgRect,
}) {
  const [drag, setDrag] = useState(null);
  const boxRef = useRef(null);

  if (layer.hidden || !imgRect) return null;

  const onMouseDown = (e, mode = 'move') => {
    if (layer.locked) return;
    e.stopPropagation();
    onSelect && onSelect(layer.id);
    setDrag({
      mode,
      startX: e.clientX,
      startY: e.clientY,
      start: { x: layer.x, y: layer.y, w: layer.w, h: layer.h, rotation: layer.rotation },
    });
  };

  const onMouseMove = (e) => {
    if (!drag) return;
    const dxPx = e.clientX - drag.startX;
    const dyPx = e.clientY - drag.startY;
    const dxPct = (dxPx / imgRect.width) * 100;
    const dyPct = (dyPx / imgRect.height) * 100;
    if (drag.mode === 'move') {
      onChange({ ...layer, x: clampPct(drag.start.x + dxPct, 0, 100 - layer.w), y: clampPct(drag.start.y + dyPct, 0, 100 - layer.h) });
    } else if (drag.mode === 'resize') {
      onChange({
        ...layer,
        w: Math.max(4, Math.min(100 - drag.start.x, drag.start.w + dxPct)),
        h: Math.max(2, Math.min(100 - drag.start.y, drag.start.h + dyPct)),
      });
    } else if (drag.mode === 'rotate') {
      const rect = boxRef.current.getBoundingClientRect();
      const cx = rect.left + rect.width / 2;
      const cy = rect.top + rect.height / 2;
      const angle = (Math.atan2(e.clientY - cy, e.clientX - cx) * 180) / Math.PI;
      onChange({ ...layer, rotation: Math.round(angle + 90) });
    }
  };
  const onMouseUp = () => {
    if (drag) onCommit && onCommit();
    setDrag(null);
  };

  const previewScale = imgRect.width / (natW || 1);
  const style = textLayerStyle(layer, natW, natH, previewScale);

  return (
    <>
      {drag && (
        <div
          style={{ position: 'fixed', inset: 0, zIndex: 40, cursor: drag.mode === 'move' ? 'grabbing' : 'crosshair' }}
          onMouseMove={onMouseMove}
          onMouseUp={onMouseUp}
        />
      )}
      <div
        ref={boxRef}
        onMouseDown={(e) => onMouseDown(e, 'move')}
        onDoubleClick={() => onSelect && onSelect(layer.id, true)}
        data-testid={`text-layer-${layer.id}`}
        style={{
          position: 'absolute',
          left: `${layer.x}%`, top: `${layer.y}%`,
          width: `${layer.w}%`, height: `${layer.h}%`,
          transform: `rotate(${layer.rotation}deg)`,
          transformOrigin: 'center center',
          outline: selected ? '1.5px dashed #D4AF37' : 'none',
          outlineOffset: 2,
          zIndex: 5,
          display: 'flex',
          alignItems: 'center',
          justifyContent: layer.align === 'left' ? 'flex-start' : layer.align === 'right' ? 'flex-end' : 'center',
          cursor: layer.locked ? 'not-allowed' : 'grab',
        }}
      >
        <div style={{ ...style, width: '100%' }}>
          {layer.text}
        </div>
        {selected && !layer.locked && (
          <>
            <Handle onDown={(e) => onMouseDown(e, 'resize')} pos="br" testid={`resize-${layer.id}`} />
            <Handle onDown={(e) => onMouseDown(e, 'rotate')} pos="top" rotate testid={`rotate-${layer.id}`} />
          </>
        )}
      </div>
    </>
  );
}

function clampPct(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

function Handle({ onDown, pos, rotate, testid }) {
  const stylePos = pos === 'br'
    ? { right: -6, bottom: -6, cursor: 'nwse-resize' }
    : { left: '50%', top: -22, transform: 'translateX(-50%)', cursor: 'grab' };
  return (
    <div
      onMouseDown={(e) => { e.stopPropagation(); onDown(e); }}
      data-testid={testid}
      style={{
        position: 'absolute', width: rotate ? 12 : 10, height: rotate ? 12 : 10,
        background: '#D4AF37', border: '1.5px solid #050505', borderRadius: rotate ? '50%' : 2,
        ...stylePos,
      }}
    />
  );
}
