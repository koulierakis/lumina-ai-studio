import {
  PROFESSIONAL_TEMPLATE_CATALOG,
  buildMergeFieldChip,
  buildProfessionalTemplateDraft,
  buildTrackChangePreview,
  buildVirtualizedDocumentWindow,
  documentApi,
  documentStats,
  extractMergeFields,
  filterProfessionalTemplates,
  flattenMergeVariables,
  groupReviewThreads,
  normalizeReviewAction,
  normalizeDiffRows,
  summarizeDocument,
  summarizeReviewState,
  summarizeVersionHistory,
  validateMergeFields,
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

  test('normalizes review actions, groups threads and summarizes versions', () => {
    const threads = groupReviewThreads([
      { id: 'c1', thread_id: 't1', kind: 'suggestion', status: 'open', body: 'Replace term', updated_at: '2026-08-03T10:00:00Z' },
      { id: 'c2', thread_id: 't1', parent_id: 'c1', status: 'resolved', body: 'Done', created_at: '2026-08-03T10:01:00Z' },
      { id: 'c3', thread_id: 't2', status: 'accepted', body: 'Accepted', updated_at: '2026-08-03T11:00:00Z' },
    ]);
    const summary = summarizeVersionHistory([
      { id: 'v1', version_number: 1, change_note: 'Autosave' },
      { id: 'v2', version_number: 2, change_note: 'Manual editor save' },
    ]);

    expect(normalizeReviewAction('accept')).toBe('accept-suggestion');
    expect(normalizeReviewAction('reject')).toBe('reject-suggestion');
    expect(threads[0].id).toBe('t2');
    expect(threads.find((thread) => thread.id === 't1').replies).toHaveLength(1);
    expect(buildTrackChangePreview({ type: 'replacement', before: 'Beta', after: 'Delta' })).toBe('replacement: Beta → Delta');
    expect(summary.latest.id).toBe('v2');
    expect(summary.named).toBe(1);
  });

  test('virtualized document windows and diff rows support large libraries', () => {
    const docs = Array.from({ length: 1000 }, (_, index) => ({ id: String(index) }));
    const window = buildVirtualizedDocumentWindow(docs, 720, 72, 720);
    const rows = normalizeDiffRows({ side_by_side: [{ status: 'inserted' }, { status: 'modified' }] });

    expect(window.items.length).toBeLessThan(30);
    expect(window.start).toBe(5);
    expect(rows.map((row) => row.marker)).toEqual(['+', '~']);
  });

  test('professional template catalog can be filtered and converted to merge-ready drafts', () => {
    const banking = filterProfessionalTemplates(PROFESSIONAL_TEMPLATE_CATALOG, { q: 'kyc', category: 'Banking' });
    const draft = buildProfessionalTemplateDraft(banking[0]);

    expect(banking).toHaveLength(1);
    expect(draft.tags).toContain('professional');
    expect(draft.content_html).toContain('{{title}}');
    expect(draft.merge_schema.required).toContain('company.name');
    expect(draft.metadata.professional).toBe(true);
  });

  test('variables and merge fields report missing data deterministically', () => {
    const html = '<h1>{{title}}</h1><p>{{company.name}}</p><p>{{ signer }}</p>';
    const variables = { title: 'Board Pack', company: { name: 'Lumina' } };
    const diagnostics = validateMergeFields(html, variables, ['date']);

    expect(extractMergeFields(html)).toEqual(['company.name', 'signer', 'title']);
    expect(flattenMergeVariables(variables)).toEqual({ title: 'Board Pack', 'company.name': 'Lumina' });
    expect(diagnostics.valid).toBe(false);
    expect(diagnostics.missing).toEqual(['date', 'signer']);
    expect(buildMergeFieldChip(' company.name! ')).toBe('{{company.name}}');
  });
});
