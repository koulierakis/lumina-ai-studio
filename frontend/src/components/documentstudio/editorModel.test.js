import {
  DEFAULT_PAGE_LAYOUT,
  PageBreakNode,
  createPageBreakNode,
  formatPageNumber,
  normalizeLegacyPageBreaks,
  normalizePageLayout,
  pageDimensions,
  paginateDocumentHtml,
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
      header: { enabled: true, text: '{{title}}', spacing: 10, firstPageOnly: true },
      footer: { enabled: false, text: '{{date}}', spacing: 6, firstPageOnly: false },
      pageNumbers: { enabled: true, position: 'top-right', format: 'Page X' },
    });

    expect(layout.header).toEqual({ enabled: true, text: '{{title}}', spacing: 10, firstPageOnly: true });
    expect(layout.footer).toEqual({ enabled: false, text: '{{date}}', spacing: 6, firstPageOnly: false });
    expect(layout.pageNumbers).toEqual({ enabled: true, position: 'top-right', format: 'Page X' });
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
    expect(formatPageNumber('Page X of Y', 2, 5)).toBe('Page 2 of 5');
    expect(formatPageNumber('Page X', 2, 5)).toBe('Page 2');
    expect(formatPageNumber('X', 2, 5)).toBe('2');
  });

  it('normalizes legacy page-break markup', () => {
    const html = '<div style="break-after:page;page-break-after:always"></div><p>Legacy content</p>';
    const normalized = normalizeLegacyPageBreaks(html);
    expect(normalized).toContain('data-lumina-page-break="true"');
  });
});
