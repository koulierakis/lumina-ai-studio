import { sanitizeEditorHtml } from './editorModel';

describe('DocumentRichEditor production foundation', () => {
  test('sanitizes dangerous pasted html while preserving safe formatting', () => {
    const html = sanitizeEditorHtml('<h1 onclick="alert(1)">Title</h1><script>alert(1)</script><p><strong>Body</strong></p><a href="javascript:evil()">bad</a>');

    expect(html).toContain('<h1>Title</h1>');
    expect(html).toContain('<strong>Body</strong>');
    expect(html).not.toContain('<script>');
    expect(html).not.toContain('onclick');
    expect(html).not.toContain('javascript:');
  });
});
