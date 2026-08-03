import {
  DEFAULT_PAGE_LAYOUT,
  PAGE_NUMBER_POSITIONS,
  PageBreakNode,
  buildExportLayoutPayload,
  createPageBreakNode,
  formatPageNumber,
  getPageRegionText,
  normalizeLegacyPageBreaks,
  normalizePageLayout,
  pageDimensions,
  pageContentBox,
  paginateDocumentHtml,
  renderLayoutText,
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
});
