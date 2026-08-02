import { documentApi, documentStats, summarizeDocument } from './model';

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
  });
});
