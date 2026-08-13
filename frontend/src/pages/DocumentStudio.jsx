import { useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import {
  Bold, Download, FileText, Italic, List, ListOrdered,
  Redo2, Save, Sparkles, Underline, Undo2, Upload, Wand2,
} from 'lucide-react';
import {
  documentApi, exportDocumentUrl, makeDocumentDownloadHeaders,
} from '../documents/model';
import DocumentRichEditor from '../components/documentstudio/DocumentRichEditor';
import DocumentAIAssistantPanel from '../components/documentstudio/DocumentAIAssistantPanel';
import PaginatedDocumentWorkspace from '../components/documentstudio/PaginatedDocumentWorkspace';
import {
  DEFAULT_PAGE_LAYOUT, buildExportLayoutPayload, normalizePageLayout,
  pageDimensions, sanitizeEditorHtml,
} from '../components/documentstudio/editorModel';

const AUTOSAVE_DELAY_MS = 8000;
const PRESET_BUTTONS = [
  { id: 'luxury-legal', label: 'Luxury Legal' },
  { id: 'executive-corporate', label: 'Executive Corporate' },
  { id: 'banking-professional', label: 'Banking Professional' },
];

function plainTextPreviewHtml(value = '') {
  const escaped = String(value).replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]));
  const paragraphs = escaped.split(/\n\s*\n/).filter(Boolean).map((part) => `<p>${part}</p>`).join('');
  return `<article>${paragraphs || '<p></p>'}</article>`;
}

export default function DocumentStudio() {
  const [documents, setDocuments] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [profile, setProfile] = useState(null);
  const [selected, setSelected] = useState(null);
  const [filters] = useState({ q: '', category: '', tag: '', folder_id: '' });
  const [editorHtml, setEditorHtml] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [statusText, setStatusText] = useState('Ready');
  const [page, setPage] = useState({ zoom: 100 });
  const [pageLayout, setPageLayout] = useState(DEFAULT_PAGE_LAYOUT);
  const [layoutDirty, setLayoutDirty] = useState(false);
  const [printPreview, setPrintPreview] = useState(false);
  const [pageFlow, setPageFlow] = useState({ pageCount: 1, mode: 'paginated', warning: '' });
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [presetLoading, setPresetLoading] = useState(false);
  const [aiPanelOpen, setAIPanelOpen] = useState(false);
  const editorApiRef = useRef(null);
  const editorElementRef = useRef(null);
  const lastSavedHtmlRef = useRef('');
  const saveSequenceRef = useRef(0);
  const autosaveTimerRef = useRef(null);
  const importInputRef = useRef(null);
  const [lexicalEditor, setLexicalEditor] = useState(null);
  const [reviewMode] = useState('editing');
  const normalizedPageLayout = useMemo(() => normalizePageLayout(pageLayout), [pageLayout]);
  useMemo(() => pageDimensions(normalizedPageLayout), [normalizedPageLayout]);

  async function loadAll() {
    setLoading(true);
    try {
      const [templatePayload, profilePayload, docs] = await Promise.all([documentApi.templates(), documentApi.profile(), documentApi.list(filters)]);
      setTemplates(templatePayload.templates || []);
      setProfile(profilePayload);
      setDocuments(docs || []);
      if (docs?.[0]) selectDocument(docs[0], false);
    } catch (error) { toast.error(error.message || 'Document Studio could not load.'); }
    finally { setLoading(false); }
  }
  useEffect(() => { loadAll(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);
  useEffect(() => { lastSavedHtmlRef.current = selected?.content_html || ''; }, [selected?.content_html, selected?.id]);
  useEffect(() => {
    window.clearTimeout(autosaveTimerRef.current);
    const contentDirty = Boolean(selected) && editorHtml !== lastSavedHtmlRef.current;
    if (loading || busy || reviewMode === 'viewing' || (!contentDirty && !layoutDirty)) return undefined;
    autosaveTimerRef.current = window.setTimeout(() => saveEditor(true), AUTOSAVE_DELAY_MS);
    return () => window.clearTimeout(autosaveTimerRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [busy, editorHtml, layoutDirty, loading, reviewMode, selected?.id]);

  async function refreshDocuments(nextFilters = filters) { const docs = await documentApi.list(nextFilters); setDocuments(docs || []); return docs || []; }
  function updatePageLayout(mutator) { setPageLayout((current) => normalizePageLayout(typeof mutator === 'function' ? mutator(current) : mutator)); setLayoutDirty(true); }
  function onEditorChange(nextHtml) { if (reviewMode !== 'viewing' && nextHtml !== editorHtml) setEditorHtml(nextHtml); }
  function format(command) { const editor = editorApiRef.current; if (!editor) return; const text = { bold: 'bold', italic: 'italic', underline: 'underline' }; if (text[command]) editor.formatText(text[command]); else if (command === 'insertUnorderedList') editor.insertList(false); else if (command === 'insertOrderedList') editor.insertList(true); }
  function undoEditor() { editorApiRef.current?.undo(); }
  function redoEditor() { editorApiRef.current?.redo(); }

  async function importWord(event) {
    const file = event.target.files?.[0]; if (!file) return; setBusy(true); setStatusText('Importing Word document…');
    try { const imported = await documentApi.importFile(file, { title: file.name.replace(/\.[^.]+$/, ''), category: 'Imported', tags: 'imported,word' }); selectDocument(imported, false); await refreshDocuments(); toast.success('Word document imported — headings, tables, images and paragraphs preserved.'); }
    catch (error) { toast.error(error.message || 'Import failed.'); }
    finally { setBusy(false); setStatusText('Ready'); event.target.value = ''; }
  }

  async function createBlankDocument() {
    setBusy(true);
    try { const created = await documentApi.create({ title: 'Untitled Document', category: 'Corporate', tags: ['draft'], content_html: '<p></p>', content_text: '', design: { pageLayout: normalizedPageLayout }, metadata: { page_layout: normalizedPageLayout } }); selectDocument(created, false); await refreshDocuments(); toast.success('New document created.'); }
    catch (error) { toast.error(error.message || 'Document creation failed.'); }
    finally { setBusy(false); }
  }

  async function saveEditor(autosave = false) {
    if (!selected) return; const saveSequence = ++saveSequenceRef.current; const htmlAtSave = editorHtml; const layoutAtSave = normalizedPageLayout; setBusy(true); setStatusText(autosave ? 'Autosaving…' : 'Saving…');
    try {
      if (autosave && htmlAtSave === lastSavedHtmlRef.current && !layoutDirty) { setStatusText('Ready'); return; }
      const contentText = htmlAtSave.replace(/<[^>]+>/g, ' '); const exportLayout = buildExportLayoutPayload(layoutAtSave);
      const updated = await documentApi.update(selected.id, { content_html: htmlAtSave, content_text: contentText, design: { ...(selected.design || {}), pageLayout: layoutAtSave, exportLayout }, metadata: { ...(selected.metadata || {}), page_layout: layoutAtSave, export_layout: exportLayout, page_count: pageFlow.pageCount }, expected_version: selected.version_number, autosave, change_note: autosave ? 'Autosave' : 'Manual save' });
      if (saveSequence !== saveSequenceRef.current) return; selectDocument(updated, false); await refreshDocuments(); if (!autosave) toast.success('Document saved.');
    } catch (error) { toast.error(error.message || 'Save failed.'); }
    finally { setBusy(false); setStatusText('Ready'); }
  }

  async function applyPreset(presetId) {
    if (!selected) return; setPresetLoading(true); setStatusText(`Applying ${presetId}…`);
    try { const updated = await documentApi.redesign(selected.id, presetId); selectDocument(updated, false); await refreshDocuments(); toast.success(`${PRESET_BUTTONS.find((p) => p.id === presetId)?.label || presetId} applied — text preserved.`); }
    catch (error) { toast.error(error.message || 'Preset application failed.'); }
    finally { setPresetLoading(false); setStatusText('Ready'); }
  }

  async function exportDocument(formatName) {
    if (!selected) return; setBusy(true); setStatusText(`Exporting ${formatName.toUpperCase()}…`);
    try { const response = await fetch(exportDocumentUrl(selected.id, formatName), { headers: makeDocumentDownloadHeaders() }); if (!response.ok) throw new Error(`${formatName.toUpperCase()} export failed with status ${response.status}`); const blob = await response.blob(); const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = `${selected.title}.${formatName}`; link.click(); URL.revokeObjectURL(url); toast.success(`${formatName.toUpperCase()} exported.`); }
    catch (error) { toast.error(error.message || `${formatName.toUpperCase()} export failed.`); }
    finally { setBusy(false); setStatusText('Ready'); }
  }

  function selectDocument(document, closeLibrary = true) { setSelected(document); setEditorHtml(document.content_html || ''); lastSavedHtmlRef.current = document.content_html || ''; setPageLayout(normalizePageLayout(document.design?.pageLayout || document.metadata?.page_layout)); setLayoutDirty(false); if (closeLibrary) setLibraryOpen(false); }
  function applyAIPreview(preview) { const source = preview?.document || {}; const nextHtml = source.content_html ? sanitizeEditorHtml(source.content_html) : sanitizeEditorHtml(plainTextPreviewHtml(source.content || source.content_text || '')); if (!nextHtml || nextHtml === '<article><p></p></article>') { toast.error('This preview does not contain editable document content.'); return; } setEditorHtml(nextHtml); setStatusText('AI preview applied locally — save to persist'); toast.success('Preview applied to the editor. Save when you are ready.'); }
  async function handleAIDocumentSaved(created, pack = null) { await refreshDocuments(); if (created) selectDocument(created, false); toast.success(pack?.length ? `${pack.length} AI documents saved to the library.` : 'AI document saved to the library.'); }

  return (
    <div className="doc-studio-shell">
      <header className="doc-topbar"><div className="doc-brand"><FileText size={22} /><span>Lumina Document Studio</span></div><div className="doc-title-area"><input className="doc-title-input" aria-label="Document title" key={selected?.id || 'untitled'} defaultValue={selected?.title || 'Untitled Document'} disabled={!selected} onBlur={(e) => { if (selected && e.target.value.trim() !== selected.title) documentApi.update(selected.id, { title: e.target.value.trim() }).then((updated) => { setSelected(updated); refreshDocuments(); toast.success('Renamed.'); }).catch(() => toast.error('Rename failed.')); }} /><span className="doc-save-indicator"><i className={busy ? 'is-busy' : ''} />{busy ? statusText : 'Saved'}</span></div><div className="doc-topbar-actions"><button className="doc-btn doc-btn-import" onClick={() => importInputRef.current?.click()} disabled={busy}><Upload size={18} />Import Word</button><input ref={importInputRef} type="file" className="hidden" accept=".docx" onChange={importWord} /><button className="doc-btn doc-btn-export doc-btn-pdf" onClick={() => exportDocument('pdf')} disabled={!selected || busy}><Download size={18} />Export PDF</button><button className="doc-btn doc-btn-export doc-btn-word" onClick={() => exportDocument('docx')} disabled={!selected || busy}><Download size={18} />Export Word</button></div></header>
      <div className="doc-toolbar"><div className="doc-toolbar-group"><button className="doc-tool-btn" onClick={createBlankDocument} disabled={busy}><FileText size={16} /><span>New</span></button><button className="doc-tool-btn" onClick={() => saveEditor(false)} disabled={!selected || busy}><Save size={16} /><span>Save</span></button></div><div className="doc-toolbar-divider" /><div className="doc-toolbar-group"><button className="doc-tool-btn" onClick={undoEditor} disabled={!selected || busy}><Undo2 size={16} /></button><button className="doc-tool-btn" onClick={redoEditor} disabled={!selected || busy}><Redo2 size={16} /></button></div><div className="doc-toolbar-divider" /><div className="doc-toolbar-group"><button className="doc-tool-btn" onClick={() => format('bold')} disabled={!selected || busy}><Bold size={16} /></button><button className="doc-tool-btn" onClick={() => format('italic')} disabled={!selected || busy}><Italic size={16} /></button><button className="doc-tool-btn" onClick={() => format('underline')} disabled={!selected || busy}><Underline size={16} /></button></div><div className="doc-toolbar-divider" /><div className="doc-toolbar-group"><button className="doc-tool-btn" onClick={() => format('insertUnorderedList')} disabled={!selected || busy}><List size={16} /></button><button className="doc-tool-btn" onClick={() => format('insertOrderedList')} disabled={!selected || busy}><ListOrdered size={16} /></button></div><div className="doc-toolbar-divider" /><div className="doc-toolbar-group"><select className="doc-page-size" value={normalizedPageLayout.size} onChange={(e) => updatePageLayout((c) => ({ ...c, size: e.target.value }))}><option value="A4">A4</option><option value="Letter">Letter</option></select><select className="doc-page-orient" value={normalizedPageLayout.orientation} onChange={(e) => updatePageLayout((c) => ({ ...c, orientation: e.target.value }))}><option value="portrait">Portrait</option><option value="landscape">Landscape</option></select></div><div className="doc-toolbar-divider" /><div className="doc-toolbar-group"><button className="doc-tool-btn" onClick={() => setPrintPreview((v) => !v)} disabled={!selected}>{printPreview ? 'Edit' : 'Preview'}</button><button className="doc-tool-btn" onClick={() => setLibraryOpen((v) => !v)}>Library</button><button className={`doc-tool-btn ${aiPanelOpen ? 'is-active' : ''}`} onClick={() => setAIPanelOpen((value) => !value)}><Sparkles size={16} />AI Assist</button></div></div>
      <div className="doc-presets-bar"><span className="doc-presets-label">Design:</span>{PRESET_BUTTONS.map((preset) => <button key={preset.id} className="doc-preset-btn" onClick={() => applyPreset(preset.id)} disabled={!selected || busy || presetLoading}><Wand2 size={16} />{preset.label}</button>)}</div>
      {aiPanelOpen && <DocumentAIAssistantPanel profileId={profile?.id} onApplyPreview={applyAIPreview} onDocumentSaved={handleAIDocumentSaved} onClose={() => setAIPanelOpen(false)} />}
      {libraryOpen && <div className="doc-library-panel"><div className="doc-library-header"><span>Document Library</span><button onClick={() => setLibraryOpen(false)}>×</button></div><div className="doc-library-list">{documents.length === 0 && <div className="doc-library-empty">No documents yet. Import a Word file or create a new document.</div>}{documents.map((doc) => <button key={doc.id} className={`doc-library-item ${selected?.id === doc.id ? 'is-selected' : ''}`} onClick={() => selectDocument(doc)}><FileText size={16} /><span>{doc.title}</span></button>)}</div></div>}
      <div className="doc-workspace">{printPreview ? <div className="doc-preview-container"><PaginatedDocumentWorkspace document={selected} html={editorHtml} layout={normalizedPageLayout} zoom={Math.min(page.zoom, 80)} preview /></div> : <div className="doc-editor-container"><PaginatedDocumentWorkspace document={selected} html={editorHtml} layout={normalizedPageLayout} zoom={page.zoom} editor={lexicalEditor} editorElementRef={editorElementRef} onPageFlowChange={setPageFlow}><div className="lumina-document lumina-editor-page" style={{ color: '#111827', fontFamily: 'Georgia, serif', fontSize: '14px', lineHeight: 1.7 }}><DocumentRichEditor ref={editorApiRef} html={editorHtml} onHtmlChange={onEditorChange} disabled={busy || !selected} onEditorReady={setLexicalEditor} /></div></PaginatedDocumentWorkspace></div>}</div>
      <footer className="doc-statusbar"><span>Page 1 of {pageFlow.pageCount}</span><span>{(editorHtml || '').replace(/<[^>]+>/g, ' ').trim().split(/\s+/).filter(Boolean).length} words</span><span>{normalizedPageLayout.size} · {normalizedPageLayout.orientation}</span><span>{busy ? statusText : 'Ready'}</span><div className="doc-zoom"><button onClick={() => setPage((p) => ({ ...p, zoom: Math.max(60, p.zoom - 10) }))}>−</button><span>{page.zoom}%</span><button onClick={() => setPage((p) => ({ ...p, zoom: Math.min(150, p.zoom + 10) }))}>+</button></div></footer>
    </div>
  );
}
