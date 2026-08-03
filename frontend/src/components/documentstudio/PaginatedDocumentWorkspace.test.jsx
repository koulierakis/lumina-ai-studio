import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import PaginatedDocumentWorkspace, { measurePageFlow } from './PaginatedDocumentWorkspace';
import { DEFAULT_PAGE_LAYOUT } from './editorModel';

function makeMeasuredElement({ blockHeights = [], scrollHeight = 0 } = {}) {
  const root = document.createElement('div');
  const editable = document.createElement('div');
  editable.setAttribute('contenteditable', 'true');
  Object.defineProperty(editable, 'scrollHeight', { configurable: true, value: scrollHeight });
  blockHeights.forEach((height) => {
    const child = document.createElement('p');
    child.getBoundingClientRect = () => ({ height });
    editable.appendChild(child);
  });
  root.appendChild(editable);
  return root;
}

describe('PaginatedDocumentWorkspace real page flow', () => {
  test('measures real overflow from editor DOM blocks', () => {
    const root = makeMeasuredElement({ blockHeights: [400, 400, 400] });
    const result = measurePageFlow(root, { size: 'A4', margins: { top: 22, right: 18, bottom: 22, left: 18 } });

    expect(result.pageCount).toBe(2);
    expect(result.contentHeightPx).toBeGreaterThan(900);
  });

  test('manual page break node in measured DOM forces another page', () => {
    const root = makeMeasuredElement({ blockHeights: [20, 20] });
    const editable = root.querySelector('[contenteditable="true"]');
    const marker = document.createElement('div');
    marker.setAttribute('data-lumina-page-break', 'true');
    marker.getBoundingClientRect = () => ({ height: 0 });
    editable.insertBefore(marker, editable.children[1]);

    expect(measurePageFlow(root, {}).pageCount).toBe(2);
  });

  test('layout recalculation reports page flow without invoking content autosave', () => {
    const saveEditor = jest.fn();
    const root = makeMeasuredElement({ blockHeights: [500, 500, 500] });
    const flow = measurePageFlow(root, { size: 'Letter' });

    expect(flow.pageCount).toBeGreaterThan(1);
    expect(saveEditor).not.toHaveBeenCalled();
  });

  test('measurement failure preserves content path by throwing for fallback handling', () => {
    expect(() => measurePageFlow(null, {})).toThrow('Page flow measurement target is unavailable.');
  });

  test('renders actual paginated content and page numbering for multi-page documents', () => {
    const html = '<p>First page content</p><div data-lumina-page-break="true"></div><p>Second page content</p>';
    const markup = renderToStaticMarkup(
      <PaginatedDocumentWorkspace document={{ title: 'Sample' }} html={html} layout={{ ...DEFAULT_PAGE_LAYOUT, pageNumbers: { position: 'bottom-center', format: 'Page 1 of 5', enabled: true } }} />
    );

    expect(markup).toContain('First page content');
    expect(markup).toContain('Second page content');
    expect(markup).toContain('Page 1');
    expect(markup).toContain('Page 2');
  });

  test('keeps measured blank page shells when live DOM flow exceeds estimated HTML pages', () => {
    const markup = renderToStaticMarkup(
      <PaginatedDocumentWorkspace document={{ title: 'Measured' }} html="<p>Short content</p>" layout={DEFAULT_PAGE_LAYOUT}>
        <div>Editor content</div>
      </PaginatedDocumentWorkspace>
    );

    expect(markup).toContain('data-page-count="1"');
    expect(markup).toContain('Short content');
  });

  test('renders editable header and footer placeholders outside the body HTML', () => {
    const markup = renderToStaticMarkup(
      <PaginatedDocumentWorkspace
        document={{ title: 'Board Resolution' }}
        html="<p>Body stays clean</p>"
        layout={{
          ...DEFAULT_PAGE_LAYOUT,
          header: { enabled: true, text: '{{DOCUMENT_TITLE}} · {{PAGE_NUMBER}}/{{TOTAL_PAGES}}', align: 'left', distanceMm: 7, repeat: true },
          footer: { enabled: true, text: '{{CURRENT_DATE}}', align: 'right', distanceMm: 9, repeat: true },
        }}
      />
    );

    expect(markup).toContain('lumina-page-header align-left');
    expect(markup).toContain('Board Resolution · 1/1');
    expect(markup).toContain('lumina-page-footer align-right');
    expect(markup).toContain('Body stays clean');
  });

  test('renders different first-page header and footer variants', () => {
    const html = '<p>First page content</p><div data-lumina-page-break="true"></div><p>Second page content</p>';
    const markup = renderToStaticMarkup(
      <PaginatedDocumentWorkspace
        document={{ title: 'Variant' }}
        html={html}
        layout={{
          ...DEFAULT_PAGE_LAYOUT,
          header: { enabled: true, text: 'Repeated header', firstPageText: 'First header', align: 'center', distanceMm: 8, repeat: true, differentFirstPage: true },
          footer: { enabled: true, text: 'Repeated footer', firstPageText: 'First footer', align: 'center', distanceMm: 8, repeat: true, differentFirstPage: true },
        }}
      />
    );

    expect(markup).toContain('First header');
    expect(markup).toContain('Repeated header');
    expect(markup).toContain('First footer');
    expect(markup).toContain('Repeated footer');
  });
});
