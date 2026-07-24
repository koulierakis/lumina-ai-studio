// Editor keyboard shortcuts hook.
import { useEffect } from 'react';

/**
 * Registers document-level keyboard shortcuts scoped to the editor.
 * Handlers is an object of { undo, redo, save, resetAll, zoomIn, zoomOut, fit, actual, escape }.
 */
export default function useEditorShortcuts(handlers) {
  useEffect(() => {
    const onKey = (e) => {
      // Ignore when typing inside inputs/textareas.
      const tag = (e.target && e.target.tagName) || '';
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(tag)) return;

      const ctrl = e.ctrlKey || e.metaKey;
      if (ctrl && !e.shiftKey && e.key.toLowerCase() === 'z') {
        e.preventDefault();
        handlers.undo?.();
        return;
      }
      if (ctrl && (e.shiftKey && e.key.toLowerCase() === 'z')) {
        e.preventDefault();
        handlers.redo?.();
        return;
      }
      if (ctrl && e.key.toLowerCase() === 'y') {
        e.preventDefault();
        handlers.redo?.();
        return;
      }
      if (ctrl && e.key.toLowerCase() === 's') {
        e.preventDefault();
        handlers.save?.();
        return;
      }
      if (e.key === '+' || e.key === '=') {
        e.preventDefault();
        handlers.zoomIn?.();
        return;
      }
      if (e.key === '-' || e.key === '_') {
        e.preventDefault();
        handlers.zoomOut?.();
        return;
      }
      if (e.key === '0') {
        e.preventDefault();
        handlers.fit?.();
        return;
      }
      if (e.key === '1') {
        e.preventDefault();
        handlers.actual?.();
        return;
      }
      if (e.key === 'Escape') {
        handlers.escape?.();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [handlers]);
}
