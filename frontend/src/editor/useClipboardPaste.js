// Clipboard image paste — Ctrl+V on the document opens the pasted image
// as a new editor source.
import { useEffect } from 'react';

/**
 * onImage(blob, mime) is called whenever the clipboard contains an image and
 * Ctrl+V is pressed OUTSIDE of a text field.
 */
export default function useClipboardPaste(onImage) {
  useEffect(() => {
    const handler = async (e) => {
      const tag = (e.target && e.target.tagName) || '';
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(tag)) return; // let the field handle it
      const items = e.clipboardData?.items || [];
      for (const it of items) {
        if (it.type && it.type.startsWith('image/')) {
          const blob = it.getAsFile();
          if (blob) {
            e.preventDefault();
            onImage(blob, it.type);
            return;
          }
        }
      }
    };
    window.addEventListener('paste', handler);
    return () => window.removeEventListener('paste', handler);
  }, [onImage]);
}
