// FFmpeg.wasm export pipeline.
// Loaded LAZILY when the editor's Export button is first pressed.

import { FFmpeg } from '@ffmpeg/ffmpeg';
import { fetchFile, toBlobURL } from '@ffmpeg/util';
import { outputDims, effectiveDuration, cssFilterFor } from './model';

// Serve the single-threaded ffmpeg-core from jsdelivr CDN. No SharedArrayBuffer needed.
const CORE_BASE = 'https://cdn.jsdelivr.net/npm/@ffmpeg/core@0.12.6/dist/umd';

let _ffmpeg = null;
let _loading = null;

async function getFFmpeg(onLog) {
  if (_ffmpeg) return _ffmpeg;
  if (_loading) return _loading;
  _loading = (async () => {
    const ff = new FFmpeg();
    if (onLog) ff.on('log', ({ message }) => onLog(message));
    await ff.load({
      coreURL: await toBlobURL(`${CORE_BASE}/ffmpeg-core.js`, 'text/javascript'),
      wasmURL: await toBlobURL(`${CORE_BASE}/ffmpeg-core.wasm`, 'application/wasm'),
    });
    _ffmpeg = ff;
    _loading = null;
    return ff;
  })();
  return _loading;
}

// Turn a media id into a File-like accessible via /api/media/{id} using the auth blob URL.
async function fetchAsset(mediaId, api) {
  const blob = await api(`/media/${mediaId}`, { responseType: 'blob' });
  return blob;
}

function ffFilterFromAdjust(clip) {
  // Map our adjustments into an -filter_complex chain.
  const a = clip.adjust || { brightness: 0, contrast: 0, saturation: 0, temperature: 0, sharpness: 0, blur: 0 };
  const parts = [];
  // eq: brightness -1..1, contrast 0..2, saturation 0..3
  const eq = [
    `brightness=${(a.brightness / 100).toFixed(3)}`,
    `contrast=${(1 + a.contrast / 100).toFixed(3)}`,
    `saturation=${(1 + a.saturation / 100).toFixed(3)}`,
    // hue for temperature
    `gamma_r=${(1 - a.temperature / 400).toFixed(3)}`,
    `gamma_b=${(1 + a.temperature / 400).toFixed(3)}`,
  ].join(':');
  parts.push(`eq=${eq}`);
  if (a.blur > 0) parts.push(`gblur=sigma=${a.blur.toFixed(1)}`);
  if (a.sharpness > 0) parts.push(`unsharp=5:5:${(a.sharpness / 100).toFixed(2)}`);
  // Preset filters
  if (clip.filter === 'B&W') parts.push('hue=s=0');
  if (clip.filter === 'Vintage') parts.push('curves=vintage');
  if (clip.filter === 'Warm') parts.push('colorbalance=rm=0.1:bm=-0.05');
  if (clip.filter === 'Cool') parts.push('colorbalance=rm=-0.05:bm=0.08');
  return parts.join(',');
}

/**
 * Render a full project to MP4. Progressive callback: (msg, pct 0..100).
 * Because ffmpeg.wasm is heavy, we do a two-pass approach:
 *   1. Normalize each clip to <w>x<h> @ <fps>, apply per-clip filters, output N intermediate MP4s.
 *   2. Concat via -f concat, then overlay music/voice (if any).
 */
export async function exportProject({
  project, api, onProgress, onLog,
}) {
  const ff = await getFFmpeg(onLog);
  const { w, h } = outputDims(project.aspect_ratio, project.resolution);
  const fps = project.fps || 30;
  const state = project.state || {};
  const clips = state.clips || [];
  if (!clips.length) throw new Error('No clips to export');

  onProgress && onProgress('Loading FFmpeg core…', 2);

  // ---- Step 1: Write all input assets ----
  onProgress && onProgress('Fetching assets…', 5);
  const written = new Map(); // assetId -> input filename
  const uniqueAssets = new Set(clips.map((c) => c.assetId));
  if (state.music?.assetId) uniqueAssets.add(state.music.assetId);
  if (state.voiceover?.assetId) uniqueAssets.add(state.voiceover.assetId);

  let idx = 0;
  for (const assetId of uniqueAssets) {
    const blob = await fetchAsset(assetId, api);
    const ext = extForBlob(blob.type);
    const name = `in_${idx}${ext}`;
    await ff.writeFile(name, await fetchFile(blob));
    written.set(assetId, name);
    idx++;
  }

  // ---- Step 2: Normalize each clip ----
  const intermediates = [];
  for (let i = 0; i < clips.length; i++) {
    const c = clips[i];
    const inFile = written.get(c.assetId);
    const outFile = `clip_${i}.mp4`;
    const dur = effectiveDuration(c);
    const filterChain = ffFilterFromAdjust(c);

    // scale + pad to letterbox to target dims
    const scalePad = `scale=${w}:${h}:force_original_aspect_ratio=decrease,pad=${w}:${h}:(ow-iw)/2:(oh-ih)/2:color=black`;
    const vf = [filterChain, scalePad].filter(Boolean).join(',');

    if (c.kind === 'photo') {
      // Loop still image for duration, apply Ken Burns zoompan if requested
      const zoompan = kenBurnsFilter(c.kenBurns, dur, fps, w, h);
      const vf2 = [zoompan, vf].filter(Boolean).join(',');
      await ff.exec([
        '-loop', '1', '-t', String(dur), '-i', inFile,
        '-vf', vf2, '-r', String(fps),
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'ultrafast', '-crf', '23',
        '-t', String(dur), '-an', outFile,
      ]);
    } else {
      const ss = Math.max(0, c.trimStart || 0);
      await ff.exec([
        '-ss', String(ss), '-i', inFile, '-t', String(dur),
        '-vf', vf, '-r', String(fps),
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'ultrafast', '-crf', '23',
        // Keep original audio at chosen volume; will remix later.
        '-c:a', 'aac', '-b:a', '128k', '-af', `volume=${((c.volume ?? 100) / 100).toFixed(2)}`,
        outFile,
      ]);
    }
    intermediates.push(outFile);
    onProgress && onProgress(`Rendering clip ${i + 1}/${clips.length}`, 5 + Math.round(60 * (i + 1) / clips.length));
  }

  // ---- Step 3: Concat intermediates ----
  const listContent = intermediates.map((f) => `file '${f}'`).join('\n');
  await ff.writeFile('list.txt', new TextEncoder().encode(listContent));
  onProgress && onProgress('Joining clips…', 70);
  await ff.exec([
    '-f', 'concat', '-safe', '0', '-i', 'list.txt',
    '-c', 'copy', 'joined.mp4',
  ]);

  // ---- Step 4: Mix music + voiceover if present ----
  let finalFile = 'joined.mp4';
  const audioInputs = [];
  const audioFilters = [];
  const totalDurValue = clips.reduce((s, c) => s + effectiveDuration(c), 0);

  if (state.music?.assetId) {
    audioInputs.push('-i', written.get(state.music.assetId));
    const vol = ((state.music.volume ?? 60) / 100).toFixed(2);
    const fi = state.music.fadeIn || 0;
    const fo = state.music.fadeOut || 0;
    let f = `volume=${vol}`;
    if (fi > 0) f += `,afade=t=in:st=0:d=${fi}`;
    if (fo > 0) f += `,afade=t=out:st=${(totalDurValue - fo).toFixed(2)}:d=${fo}`;
    audioFilters.push({ tag: 'music', filter: f });
  }
  if (state.voiceover?.assetId) {
    audioInputs.push('-i', written.get(state.voiceover.assetId));
    const vol = ((state.voiceover.volume ?? 100) / 100).toFixed(2);
    audioFilters.push({ tag: 'voice', filter: `volume=${vol}` });
  }

  if (audioInputs.length) {
    onProgress && onProgress('Mixing audio…', 82);
    // Build filter_complex to mix joined audio + music + voice
    const mapCount = 1 + audioFilters.length; // [0:a] then extras
    const chains = [];
    let extraIdx = 1;
    const streams = ['[0:a]']; // original from joined.mp4
    for (const af of audioFilters) {
      chains.push(`[${extraIdx}:a]${af.filter}[${af.tag}]`);
      streams.push(`[${af.tag}]`);
      extraIdx++;
    }
    const mix = `${streams.join('')}amix=inputs=${mapCount}:duration=first:dropout_transition=0[aout]`;
    chains.push(mix);
    await ff.exec([
      '-i', 'joined.mp4',
      ...audioInputs,
      '-filter_complex', chains.join(';'),
      '-map', '0:v', '-map', '[aout]',
      '-c:v', 'copy', '-c:a', 'aac', '-b:a', '160k',
      '-shortest', 'final.mp4',
    ]);
    finalFile = 'final.mp4';
  }

  onProgress && onProgress('Reading output…', 96);
  const outData = await ff.readFile(finalFile);
  const blob = new Blob([outData.buffer], { type: 'video/mp4' });

  // Cleanup FS
  try {
    for (const [, name] of written) await ff.deleteFile(name).catch(() => {});
    for (const f of intermediates) await ff.deleteFile(f).catch(() => {});
    await ff.deleteFile('list.txt').catch(() => {});
    await ff.deleteFile('joined.mp4').catch(() => {});
    await ff.deleteFile('final.mp4').catch(() => {});
  } catch { /* ignore */ }

  onProgress && onProgress('Done', 100);
  return blob;
}

function extForBlob(mime) {
  if (!mime) return '.bin';
  if (mime.startsWith('image/')) return '.' + (mime.split('/')[1] || 'png');
  if (mime.startsWith('video/')) return mime === 'video/mp4' ? '.mp4' : '.webm';
  if (mime.startsWith('audio/')) return mime === 'audio/webm' ? '.webm' : mime === 'audio/mpeg' ? '.mp3' : '.wav';
  return '.bin';
}

function kenBurnsFilter(mode, dur, fps, w, h) {
  const frames = Math.max(1, Math.round(dur * fps));
  if (!mode || mode === 'none') return '';
  // zoompan requires integer frames. Zoom range 1.0 -> 1.12 for zoom-in.
  switch (mode) {
    case 'zoom-in':
      return `zoompan=z='min(1+on/${frames}*0.12,1.12)':d=${frames}:s=${w}x${h}:fps=${fps}`;
    case 'zoom-out':
      return `zoompan=z='max(1.12-on/${frames}*0.12,1.0)':d=${frames}:s=${w}x${h}:fps=${fps}`;
    case 'pan-left':
      return `zoompan=z='1.1':x='iw*0.05-on/${frames}*iw*0.1':y='ih*0.05':d=${frames}:s=${w}x${h}:fps=${fps}`;
    case 'pan-right':
      return `zoompan=z='1.1':x='on/${frames}*iw*0.1':y='ih*0.05':d=${frames}:s=${w}x${h}:fps=${fps}`;
    default: return '';
  }
}
