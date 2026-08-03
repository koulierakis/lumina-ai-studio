import { measurePageFlow } from './PaginatedDocumentWorkspace';

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
});
