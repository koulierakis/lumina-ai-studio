import {
  buildVirtualizedDocumentWindow,
  documentApi,
  documentStats,
  normalizeDiffRows,
  summarizeDocument,
  summarizeReviewState,
} from './model';

describe('Document Studio model helpers', () => {
  test('summarizes long searchable document text', () => {
    const summary = summarizeDocument({ content_text: 'A'.repeat(260) });

    expect(summary).toHaveLength(221);
    expect(summary.endsWith('…')).toBe(true);
  });

  test('calculates document statistics for versions and exports', () => {
    const stats = documentStats({ content_text: 'one two three four', version_number: 3, export_media_ids: ['pdf', 'docx'] });

    expect(stats).toEqual({ words: 4, versions: 3, exports: 2 });
  });

  test('publishes enterprise lifecycle and folder management API helpers', () => {
    expect(documentApi.renameFolder).toBeInstanceOf(Function);
    expect(documentApi.moveFolder).toBeInstanceOf(Function);
    expect(documentApi.deleteFolder).toBeInstanceOf(Function);
    expect(documentApi.lifecycle).toBeInstanceOf(Function);
    expect(documentApi.collections).toBeInstanceOf(Function);
    expect(documentApi.createCollection).toBeInstanceOf(Function);
    expect(documentApi.batch).toBeInstanceOf(Function);
    expect(documentApi.activity).toBeInstanceOf(Function);
    expect(documentApi.templateLibrary).toBeInstanceOf(Function);
    expect(documentApi.createTemplate).toBeInstanceOf(Function);
    expect(documentApi.mergeTemplate).toBeInstanceOf(Function);
    expect(documentApi.review).toBeInstanceOf(Function);
    expect(documentApi.createReviewItem).toBeInstanceOf(Function);
    expect(documentApi.trackChanges).toBeInstanceOf(Function);
    expect(documentApi.trackChangeAction).toBeInstanceOf(Function);
    expect(documentApi.lock).toBeInstanceOf(Function);
    expect(documentApi.exportJob).toBeInstanceOf(Function);
    expect(documentApi.libraryIndex).toBeInstanceOf(Function);
  });

  test('document filters support archive and trash explorer status values', () => {
    const filters = { status: 'trashed', q: 'kyc' };

    expect(filters.status).toBe('trashed');
    expect(filters.q).toBe('kyc');
  });

  test('summarizes review, lock and track changes state', () => {
    const summary = summarizeReviewState({
      status: 'in_review',
      metadata: {
        review: { status: 'changes_requested', open_count: 2, resolved_count: 1 },
        track_changes: { pending_count: 3, accepted_count: 4, rejected_count: 1 },
        lock: { locked: true, owner: 'reviewer@example.com' },
      },
    });

    expect(summary.reviewStatus).toBe('changes_requested');
    expect(summary.pendingChanges).toBe(3);
    expect(summary.locked).toBe(true);
  });

  test('virtualized document windows and diff rows support large libraries', () => {
    const docs = Array.from({ length: 1000 }, (_, index) => ({ id: String(index) }));
    const window = buildVirtualizedDocumentWindow(docs, 720, 72, 720);
    const rows = normalizeDiffRows({ side_by_side: [{ status: 'inserted' }, { status: 'modified' }] });

    expect(window.items.length).toBeLessThan(30);
    expect(window.start).toBe(5);
    expect(rows.map((row) => row.marker)).toEqual(['+', '~']);
  });
});
