import { useEffect, useState } from 'react';
import { fetchMediaBlobUrl, makeAbortController } from '../lib/api';

/** Authenticated image tag – fetches media by id with token, shows as <img>. */
export default function AuthImage({ mediaId, alt = '', className = '', ...props }) {
  const [src, setSrc] = useState(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    let url = null;
    let cancelled = false;
    const controller = makeAbortController();
    if (!mediaId) return undefined;
    setErr(false);
    setSrc(null);
    fetchMediaBlobUrl(mediaId, { signal: controller.signal })
      .then((u) => {
        if (cancelled) {
          URL.revokeObjectURL(u);
          return;
        }
        url = u;
        setSrc(u);
      })
      .catch((error) => {
        if (cancelled || error?.isAborted || error?.code === 'aborted') return;
        setErr(true);
      });
    return () => {
      cancelled = true;
      controller.abort();
      if (url) URL.revokeObjectURL(url);
    };
  }, [mediaId]);

  if (err) {
    return (
      <div className={`flex items-center justify-center bg-white/[0.02] text-white/30 text-xs ${className}`}>
        image unavailable
      </div>
    );
  }
  if (!src) {
    return (
      <div
        className={`bg-white/[0.02] animate-pulse ${className}`}
        style={{
          backgroundImage:
            'linear-gradient(90deg, rgba(255,255,255,0.02) 0%, rgba(212,175,55,0.06) 50%, rgba(255,255,255,0.02) 100%)',
          backgroundSize: '1000px 100%',
        }}
      />
    );
  }
  return <img src={src} alt={alt} className={className} onError={() => setErr(true)} {...props} />;
}
