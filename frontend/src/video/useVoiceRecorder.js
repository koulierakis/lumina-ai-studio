// Simple in-browser microphone recorder using MediaRecorder.
import { useCallback, useRef, useState } from 'react';

export default function useVoiceRecorder() {
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const mediaRef = useRef(null);
  const chunksRef = useRef([]);
  const startTsRef = useRef(0);
  const tickRef = useRef(null);

  const start = useCallback(async () => {
    if (recording) return;
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mr = new MediaRecorder(stream, { mimeType: 'audio/webm' });
    chunksRef.current = [];
    mr.ondataavailable = (e) => { if (e.data.size) chunksRef.current.push(e.data); };
    mr.start(200);
    mediaRef.current = { mr, stream };
    startTsRef.current = Date.now();
    setElapsed(0);
    setRecording(true);
    tickRef.current = setInterval(() => setElapsed((Date.now() - startTsRef.current) / 1000), 200);
  }, [recording]);

  const stop = useCallback(() => new Promise((resolve) => {
    const { mr, stream } = mediaRef.current || {};
    if (!mr) return resolve(null);
    mr.onstop = () => {
      const blob = new Blob(chunksRef.current, { type: 'audio/webm' });
      stream.getTracks().forEach((t) => t.stop());
      clearInterval(tickRef.current);
      setRecording(false);
      resolve(blob);
    };
    mr.stop();
  }), []);

  return { recording, elapsed, start, stop };
}
