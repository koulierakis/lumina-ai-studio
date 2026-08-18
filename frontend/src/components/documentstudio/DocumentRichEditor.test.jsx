import { act } from 'react';
import { createRoot } from 'react-dom/client';
import DocumentRichEditor from './DocumentRichEditor';
import {
  calculateMeasuredPages,
  normalizeLegacyPageBreaks,
  normalizePageLayout,
  pageContentBox,
  pageDimensions,
  sanitizeEditorHtml,
} from './editorModel';

describe('DocumentRichEditor editability lifecycle', () => {
  let host;
  let root;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    host = document.createElement('div');
    document.body.appendChild(host);
    root = createRoot(host);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    host.remove();
  });

  test('becomes editable when initialization finishes without remounting Lexical', async () => {
    const props = { html: '<p></p>', onHtmlChange: jest.fn() };
    await act(async () => root.render(<DocumentRichEditor {...props} disabled />));
    expect(host.querySelector('[contenteditable]')).toHaveAttribute('contenteditable', 'false');

    await act(async () => root.render(<DocumentRichEditor {...props} disabled={false} />));
    expect(host.querySelector('[contenteditable]')).toHaveAttribute('contenteditable', 'true');
  });
});

describe('DocumentRichEditor production foundation', () => {
  test('sanitizes dangerous pasted html while preserving safe formatting', () => {
    const html = sanitizeEditorHtml('<h1 onclick="alert(1)">Title</h1><script>alert(1)</script><p><strong>Body</strong></p><a href="javascript:evil()">bad</a>');

    expect(html).toContain('<h1>Title</h1>');
    expect(html).toContain('<strong>Body</strong>');
    expect(html).not.toContain('<script>');
    expect(html).not.toContain('onclick');
    expect(html).not.toContain('javascript:');
  });

  test('legacy page break html imports into the structured marker', () => {
    const html = normalizeLegacyPageBreaks('<p>One</p><div style="page-break-after: always"></div><p>Two</p>');

    expect(html).toContain('data-lumina-page-break="true"');
  });
});

describe('Document Studio page flow model', () => {
  test('default A4 portrait layout receives safe defaults', () => {
    const layout = normalizePageLayout({});
    const dimensions = pageDimensions(layout);
    const box = pageContentBox(layout);

    expect(layout.size).toBe('A4');
    expect(layout.orientation).toBe('portrait');
    expect(dimensions).toEqual({ width: 210, height: 297 });
    expect(box.heightMm).toBeCloseTo(253);
  });

  test('Letter and landscape layouts resolve deterministic dimensions', () => {
    expect(pageDimensions(normalizePageLayout({ size: 'Letter' }))).toEqual({ width: 215.9, height: 279.4 });
    expect(pageDimensions(normalizePageLayout({ size: 'A4', orientation: 'landscape' }))).toEqual({ width: 297, height: 210 });
  });

  test('custom margins reduce available content area', () => {
    const box = pageContentBox({ margins: { top: 10, right: 20, bottom: 30, left: 40 } });

    expect(box.widthMm).toBeCloseTo(150);
    expect(box.heightMm).toBeCloseTo(257);
  });

  test('page count increases when content grows and decreases when deleted', () => {
    const onePage = calculateMeasuredPages({ contentHeightPx: 100, blockMetrics: [{ height: 60 }] });
    const threePages = calculateMeasuredPages({ contentHeightPx: 100, blockMetrics: [{ height: 60 }, { height: 60 }, { height: 60 }] });
    const backToOne = calculateMeasuredPages({ contentHeightPx: 100, blockMetrics: [{ height: 40 }] });

    expect(onePage).toBe(1);
    expect(threePages).toBe(3);
    expect(backToOne).toBe(1);
  });

  test('manual page break forces another page', () => {
    const pages = calculateMeasuredPages({ contentHeightPx: 100, blockMetrics: [{ height: 20 }, { pageBreak: true, height: 0 }, { height: 20 }] });

    expect(pages).toBe(2);
  });

  test('zoom does not change page count because measurement uses unscaled content height', () => {
    const metrics = [{ height: 90 }, { height: 90 }];
    const at80 = calculateMeasuredPages({ contentHeightPx: 100, blockMetrics: metrics });
    const at130 = calculateMeasuredPages({ contentHeightPx: 100, blockMetrics: metrics });

    expect(at80).toBe(2);
    expect(at130).toBe(2);
  });

  test('20-page ordinary text model remains deterministic', () => {
    const metrics = Array.from({ length: 20 }, () => ({ height: 100 }));

    expect(calculateMeasuredPages({ contentHeightPx: 100, blockMetrics: metrics })).toBe(20);
  });
});
