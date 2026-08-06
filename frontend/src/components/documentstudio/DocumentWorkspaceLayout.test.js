import fs from 'fs';
import path from 'path';

const read = (name) => fs.readFileSync(path.join(__dirname, name), 'utf8');

describe('Document Studio simplified workspace regression', () => {
  const page = read('../../pages/DocumentStudio.jsx');
  const pagination = read('PaginatedDocumentWorkspace.jsx');
  const css = read('../../index.css');

  test('renders a single centered editable canvas as the primary surface', () => {
    expect(page).toContain('<DocumentRichEditor');
    expect(page).toContain('<PaginatedDocumentWorkspace');
    expect(pagination).toContain('lumina-print-page');
    expect(page).toContain('doc-editor-container');
    expect(css).toContain('.doc-editor-container');
    expect(css).toContain('.doc-workspace');
  });

  test('provides a prominent Import Word button', () => {
    expect(page).toContain('Import Word');
    expect(page).toContain('accept=".docx"');
    expect(page).toContain('importWord');
    expect(page).toContain('doc-btn-import');
  });

  test('provides three luxury design preset buttons without dropdowns', () => {
    expect(page).toContain('luxury-legal');
    expect(page).toContain('executive-corporate');
    expect(page).toContain('banking-professional');
    expect(page).toContain('Luxury Legal');
    expect(page).toContain('Executive Corporate');
    expect(page).toContain('Banking Professional');
    expect(page).toContain('doc-preset-btn');
    expect(page).not.toContain('selectedPresetId');
    // Presets are buttons, not a dropdown select
    expect(page).not.toContain('selectedPresetId');
  });

  test('provides large Export PDF and Export Word buttons', () => {
    expect(page).toContain('Export PDF');
    expect(page).toContain('Export Word');
    expect(page).toContain("exportDocument('pdf')");
    expect(page).toContain("exportDocument('docx')");
    expect(page).toContain('doc-btn-pdf');
    expect(page).toContain('doc-btn-word');
  });

  test('uses a single workspace without a permanent preview split panel', () => {
    expect(page).not.toContain('PanelGroup');
    expect(page).not.toContain('ResizablePanel');
    expect(page).not.toContain('PanelResizeHandle');
    expect(page).not.toContain('rightPanelCollapsed');
    expect(page).not.toContain('rightPanelMode');
    expect(page).not.toContain('document-workspace-divider');
  });

  test('does not include comments, collaboration, OCR, AI rewrite, or presentation mode', () => {
    expect(page).not.toContain('addComment');
    expect(page).not.toContain('reviewState');
    expect(page).not.toContain('trackState');
    expect(page).not.toContain('reviewDraft');
    expect(page).not.toContain('DocumentContextInspector');
    expect(page).not.toContain('DocumentOfficeChrome');
    expect(page).not.toContain('DocumentNavigator');
    expect(page).not.toContain('DocumentStudioSidebar');
    expect(page).not.toContain('operate(');
    expect(page).not.toContain('runAnalysis');
    expect(page).not.toContain('Presentation Preview');
    expect(page).not.toContain('Auto Redesign');
  });

  test('status bar remains functional with page count, word count, and zoom', () => {
    expect(page).toContain('doc-statusbar');
    expect(page).toContain('pageFlow.pageCount');
    expect(page).toContain('words');
    expect(page).toContain('page.zoom');
    expect(css).toContain('.doc-statusbar');
    expect(css).toContain('.doc-zoom');
  });

  test('no viewport clipping classes are used', () => {
    const classTokens = [...page.matchAll(/className="([^"]*)"/g)].flatMap(match => match[1].split(/\s+/));
    expect(classTokens).not.toContain('h-screen');
    expect(classTokens).not.toContain('overflow-hidden');
  });

  test('CSS provides 125-135% visual scale with larger UI elements', () => {
    expect(css).toContain('.doc-topbar');
    expect(css).toContain('height: 60px');
    expect(css).toContain('.doc-toolbar');
    expect(css).toContain('height: 52px');
    expect(css).toContain('.doc-btn');
    expect(css).toContain('height: 42px');
    expect(css).toContain('font-size: 15px');
    expect(css).toContain('.doc-preset-btn');
    expect(css).toContain('height: 40px');
  });
});