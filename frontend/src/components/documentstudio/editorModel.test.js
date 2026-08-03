import {
  DEFAULT_PAGE_LAYOUT,
  PAGE_NUMBER_POSITIONS,
  PageBreakNode,
  applyFindReplace,
  buildAdvancedTableHtml,
  buildExportLayoutPayload,
  buildImageFigureHtml,
  createPageBreakNode,
  documentAccessibilityAudit,
  documentPerformanceAudit,
  extractDocumentOutline,
  extractDocumentImages,
  findReplacePreview,
  formatPageNumber,
  getPageRegionText,
  normalizeImageAsset,
  normalizeLegacyPageBreaks,
  normalizePageLayout,
  normalizeTableModel,
  pageDimensions,
  pageContentBox,
  paginateDocumentHtml,
  renderLayoutText,
  sanitizeEditorHtml,
  spellCheckFoundation,
  summarizeTables,
} from './editorModel';

describe('document studio page layout model', () => {
  it('provides safe defaults for legacy documents', () => {
    const layout = normalizePageLayout();
    expect(layout).toMatchObject(DEFAULT_PAGE_LAYOUT);
    expect(layout.margins).toEqual(DEFAULT_PAGE_LAYOUT.margins);
  });

  it('persists size, orientation and margins for A4 and Letter layouts', () => {
    const a4 = normalizePageLayout({ size: 'A4', orientation: 'portrait', margins: { top: 24, right: 20, bottom: 20, left: 20 } });
    const letter = normalizePageLayout({ size: 'Letter', orientation: 'landscape', margins: { top: 18, right: 16, bottom: 12, left: 14 } });

    expect(a4.size).toBe('A4');
    expect(a4.orientation).toBe('portrait');
    expect(a4.margins).toEqual({ top: 24, right: 20, bottom: 20, left: 20 });

    expect(letter.size).toBe('Letter');
    expect(letter.orientation).toBe('landscape');
    expect(letter.margins).toEqual({ top: 18, right: 16, bottom: 12, left: 14 });
  });

  it('keeps header, footer and page-number settings intact', () => {
    const layout = normalizePageLayout({
      header: { enabled: true, text: '{{DOCUMENT_TITLE}}', firstPageText: 'Cover', align: 'left', distanceMm: 10, differentFirstPage: true },
      footer: { enabled: false, text: '{{CURRENT_DATE}}', align: 'right', distanceMm: 6, differentFirstPage: false },
      pageNumbers: { enabled: true, position: 'top-right', format: 'Page 1' },
    });

    expect(layout.header).toMatchObject({ enabled: true, text: '{{DOCUMENT_TITLE}}', firstPageText: 'Cover', align: 'left', distanceMm: 10, differentFirstPage: true });
    expect(layout.footer).toMatchObject({ enabled: false, text: '{{CURRENT_DATE}}', align: 'right', distanceMm: 6, differentFirstPage: false });
    expect(layout.pageNumbers).toEqual({ enabled: true, position: 'top-right', format: 'Page 1' });
  });

  it('normalizes old document defaults and legacy placeholder formats safely', () => {
    const layout = normalizePageLayout({ header: { text: '{{title}}', spacing: 12, firstPageOnly: true }, pageNumbers: { format: 'Page X of Y' } });
    expect(layout.header.distanceMm).toBe(12);
    expect(layout.header.differentFirstPage).toBe(true);
    expect(layout.pageNumbers.format).toBe('Page 1 of 5');
    expect(renderLayoutText('{{title}} {{date}} {{page}}/{{pages}}', { title: 'Legacy' }, 2, 9)).toContain('Legacy');
  });

  it('returns the expected page dimensions for portrait and landscape choices', () => {
    expect(pageDimensions({ size: 'A4', orientation: 'portrait' })).toEqual({ width: 210, height: 297 });
    expect(pageDimensions({ size: 'A4', orientation: 'landscape' })).toEqual({ width: 297, height: 210 });
    expect(pageDimensions({ size: 'Letter', orientation: 'portrait' })).toEqual({ width: 215.9, height: 279.4 });
    expect(pageDimensions({ size: 'Letter', orientation: 'landscape' })).toEqual({ width: 279.4, height: 215.9 });
  });

  it('inserts and imports page breaks in a Lexical-compatible way', () => {
    const node = createPageBreakNode();
    expect(node.getType()).toBe('page-break');

    const imported = PageBreakNode.importDOM().div(document.createElement('div'));
    expect(imported).toBeNull();

    const marker = document.createElement('div');
    marker.setAttribute('data-lumina-page-break', 'true');
    const importedNode = PageBreakNode.importDOM().div(marker).conversion(marker).node;
    expect(importedNode.getType()).toBe('page-break');
  });

  it('paginates content across pages and honors manual page breaks', () => {
    const body = Array.from({ length: 80 }, (_, index) => `<p>Paragraph ${index + 1} with enough text to force overflow across a few pages.</p>`).join('');
    const html = `${body}<div data-lumina-page-break="true"></div>${body}`;
    const pages = paginateDocumentHtml(html, DEFAULT_PAGE_LAYOUT);
    expect(pages.length).toBeGreaterThan(1);
    expect(pages[0].pageNumber).toBe(1);
    expect(pages[1].pageNumber).toBe(2);
  });

  it('formats page numbering for the supported styles', () => {
    expect(formatPageNumber('Page 1 of 5', 2, 5)).toBe('Page 2 of 5');
    expect(formatPageNumber('Page 1', 2, 5)).toBe('Page 2');
    expect(formatPageNumber('1', 2, 5)).toBe('2');
  });

  it('supports every page-number position', () => {
    PAGE_NUMBER_POSITIONS.forEach((position) => {
      const layout = normalizePageLayout({ pageNumbers: { position } });
      expect(layout.pageNumbers.position).toBe(position);
      expect(layout.pageNumbers.enabled).toBe(position !== 'none');
    });
  });

  it('resolves structured placeholders without mutating stored header/footer content', () => {
    const template = '{{DOCUMENT_TITLE}} · {{CURRENT_DATE}} · {{PAGE_NUMBER}}/{{TOTAL_PAGES}}';
    const rendered = renderLayoutText(template, { title: 'Board Pack' }, 3, 7);
    expect(rendered).toContain('Board Pack');
    expect(rendered).toContain('3/7');
    expect(template).toContain('{{DOCUMENT_TITLE}}');
  });

  it('applies first-page header and footer variations without storing them in body HTML', () => {
    const header = normalizePageLayout({ header: { text: 'Repeated', firstPageText: 'First only', differentFirstPage: true } }).header;
    expect(getPageRegionText(header, { title: 'Doc' }, 1, 2)).toBe('First only');
    expect(getPageRegionText(header, { title: 'Doc' }, 2, 2)).toBe('Repeated');
  });

  it('recalculates pagination capacity after margin changes', () => {
    const compact = pageContentBox({ margins: { top: 10, bottom: 10, left: 10, right: 10 } });
    const wide = pageContentBox({ margins: { top: 50, bottom: 50, left: 10, right: 10 } });
    expect(wide.heightMm).toBeLessThan(compact.heightMm);
  });

  it('builds print/export layout payload with page setup, header, footer and numbering', () => {
    const payload = buildExportLayoutPayload({ size: 'Letter', orientation: 'landscape', margins: { top: 12, right: 13, bottom: 14, left: 15 }, pageNumbers: { position: 'bottom-left', format: 'Page 1 of 5' } });
    expect(payload.page).toMatchObject({ size: 'Letter', orientation: 'landscape', margins: { top: 12, right: 13, bottom: 14, left: 15 } });
    expect(payload.header.text).toBe('{{DOCUMENT_TITLE}}');
    expect(payload.footer.text).toBe('{{CURRENT_DATE}}');
    expect(payload.pageNumbers.position).toBe('bottom-left');
  });

  it('normalizes legacy page-break markup', () => {
    const html = '<div style="break-after:page;page-break-after:always"></div><p>Legacy content</p>';
    const normalized = normalizeLegacyPageBreaks(html);
    expect(normalized).toContain('data-lumina-page-break="true"');
  });

  it('normalizes image assets for document-safe insertion', () => {
    const asset = normalizeImageAsset({ src: 'https://example.com/logo.png', role: 'logo', width: 200, opacity: 2, align: 'unknown' });

    expect(asset.role).toBe('logo');
    expect(asset.width).toBe(100);
    expect(asset.opacity).toBe(5);
    expect(asset.align).toBe('center');
  });

  it('builds accessible, print-stable image figure markup', () => {
    const html = buildImageFigureHtml({ src: 'data:image/png;base64,AAAA', alt: 'Logo', caption: 'Company', role: 'logo', align: 'left', width: 24 });

    expect(html).toContain('data-lumina-image="true"');
    expect(html).toContain('alt="Logo"');
    expect(html).toContain('break-inside:avoid');
    expect(html).toContain('Company');
  });

  it('rejects unsafe image sources during sanitization and extraction', () => {
    const dirty = '<p>Test</p><img src="file:///secret.png" alt="bad"><img src="https://example.com/safe.webp" alt="safe">';

    expect(buildImageFigureHtml({ src: 'javascript:alert(1)' })).toBe('');
    expect(sanitizeEditorHtml(dirty)).not.toContain('file:///secret.png');
    expect(extractDocumentImages(dirty)).toHaveLength(1);
  });

  it('normalizes advanced table dimensions and style defaults', () => {
    const table = normalizeTableModel({ rows: 500, columns: 99, headerRows: 400, style: 'bad', width: 4 });

    expect(table.rows).toBe(100);
    expect(table.columns).toBe(20);
    expect(table.headerRows).toBe(100);
    expect(table.style).toBe('executive');
    expect(table.width).toBe(20);
  });

  it('builds print-ready advanced tables with repeatable headers', () => {
    const html = buildAdvancedTableHtml({ rows: 4, columns: 3, caption: 'Risk matrix', style: 'matrix', firstColumn: true, totalRow: true });

    expect(html).toContain('data-lumina-table="advanced"');
    expect(html).toContain('<caption');
    expect(html).toContain('table-header-group');
    expect(html).toContain('scope="row"');
    expect(summarizeTables(html)).toEqual([{ index: 1, advanced: true, rows: 4, columns: 3 }]);
  });

  it('extracts outlines, previews find-replace, and flags spelling candidates', () => {
    const html = '<h1>Executive Summary</h1><p>The corporate contract has teh typo.</p><h2>Terms</h2>';

    expect(extractDocumentOutline(html).map((item) => item.text)).toEqual(['Executive Summary', 'Terms']);
    expect(findReplacePreview(html, 'corporate').count).toBe(1);
    expect(applyFindReplace(html, 'teh', 'the')).toContain('the typo');
    expect(spellCheckFoundation(html).unknown).toContain('teh');
  });

  it('audits accessibility and performance for production readiness', () => {
    const html = '<h1>Title</h1><h3>Skipped</h3><p>Body</p><img src="https://example.com/logo.png"><table><tr><td>A</td><td>B</td></tr><tr><td>C</td><td>D</td></tr></table>';
    const accessibility = documentAccessibilityAudit(html, { header: { enabled: false }, footer: { enabled: false } });
    const performance = documentPerformanceAudit(html, { pageCount: 2 });

    expect(accessibility.score).toBeLessThan(100);
    expect(accessibility.issues.map((issue) => issue.code)).toEqual(expect.arrayContaining(['image-alt', 'heading-order', 'table-headers']));
    expect(performance.imageCount).toBe(1);
    expect(performance.pageCount).toBe(2);
  });
});
