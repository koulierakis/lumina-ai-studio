import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  calculateMeasuredPages,
  formatPageNumber,
  normalizePageLayout,
  pageContentBox,
  pageDimensions,
  renderLayoutText,
} from './editorModel';

const MEASURE_DEBOUNCE_MS = 80;

function collectBlockMetrics(root) {
  if (!root) return [];
  const editable = root.querySelector('[contenteditable="true"]') || root;
  const children = Array.from(editable.children || []);
  const source = children.length ? children : [editable];

  return source.map((element) => {
    const rect = element.getBoundingClientRect?.();
    const styles = window.getComputedStyle ? window.getComputedStyle(element) : null;
    const marginTop = parseFloat(styles?.marginTop || '0') || 0;
    const marginBottom = parseFloat(styles?.marginBottom || '0') || 0;
    return {
      height: Math.max(0, rect?.height || element.scrollHeight || 0) + marginTop + marginBottom,
      pageBreak: element.getAttribute?.('data-lumina-page-break') === 'true' || /page-break-after\s*:\s*always|break-after\s*:\s*page/i.test(element.getAttribute?.('style') || ''),
    };
  });
}

export function measurePageFlow(editorElement, layout) {
  const contentBox = pageContentBox(layout);
  const editable = editorElement?.querySelector?.('[contenteditable="true"]') || editorElement;
  if (!editable || !contentBox.heightPx || !Number.isFinite(contentBox.heightPx)) {
    throw new Error('Page flow measurement target is unavailable.');
  }

  const blockMetrics = collectBlockMetrics(editorElement);
  const scrollHeight = editable.scrollHeight || editorElement.scrollHeight || 0;
  const pageCount = calculateMeasuredPages({
    blockMetrics,
    contentHeightPx: contentBox.heightPx,
    scrollHeightPx: scrollHeight,
  });

  return {
    pageCount,
    contentHeightPx: contentBox.heightPx,
    contentWidthPx: contentBox.widthPx,
    measuredAt: Date.now(),
  };
}

export default function PaginatedDocumentWorkspace({
  document,
  html,
  layout,
  zoom = 90,
  preview = false,
  editor = null,
  editorElementRef = null,
  onPageFlowChange,
  children,
}) {
  const normalized = useMemo(() => normalizePageLayout(layout), [layout]);
  const dimensions = useMemo(() => pageDimensions(normalized), [normalized]);
  const contentBox = useMemo(() => pageContentBox(normalized), [normalized]);
  const scale = preview ? 1 : zoom / 100;
  const [flow, setFlow] = useState({ pageCount: 1, mode: 'paginated', warning: '' });
  const measureTimerRef = useRef(null);
  const resizeObserverRef = useRef(null);
  const lastSignatureRef = useRef('');

  const emitFlow = useCallback((next) => {
    setFlow((current) => {
      if (current.pageCount === next.pageCount && current.mode === next.mode && current.warning === next.warning) return current;
      return next;
    });
    onPageFlowChange?.(next);
  }, [onPageFlowChange]);

  const scheduleMeasure = useCallback(() => {
    if (preview || !children) return;
    window.clearTimeout(measureTimerRef.current);
    measureTimerRef.current = window.setTimeout(() => {
      try {
        const result = measurePageFlow(editorElementRef?.current, normalized);
        const signature = `${result.pageCount}:${Math.round(result.contentHeightPx)}:${Math.round(result.contentWidthPx)}`;
        if (signature !== lastSignatureRef.current) {
          lastSignatureRef.current = signature;
          emitFlow({ ...result, mode: 'paginated', warning: '' });
        }
      } catch (error) {
        emitFlow({ pageCount: 1, mode: 'continuous', warning: 'Page measurement is temporarily unavailable. Continuous editing mode is active and content is preserved.' });
      }
    }, MEASURE_DEBOUNCE_MS);
  }, [children, editorElementRef, emitFlow, normalized, preview]);

  useEffect(() => {
    scheduleMeasure();
    return () => window.clearTimeout(measureTimerRef.current);
  }, [html, normalized, scheduleMeasure]);

  useEffect(() => {
    if (preview || !children || !editor) return undefined;
    return editor.registerUpdateListener(() => scheduleMeasure());
  }, [children, editor, preview, scheduleMeasure]);

  useEffect(() => {
    if (preview || !children || !editorElementRef?.current || typeof ResizeObserver === 'undefined') return undefined;
    resizeObserverRef.current?.disconnect();
    resizeObserverRef.current = new ResizeObserver(() => scheduleMeasure());
    resizeObserverRef.current.observe(editorElementRef.current);
    const editable = editorElementRef.current.querySelector?.('[contenteditable="true"]');
    if (editable) resizeObserverRef.current.observe(editable);
    return () => resizeObserverRef.current?.disconnect();
  }, [children, editorElementRef, preview, scheduleMeasure]);

  const pageCount = preview ? Math.max(1, flow.pageCount) : Math.max(1, flow.pageCount);
  const pages = Array.from({ length: pageCount }, (_, index) => index + 1);
  const pageNumberPosition = normalized.pageNumbers.position || 'bottom-center';
  const scaledWidth = dimensions.width * scale;

  return (
    <div className={`lumina-page-workspace ${preview ? 'is-preview' : ''} ${flow.mode === 'continuous' ? 'is-continuous-fallback' : ''}`} data-page-count={pageCount} data-page-flow-mode={flow.mode}>
      {flow.warning && <div className="lumina-page-flow-warning" role="status">{flow.warning}</div>}
      <div className="lumina-page-stack" style={{ width: `${scaledWidth}mm` }}>
        {pages.map((pageNumber) => (
          <section
            key={pageNumber}
            className="lumina-print-page"
            aria-label={`Page ${pageNumber}`}
            style={{
              width: `${dimensions.width}mm`,
              height: `${dimensions.height}mm`,
              padding: `${normalized.margins.top}mm ${normalized.margins.right}mm ${normalized.margins.bottom}mm ${normalized.margins.left}mm`,
              background: normalized.background,
              transform: `scale(${scale})`,
              transformOrigin: 'top left',
              marginBottom: `${Math.max(28, dimensions.height * (scale - 1) + 36)}px`,
            }}
          >
            <div className="lumina-page-content-guide" style={{ height: `${contentBox.heightMm}mm` }} />
            {normalized.pageNumbers.enabled && pageNumberPosition !== 'none' && (
              <span className={`lumina-page-number ${pageNumberPosition}`}>{formatPageNumber(normalized.pageNumbers.format, pageNumber, pageCount)}</span>
            )}
          </section>
        ))}
        {children && (
          <div
            ref={editorElementRef}
            className="lumina-paginated-editor-layer"
            style={{
              width: `${dimensions.width}mm`,
              minHeight: `${dimensions.height * pageCount}mm`,
              padding: `${normalized.margins.top}mm ${normalized.margins.right}mm ${normalized.margins.bottom}mm ${normalized.margins.left}mm`,
              transform: `scale(${scale})`,
              transformOrigin: 'top left',
              color: 'inherit',
            }}
          >
            <div
              className="lumina-page-flow-editor"
              style={{
                width: `${contentBox.widthMm}mm`,
                minHeight: `${contentBox.heightMm}mm`,
              }}
            >
              {children}
            </div>
          </div>
        )}
        {preview && (
          <PreviewBody document={document} html={html} layout={normalized} pageCount={pageCount} />
        )}
      </div>
    </div>
  );
}

function PreviewBody({ document, html, layout, pageCount }) {
  const dimensions = pageDimensions(layout);
  const contentBox = pageContentBox(layout);
  const pageNumberPosition = layout.pageNumbers.position || 'bottom-center';
  return (
    <div className="lumina-preview-html-layer" style={{ width: `${dimensions.width}mm` }}>
      {Array.from({ length: pageCount }, (_, index) => (
        <section key={index + 1} className="lumina-preview-page-body" style={{ minHeight: `${contentBox.heightMm}mm` }}>
          {layout.header.enabled && (!layout.header.firstPageOnly || index === 0) && <header className="lumina-page-header">{renderLayoutText(layout.header.text, document, index + 1, pageCount)}</header>}
          <main dangerouslySetInnerHTML={{ __html: index === 0 ? html || '<p></p>' : '' }} />
          {layout.footer.enabled && (!layout.footer.firstPageOnly || index === 0) && <footer className="lumina-page-footer">{renderLayoutText(layout.footer.text, document, index + 1, pageCount)}</footer>}
          {layout.pageNumbers.enabled && pageNumberPosition !== 'none' && <span className={`lumina-page-number ${pageNumberPosition}`}>{formatPageNumber(layout.pageNumbers.format, index + 1, pageCount)}</span>}
        </section>
      ))}
    </div>
  );
}
