const fs = require('fs');
const path = require('path');

describe('Document Studio production safety invariants', () => {
  const source = fs.readFileSync(path.join(__dirname, 'DocumentStudio.jsx'), 'utf8');

  test('exports the persisted current editor state instead of stale document content', () => {
    expect(source).toContain('const contentDirty = editorHtml !== lastSavedHtmlRef.current || layoutDirty;');
    expect(source).toContain('const persisted = contentDirty ? await saveEditor(true) : selected;');
    expect(source).toContain('exportDocumentUrl(persisted.id, formatName)');
  });

  test('design presets save unsaved edits before server-side redesign', () => {
    expect(source).toContain('const saved = await saveEditor(true);');
    expect(source).toContain('if (!saved) return;');
    expect(source).toContain('documentApi.redesign(selected.id, presetId)');
  });

  test('document studio user-facing text contains no known mojibake markers', () => {
    expect(source).not.toMatch(/β€¦|β€”|Γ—|β€|Β·|β’/);
  });
});
