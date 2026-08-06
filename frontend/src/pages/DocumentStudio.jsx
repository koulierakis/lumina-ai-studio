import { useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import { Download, FileText, Heart, History, PanelRightClose, PanelRightOpen, ShieldCheck, Sparkles, Upload, Wand2, X } from 'lucide-react';
import { PanelGroup, Panel as ResizablePanel, PanelResizeHandle } from 'react-resizable-panels';
import { DOCUMENT_CREATION_MODES, DOCUMENT_TYPES, EXPORT_FORMATS, PROFESSIONAL_TEMPLATE_CATALOG, buildMergeFieldChip, buildProfessionalTemplateDraft, buildTrackChangePreview, documentApi, documentStats, exportDocumentUrl, filterProfessionalTemplates, groupReviewThreads, makeDocumentDownloadHeaders, normalizeReviewAction, summarizeDocument, summarizeVersionHistory, validateMergeFields } from '../documents/model';

import DocumentRichEditor from "../components/documentstudio/DocumentRichEditor";
import PaginatedDocumentWorkspace from "../components/documentstudio/PaginatedDocumentWorkspace";
import DocumentStudioSidebar from "../components/documentstudio/DocumentStudioSidebar";
import DocumentOfficeChrome from "../components/documentstudio/DocumentOfficeChrome";
import DocumentNavigator from "../components/documentstudio/DocumentNavigator";
import DocumentContextInspector from "../components/documentstudio/DocumentContextInspector";
import { DEFAULT_PAGE_LAYOUT, PAGE_NUMBER_FORMATS, PAGE_NUMBER_POSITIONS, applyFindReplace, buildAdvancedTableHtml, buildExportLayoutPayload, buildImageFigureHtml, documentAccessibilityAudit, documentPerformanceAudit, extractDocumentImages, extractDocumentOutline, findReplacePreview, normalizeImageAsset, normalizePageLayout, pageDimensions, sanitizeEditorHtml, spellCheckFoundation, summarizeTables } from "../components/documentstudio/editorModel";
import {
  DOCUMENT_PROFILE_IDS,
  getDocumentProfileOptions,
  getDocumentThemeOptions,
  getTypographyPresetOptions,
  getLayoutPresetOptions,
  createDesignConfiguration,
  createDesignCssVariables,
  resolvePageDimensions,
} from "../documents/design";
const initialFilters = { q: '', category: '', tag: '', folder_id: '' };
const AUTOSAVE_DELAY_MS = 8000;
const defaultGenerator = {
  template_id: 'premium-agreement',
  title: 'Premium Corporate Services Agreement',
  parties: ['Lumina Corporate Holdings', 'Strategic Counterparty Ltd.'],
  jurisdiction: 'England and Wales',
  effective_date: new Date().toISOString().slice(0, 10),
  fields: { subject: 'strategic advisory, technology implementation and managed corporate services', term: 'twenty-four months', governing_law: 'England and Wales' },
  prompt: 'Draft an executive-quality international corporate services agreement with definitions, compliance wording, annexes, signature blocks and premium formatting.',
  creation_mode: 'template',
  tags: ['premium', 'agreement', 'corporate'],
};

const defaultImageDraft = {
  src: '',
  alt: 'Corporate brand image',
  caption: '',
  width: 38,
  align: 'center',
  shape: 'rounded',
  role: 'image',
  opacity: 100,
  border: true,
  shadow: false,
  link: '',
};

const defaultTableDraft = {
  rows: 4,
  columns: 4,
  headerRows: 1,
  caption: 'Executive decision matrix',
  style: 'executive',
  width: 100,
  repeatHeader: true,
  bandedRows: true,
  totalRow: false,
  firstColumn: true,
};

export default function DocumentStudio() {
  const [documents, setDocuments] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [templateLibrary, setTemplateLibrary] = useState([]);
  const [templateDraft, setTemplateDraft] = useState({ name: 'Banking Certificate Template', category: 'Banking', tags: ['banking', 'kyc'], content_html: '<article><h1>{{title}}</h1><p>{{company.name}}</p>{{#if signer}}<p>Signer: {{signer}}</p>{{/if}}{{#each items}}<p>{{item.name}} · {{item.amount|currency}}</p>{{/each}}</article>', merge_schema: { required: ['title', 'company.name'] } });
  const [templateFilters, setTemplateFilters] = useState({ q: '', category: '' });
  const [mergeVariables, setMergeVariables] = useState('{"title":"Certificate of Authority","company":{"name":"JSA GLOBAL PARTNERS LLC"},"signer":"GIANNIS KOULIERAKIS","items":[{"name":"Service Fee","amount":12500}]}');
  const [mergePreview, setMergePreview] = useState(null);
  const [companies, setCompanies] = useState([]);
  const [people, setPeople] = useState([]);
  const [banks, setBanks] = useState([]);
  const [clauses, setClauses] = useState([]);
  const [folders, setFolders] = useState([]);
  const [collections, setCollections] = useState([]);
  const [selectedIds, setSelectedIds] = useState([]);
  const [profile, setProfile] = useState(null);
  const [selected, setSelected] = useState(null);
  const [versions, setVersions] = useState([]);
  const [activity, setActivity] = useState([]);
  const [analysis, setAnalysis] = useState(null);
  const [quality, setQuality] = useState(null);
  const [compareResult, setCompareResult] = useState(null);
  const [filters, setFilters] = useState(initialFilters);
  const [generator, setGenerator] = useState(defaultGenerator);
  const [editorHtml, setEditorHtml] = useState('');
  const [newDocumentTitle, setNewDocumentTitle] = useState('Executive Letterhead Document');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [designPresets, setDesignPresets] = useState([]);
  const [selectedPresetId, setSelectedPresetId] = useState('');
  const [presetLoading, setPresetLoading] = useState(false);
  const [presetMessage, setPresetMessage] = useState('');
  const [statusText, setStatusText] = useState('Ready');
  const [intelligencePreview, setIntelligencePreview] = useState(null);
  const [outlineMode, setOutlineMode] = useState('page');
  const [page, setPage] = useState({ size: 'A4', orientation: 'portrait', zoom: 90, margin: 22, lineHeight: 1.55 });
  const [pageLayout, setPageLayout] = useState(DEFAULT_PAGE_LAYOUT);
  const [printPreview, setPrintPreview] = useState(false);
  const [layoutWarning, setLayoutWarning] = useState('');
  const [layoutDirty, setLayoutDirty] = useState(false);
  const [imageDraft, setImageDraft] = useState(defaultImageDraft);
  const [tableDraft, setTableDraft] = useState(defaultTableDraft);
  const [findReplace, setFindReplace] = useState({ find: '', replace: '' });
  const imageInputRef = useRef(null);
  const saveSequenceRef = useRef(0);
  const autosaveTimerRef = useRef(null);

  const [luxuryDesigner, setLuxuryDesigner] = useState({
    profileId: DOCUMENT_PROFILE_IDS.BANK_OF_CYPRUS,
    themeId: 'banking-blue',
    typographyPresetId: 'banking',
    layoutPresetId: 'banking',
  });
  const [comments, setComments] = useState([]);
  const [reviewState, setReviewState] = useState({ comments: [], markers: [], open_count: 0, resolved_count: 0, status: 'draft' });
  const [trackState, setTrackState] = useState({ changes: [], pending_count: 0, accepted_count: 0, rejected_count: 0 });
  const [reviewDraft, setReviewDraft] = useState({ kind: 'comment', body: '', suggestion: '' });
  const [reviewMode, setReviewMode] = useState('editing');
  const [history, setHistory] = useState({ past: [], future: [] });
  const editorApiRef = useRef(null);
  const editorElementRef = useRef(null);
  const lastSavedHtmlRef = useRef('');
  const [lexicalEditor, setLexicalEditor] = useState(null);
  const [pageFlow, setPageFlow] = useState({ pageCount: 1, mode: 'paginated', warning: '' });
  const [ribbonTab, setRibbonTab] = useState('Home');
  const [navigatorTab, setNavigatorTab] = useState('Pages');
  const [navigatorCollapsed, setNavigatorCollapsed] = useState(false);
  const [rightPanelCollapsed, setRightPanelCollapsed] = useState(false);
  const [rightPanelMode, setRightPanelMode] = useState('preview');
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [toolCenterOpen, setToolCenterOpen] = useState(false);
  const [selectionContext, setSelectionContext] = useState('document');

  const categories = useMemo(() => [...new Set(templates.map((item) => item.category))], [templates]);
  const professionalTemplateMatches = useMemo(() => filterProfessionalTemplates(PROFESSIONAL_TEMPLATE_CATALOG, templateFilters), [templateFilters]);
  const mergeDiagnostics = useMemo(() => {
    try {
      return validateMergeFields(templateDraft.content_html, JSON.parse(mergeVariables || '{}'), templateDraft.merge_schema?.required || []);
    } catch (_) {
      return { valid: false, fields: [], required: [], missing: ['Invalid JSON'], available: [] };
    }
  }, [mergeVariables, templateDraft.content_html, templateDraft.merge_schema]);

  const luxuryDesign = useMemo(
    () =>
      createDesignConfiguration({
        profileId: luxuryDesigner.profileId,
        themeId: luxuryDesigner.themeId,
        typographyPresetId: luxuryDesigner.typographyPresetId,
        layoutPresetId: luxuryDesigner.layoutPresetId,
        branding: {
          companyName: profile?.company_name || '',
          legalName: profile?.company_name || '',
          primaryColor: profile?.primary_color || undefined,
          secondaryColor: profile?.secondary_color || undefined,
          accentColor: profile?.accent_color || undefined,
          logoUrl: profile?.logo_url || '',
          sealUrl: profile?.seal_url || '',
          signatureUrl: profile?.signature_url || '',
          confidentialLabel:
            luxuryDesigner.profileId === DOCUMENT_PROFILE_IDS.BANK_OF_CYPRUS
              ? 'CONFIDENTIAL - BANKING / KYC / COMPLIANCE REVIEW'
              : 'CONFIDENTIAL',
        },
        language:
          luxuryDesigner.profileId === DOCUMENT_PROFILE_IDS.GREEK_IKE
            ? 'el'
            : 'en',
        country:
          luxuryDesigner.profileId === DOCUMENT_PROFILE_IDS.GREEK_IKE
            ? 'GR'
            : luxuryDesigner.profileId === DOCUMENT_PROFILE_IDS.BANK_OF_CYPRUS
              ? 'CY'
              : 'US',
      }),
    [
      luxuryDesigner,
      profile?.company_name,
      profile?.primary_color,
      profile?.secondary_color,
      profile?.accent_color,
      profile?.logo_url,
      profile?.seal_url,
      profile?.signature_url,
    ]
  );

  const luxuryCssVariables = useMemo(
    () => createDesignCssVariables(luxuryDesign),
    [luxuryDesign]
  );

  const luxuryPageDimensions = useMemo(
    () =>
      resolvePageDimensions({
        size: luxuryDesign.layout.page.size,
        orientation: luxuryDesign.layout.page.orientation,
      }),
    [luxuryDesign]
  );

  const luxuryProfileOptions = useMemo(
    () => getDocumentProfileOptions('el'),
    []
  );

  const normalizedPageLayout = useMemo(() => normalizePageLayout(pageLayout), [pageLayout]);
  const activePageDimensions = useMemo(() => pageDimensions(normalizedPageLayout), [normalizedPageLayout]);
  const documentImages = useMemo(() => extractDocumentImages(editorHtml), [editorHtml]);
  const documentTables = useMemo(() => summarizeTables(editorHtml), [editorHtml]);
  const documentOutline = useMemo(() => extractDocumentOutline(editorHtml), [editorHtml]);
  const findPreview = useMemo(() => findReplacePreview(editorHtml, findReplace.find), [editorHtml, findReplace.find]);
  const spelling = useMemo(() => spellCheckFoundation(editorHtml, [profile?.company_name, profile?.jurisdiction].filter(Boolean).join(' ').split(/\s+/)), [editorHtml, profile?.company_name, profile?.jurisdiction]);
  const reviewThreads = useMemo(() => groupReviewThreads(reviewState.comments || []), [reviewState.comments]);
  const versionSummary = useMemo(() => summarizeVersionHistory(versions), [versions]);
  const accessibility = useMemo(() => documentAccessibilityAudit(editorHtml, normalizedPageLayout), [editorHtml, normalizedPageLayout]);
  const performance = useMemo(() => documentPerformanceAudit(editorHtml, pageFlow), [editorHtml, pageFlow]);

  function updatePageLayout(mutator) {
    setPageLayout((current) => normalizePageLayout(typeof mutator === 'function' ? mutator(current) : mutator));
    setLayoutDirty(true);
  }

  const luxuryThemeOptions = useMemo(
    () => getDocumentThemeOptions('el'),
    []
  );

  const luxuryTypographyOptions = useMemo(
    () => getTypographyPresetOptions('el'),
    []
  );

  const luxuryLayoutOptions = useMemo(
    () => getLayoutPresetOptions('el'),
    []
  );

  async function loadAll() {
    setLoading(true);
    const [templatePayload, templateLibraryPayload, profilePayload, companyPayload, peoplePayload, bankPayload, clausePayload, folderPayload, collectionPayload, docs] = await Promise.all([
      documentApi.templates(),
      documentApi.templateLibrary(),
      documentApi.profile(),
      documentApi.companies(),
      documentApi.people(),
      documentApi.banks(),
      documentApi.clauses(),
      documentApi.folders(),
      documentApi.collections(),
      documentApi.list(filters),
    ]);
    setTemplates(templatePayload.templates || []);
    setTemplateLibrary(templateLibraryPayload || []);
    setProfile(profilePayload);
    setCompanies(companyPayload || []);
    setPeople(peoplePayload || []);
    setBanks(bankPayload || []);
    setClauses(clausePayload || templatePayload.clause_library || []);
    setFolders(folderPayload || []);
    setCollections(collectionPayload || []);
    setDocuments(docs || []);
    if (!selected && docs?.[0]) {
      setSelected(docs[0]);
      setEditorHtml(docs[0].content_html || '');
      setPageLayout(normalizePageLayout(docs[0].design?.pageLayout || docs[0].metadata?.page_layout));
      setLayoutDirty(false);
      await loadVersions(docs[0]);
    }
    setLoading(false);
  }

  useEffect(() => {
    loadAll().catch((error) => toast.error(error.message || 'Document Studio could not load.'));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    documentApi.designPresets().then((payload) => {
      setDesignPresets(payload?.presets || []);
    }).catch(() => {
      setDesignPresets([]);
    });
  }, []);

  useEffect(() => {
    lastSavedHtmlRef.current = selected?.content_html || '';
  }, [selected?.content_html, selected?.id]);

  useEffect(() => {
    window.clearTimeout(autosaveTimerRef.current);
    const contentDirty = Boolean(selected) && editorHtml !== lastSavedHtmlRef.current;
    if (loading || busy || reviewMode === 'viewing' || (!contentDirty && !layoutDirty)) {
      return undefined;
    }
    autosaveTimerRef.current = window.setTimeout(() => {
      saveEditor(true);
    }, AUTOSAVE_DELAY_MS);
    return () => window.clearTimeout(autosaveTimerRef.current);
    // saveEditor is intentionally resolved at execution time with the latest render state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [busy, editorHtml, layoutDirty, loading, reviewMode, selected?.id]);

  async function refreshDocuments(nextFilters = filters) {
    const docs = await documentApi.list(nextFilters);
    setDocuments(docs || []);
    return docs || [];
  }

  function toggleSelected(documentId) {
    setSelectedIds((current) => current.includes(documentId) ? current.filter((id) => id !== documentId) : [...current, documentId]);
  }

  async function createCollectionFromSelection() {
    const ids = selectedIds.length ? selectedIds : selected ? [selected.id] : [];
    if (!ids.length) return toast.error('Select at least one document for the collection.');
    try {
      const collection = await documentApi.createCollection({ name: `Executive Collection ${collections.length + 1}`, document_ids: ids, description: 'Curated enterprise document set' });
      setCollections((current) => [collection, ...current]);
      await refreshDocuments();
      toast.success('Collection created.');
    } catch (error) {
      toast.error(error.message || 'Collection creation failed.');
    }
  }

  async function runBatch(action, extra = {}) {
    const ids = selectedIds.length ? selectedIds : selected ? [selected.id] : [];
    if (!ids.length) return toast.error('Select one or more documents first.');
    setBusy(true);
    try {
      await documentApi.batch({ document_ids: ids, action, ...extra });
      setSelectedIds([]);
      await refreshDocuments();
      toast.success(`Batch ${action} completed.`);
    } catch (error) {
      toast.error(error.message || `Batch ${action} failed.`);
    } finally {
      setBusy(false);
    }
  }

  async function generateDocument() {
    setBusy(true);
    setStatusText('Generating executive document…');
    try {
      const payload = { ...generator, company_profile_id: profile?.id, parties: generator.parties, tags: generator.tags, fields: generator.fields };
      const preview = await documentApi.classify({ prompt: generator.prompt, title: generator.title, selected_type: generator.fields.document_type, template_id: generator.template_id, company_profile_id: profile?.id });
      setIntelligencePreview(preview);
      if (preview?.document_class?.override_source === 'prompt') {
        payload.template_id = 'premium-agreement';
        payload.fields = { ...payload.fields, document_type: preview.document_class.label, subject: '' };
      }
      const created = await documentApi.generate(payload);
      setSelected(created);
      setEditorHtml(created.content_html || '');
      setPageLayout(normalizePageLayout(created.design?.pageLayout || created.metadata?.page_layout));
      setLayoutDirty(false);
      setAnalysis(null); setQuality(null); setCompareResult(null);
      setGenerator((previous) => ({ ...previous, title: created.title, fields: { ...previous.fields, document_type: created.metadata?.document_class?.label || previous.fields.document_type, subject: '' } }));
      await refreshDocuments();
      toast.success(`${created.metadata?.document_class?.label || 'Document'} generated and validated.`);
    } catch (error) {
      toast.error(error.message || 'Generation failed.');
    } finally {
      setBusy(false);
      setStatusText('Ready');
    }
  }

  async function saveTemplateDraft(action = 'save') {
    setBusy(true);
    try {
      const payload = { ...templateDraft, tags: templateDraft.tags || [] };
      const saved = templateDraft.id ? await documentApi.updateTemplate(templateDraft.id, payload) : await documentApi.createTemplate(payload);
      const finalTemplate = action === 'publish' ? await documentApi.templateAction(saved.id, 'publish') : saved;
      setTemplateDraft(finalTemplate);
      setTemplateLibrary(await documentApi.templateLibrary());
      toast.success(action === 'publish' ? 'Template published.' : 'Template saved.');
    } catch (error) {
      toast.error(error.message || 'Template save failed.');
    } finally {
      setBusy(false);
    }
  }

  async function previewTemplate(template = templateDraft) {
    try {
      const variables = JSON.parse(mergeVariables || '{}');
      const preview = template.id ? await documentApi.mergeTemplate(template.id, { variables }) : { content_html: template.content_html, diagnostics: { valid: true, missing_variables: [] } };
      setMergePreview(preview);
      toast[preview.diagnostics?.valid ? 'success' : 'error'](preview.diagnostics?.valid ? 'Merge preview ready.' : 'Merge diagnostics found missing variables.');
    } catch (error) {
      toast.error(error.message || 'Merge preview failed.');
    }
  }

  function applyProfessionalTemplate(template) {
    const draft = buildProfessionalTemplateDraft(template);
    setTemplateDraft(draft);
    setGenerator((current) => ({
      ...current,
      title: draft.name,
      template_id: current.template_id,
      tags: draft.tags,
      fields: { ...current.fields, document_type: template.category, subject: template.tone },
      prompt: `Create a ${template.name} for ${profile?.company_name || 'the active company'} using ${template.tone}. Include: ${(template.blocks || []).join(', ')}.`,
    }));
    toast.success(`${template.name} loaded into the template workspace.`);
  }

  async function saveEditor(autosave = false) {
    if (!selected) return;
    const saveSequence = ++saveSequenceRef.current;
    const htmlAtSave = editorHtml;
    const layoutAtSave = normalizedPageLayout;
    setBusy(true);
    setStatusText(autosave ? 'Autosaving…' : 'Saving version…');
    try {
    if (autosave && htmlAtSave === lastSavedHtmlRef.current && !layoutDirty) {
      setStatusText('Ready');
      return;
    }
    const contentText = htmlAtSave.replace(/<[^>]+>/g, ' ');
    const exportLayout = buildExportLayoutPayload(layoutAtSave);
    const nextDesign = { ...(selected.design || {}), pageLayout: layoutAtSave, exportLayout };
    const nextMetadata = { ...(selected.metadata || {}), page_layout: layoutAtSave, export_layout: exportLayout, page_count: pageFlow.pageCount };
    const updated = await documentApi.update(selected.id, { content_html: htmlAtSave, content_text: contentText, design: nextDesign, metadata: nextMetadata, expected_version: selected.version_number, autosave, change_note: autosave ? 'Autosave' : 'Manual editor save' });
    if (saveSequence !== saveSequenceRef.current) return;
    setSelected(updated);
    lastSavedHtmlRef.current = updated.content_html || htmlAtSave;
    setPageLayout(normalizePageLayout(updated.design?.pageLayout || updated.metadata?.page_layout || layoutAtSave));
    setLayoutDirty(false);
    await refreshDocuments();
    await loadVersions(updated);
    toast.success(autosave ? 'Autosaved.' : 'Document saved with version history.');
    } catch (error) {
      toast.error(error.message || 'Document save failed.');
    } finally { setBusy(false); setStatusText('Ready'); }
  }

  async function selectCompany(companyId) {
    const company = companies.find((item) => item.id === companyId);
    if (!company) return;
    setProfile(company);
    setGenerator((previous) => ({ ...previous, company_profile_id: company.id, parties: [company.company_name, previous.parties[1] || 'Counterparty'], jurisdiction: company.jurisdiction || previous.jurisdiction }));
    setPeople(await documentApi.people({ company_profile_id: company.id }));
    setBanks(await documentApi.banks({ company_profile_id: company.id }));
    toast.success(`Company selected: ${company.company_name}`);
  }

  async function createEnterpriseCompany() {
    const created = await documentApi.createCompany({ company_name: companies.some((item) => item.company_name.includes('ΕΛΛΑΣ')) ? 'JSA GLOBAL PARTNERS LLC' : 'JSA GLOBAL PARTNERS ΕΛΛΑΣ Ι.Κ.Ε.', legal_form: companies.some((item) => item.company_name.includes('ΕΛΛΑΣ')) ? 'LLC' : 'Ι.Κ.Ε.', jurisdiction: companies.some((item) => item.company_name.includes('ΕΛΛΑΣ')) ? 'Wyoming, USA' : 'Greece', status: 'Active', standing: 'Good Standing', registered_office: 'Registered office on file', compliance_notes: 'Institutional banking, AML/KYC and corporate secretarial profile.' });
    setCompanies([created, ...companies]);
    await selectCompany(created.id);
  }

  async function addDefaultPerson() {
    if (!profile) return;
    const person = await documentApi.savePerson({ company_profile_id: profile.id, full_name: 'GIANNIS KOULIERAKIS', role: 'Managing Member', authority: 'Full authority to represent and bind the company for banking and corporate documentation.', relationship_to_company: 'Managing Member', initials: 'GK' });
    setPeople([person, ...people.filter((item) => item.id !== person.id)]);
    toast.success('Person authority profile saved.');
  }

  async function addDefaultBank() {
    if (!profile) return;
    const bank = await documentApi.saveBank({ company_profile_id: profile.id, bank_name: 'Bank of Cyprus', branch: 'Corporate Banking', swift: 'BCYPCY2N', iban: 'IBAN on file', address: 'Bank address on file', compliance_contact: 'Compliance Department', relationship_manager: 'Relationship Manager on file' });
    setBanks([bank, ...banks.filter((item) => item.id !== bank.id)]);
    toast.success('Bank profile saved.');
  }

  async function runLegalReview() {
    if (!selected) return;
    const review = await documentApi.legalReview(selected.id);
    setSelected({ ...selected, metadata: { ...selected.metadata, legal_review: review } });
    toast[review.passed ? 'success' : 'error'](review.passed ? 'Legal review passed.' : 'Legal review found issues.');
  }

  async function insertClause(clauseId) {
    if (!selected) return;
    const updated = await documentApi.insertClause(selected.id, clauseId);
    setSelected(updated); setEditorHtml(updated.content_html || ''); await loadVersions(updated); await refreshDocuments(); toast.success('Clause inserted and versioned.');
  }

  function onEditorChange(nextHtml) {
    if (reviewMode === 'viewing') return;
    if (nextHtml !== editorHtml) {
      setEditorHtml(nextHtml);
    }
  }

  function format(command, value = null) {
    const editor = editorApiRef.current;
    if (!editor) return;
    const textFormats = { bold: 'bold', italic: 'italic', underline: 'underline' };
    const alignments = { justifyLeft: 'left', justifyCenter: 'center', justifyRight: 'right' };
    if (textFormats[command]) editor.formatText(textFormats[command]);
    else if (alignments[command]) editor.formatElement(alignments[command]);
    else if (command === 'insertUnorderedList') editor.insertList(false);
    else if (command === 'insertOrderedList') editor.insertList(true);
    else if (command === 'indent') editor.indent();
    else if (command === 'outdent') editor.outdent();
    else if (command === 'fontName') editor.setInlineStyle({ 'font-family': value });
    else if (command === 'fontSize') editor.setInlineStyle({ 'font-size': `${Number(value || 3) * 4}px` });
    else if (command === 'foreColor') editor.setInlineStyle({ color: value });
    else if (command === 'lineHeight') editor.setInlineStyle({ 'line-height': value });
  }

  function insertHtml(markup) {
    editorApiRef.current?.insertHtml(markup);
  }

  function insertPremiumBlock(kind) {
    if (kind === 'pageBreak') {
      editorApiRef.current?.insertPageBreak();
      return;
    }
    const company = profile?.company_name || 'Company Name';
    const blocks = {
      title: '<h1 style="font-family:Georgia,serif;font-size:36px;letter-spacing:-.02em;margin:0 0 18px;color:#111827">Premium Document Title</h1><p style="font-size:14px;color:#4b5563">Professional opening paragraph with clear executive tone.</p>',
      paragraph: '<p style="margin:14px 0;line-height:1.7">Insert polished professional text here. Use concise language, premium spacing and clear business structure.</p>',
      list: '<ul style="margin:18px 0;padding-left:24px;line-height:1.7"><li>First professional point</li><li>Second professional point</li><li>Action / next step</li></ul>',
      logo: `<figure style="margin:18px 0 28px"><div style="width:96px;height:96px;border:1px solid #B9985A;border-radius:18px;display:flex;align-items:center;justify-content:center;color:#B9985A;font-family:Georgia,serif">LOGO</div><figcaption style="font-size:11px;color:#6b7280;margin-top:8px">${company}</figcaption></figure>`,
      header: `<div style="border-bottom:1px solid #B9985A;padding-bottom:12px;margin-bottom:24px;font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:#6b7280">${company} · Confidential · Page <span class="pageNumber">1</span></div>`,
      footer: `<div style="border-top:1px solid #B9985A;padding-top:12px;margin-top:32px;font-size:11px;color:#6b7280">${company} · Document No. DRAFT · Page <span class="pageNumber">1</span></div>`,
      watermark: `<div style="position:absolute;inset:38% auto auto 10%;transform:rotate(-28deg);font-family:Georgia,serif;font-size:76px;color:rgba(185,152,90,.09);pointer-events:none;z-index:0">CONFIDENTIAL</div>`,
      pageNumber: '<span style="display:inline-block;border-top:1px solid #d1d5db;margin-top:18px;padding-top:8px;font-size:11px;color:#6b7280">Page 1</span>',
      table: '<table style="width:100%;border-collapse:collapse;margin:24px 0;font-size:13px"><thead><tr><th style="border:1px solid #d1d5db;background:#111827;color:white;padding:10px;text-align:left">Item</th><th style="border:1px solid #d1d5db;background:#111827;color:white;padding:10px;text-align:left">Description</th><th style="border:1px solid #d1d5db;background:#111827;color:white;padding:10px;text-align:left">Value</th></tr></thead><tbody><tr><td style="border:1px solid #d1d5db;padding:10px">1</td><td style="border:1px solid #d1d5db;padding:10px">Professional service</td><td style="border:1px solid #d1d5db;padding:10px">TBD</td></tr></tbody></table>',
      signature: `<section style="margin-top:48px"><h2 style="font-family:Georgia,serif;font-size:22px;color:#111827">Signature</h2><div style="display:grid;grid-template-columns:1fr 1fr;gap:36px;margin-top:42px"><div style="border-top:1px solid #111827;padding-top:10px;min-height:90px">Authorized Signatory<br/>${company}<br/>Name:<br/>Date:</div><div style="border-top:1px solid #111827;padding-top:10px;min-height:90px">Counterparty<br/>Name:<br/>Title:<br/>Date:</div></div></section>`,
      pageBreak: '<div data-lumina-page-break="true" style="break-after:page;page-break-after:always;border-top:1px dashed #B9985A;margin:36px 0"><span style="font-size:10px;color:#B9985A">PAGE BREAK</span></div>',
    };
    insertHtml(blocks[kind] || blocks.paragraph);
  }

  function insertImageAsset(asset = imageDraft) {
    const html = buildImageFigureHtml(asset);
    if (!html) {
      toast.error('Add a safe image source before inserting. Supported sources: HTTPS, blob URLs, or data image files.');
      return;
    }
    insertHtml(html);
    setImageDraft((current) => ({ ...current, src: '', caption: current.caption }));
    toast.success(`${normalizeImageAsset(asset).role} inserted into the document.`);
  }

  function insertBrandAsset(role) {
    const profileKey = role === 'signature' ? 'signature_url' : role === 'seal' ? 'seal_url' : 'logo_url';
    const source = profile?.[profileKey] || '';
    if (!source) {
      toast.error(`No ${role} URL is saved in the active company identity.`);
      return;
    }
    insertImageAsset({
      ...imageDraft,
      src: source,
      role,
      alt: `${profile?.company_name || 'Company'} ${role}`,
      caption: role === 'logo' ? profile?.company_name || '' : '',
      width: role === 'logo' ? 24 : role === 'signature' ? 30 : 18,
      shape: role === 'seal' ? 'stamp' : 'rounded',
      align: role === 'logo' ? 'left' : 'center',
      border: role !== 'signature',
    });
  }

  function handleImageUpload(file) {
    if (!file?.type?.startsWith('image/')) return false;
    const reader = new FileReader();
    reader.onload = () => {
      const asset = normalizeImageAsset({ ...imageDraft, src: reader.result, alt: file.name, caption: file.name.replace(/\.[^.]+$/, '') });
      setImageDraft(asset);
      insertImageAsset(asset);
    };
    reader.readAsDataURL(file);
    return true;
  }

  function insertAdvancedTable() {
    insertHtml(buildAdvancedTableHtml(tableDraft));
    toast.success('Advanced table inserted with print-safe structure.');
  }

  function replaceAllMatches() {
    if (!findReplace.find.trim()) return;
    const nextHtml = applyFindReplace(editorHtml, findReplace.find, findReplace.replace);
    setEditorHtml(nextHtml);
    editorApiRef.current?.setHtml(nextHtml);
    toast.success(`${findPreview.count} match(es) replaced.`);
  }

  async function createBlankDocument() {
    setBusy(true);
    try {
      const title = newDocumentTitle.trim() || 'Untitled Document';
      const created = await documentApi.create({
        title,
        category: 'Corporate',
        tags: ['draft'],
        content_html: `<article><h1>${title}</h1><p>Start writing your premium document.</p></article>`,
        content_text: `${title} Start writing your premium document.`,
        design: { pageLayout: normalizedPageLayout },
        metadata: { page_layout: normalizedPageLayout },
      });
      setSelected(created);
      setEditorHtml(created.content_html || '');
      setPageLayout(normalizePageLayout(created.design?.pageLayout || created.metadata?.page_layout));
      setLayoutDirty(false);
      await refreshDocuments();
      await loadVersions(created);
      toast.success('New document created.');
    } catch (error) {
      toast.error(error.message || 'Document creation failed.');
    } finally {
      setBusy(false);
    }
  }

  async function duplicateSelectedDocument() {
    if (!selected) return;
    setBusy(true);
    try {
      const reusableMetadata = { ...(selected.metadata || {}) };
      ['lock', 'review', 'track_changes', 'export_jobs', 'activity'].forEach((key) => {
        delete reusableMetadata[key];
      });
      const copy = await documentApi.create({
        title: `Copy of ${selected.title}`,
        document_type: selected.document_type,
        category: selected.category,
        folder_id: selected.folder_id,
        collection_ids: selected.collection_ids,
        tags: selected.tags,
        country: selected.country,
        language: selected.language,
        template_id: selected.template_id,
        company_profile_id: selected.company_profile_id,
        content_html: selected.content_html,
        content_text: selected.content_text,
        design: { ...(selected.design || {}), pageLayout: normalizedPageLayout },
        components: selected.components,
        tables: selected.tables,
        charts: selected.charts,
        quality_score: selected.quality_score,
        imported_media_id: selected.imported_media_id,
        metadata: { ...reusableMetadata, duplicated_from: selected.id },
      });
      setSelected(copy);
      setEditorHtml(copy.content_html || '');
      setPageLayout(normalizePageLayout(copy.design?.pageLayout || copy.metadata?.page_layout));
      setLayoutDirty(false);
      await refreshDocuments();
      toast.success('Document duplicated.');
    } catch (error) {
      toast.error(error.message || 'Duplicate failed.');
    } finally {
      setBusy(false);
    }
  }

  async function renameSelectedDocument(nextTitle) {
    if (!selected) return;
    const title = typeof nextTitle === 'string' ? nextTitle : window.prompt('New document name', selected.title);
    if (!title?.trim()) return;
    const updated = await documentApi.update(selected.id, { title: title.trim(), change_note: 'Renamed document' });
    setSelected(updated);
    await refreshDocuments();
    toast.success('Document renamed.');
  }

  async function deleteSelectedDocument() {
    if (!selected) return;
    if (!window.confirm(`Delete ${selected.title}?`)) return;
    await documentApi.remove(selected.id);
    setSelected(null);
    setEditorHtml('');
    const docs = await refreshDocuments();
    if (docs[0]) {
      setSelected(docs[0]);
      setEditorHtml(docs[0].content_html || '');
      setPageLayout(normalizePageLayout(docs[0].design?.pageLayout || docs[0].metadata?.page_layout));
      setLayoutDirty(false);
      await loadVersions(docs[0]);
    }
    toast.success('Document deleted.');
  }

  function undoEditor() {
    editorApiRef.current?.undo();
  }

  function redoEditor() {
    editorApiRef.current?.redo();
  }

  function handleDrop(event) {
    event.preventDefault();
    const file = event.dataTransfer.files?.[0];
    if (!file) return;
    if (handleImageUpload(file)) {
      return;
    }
    toast.info('Το αρχείο παραλήφθηκε. Χρησιμοποιήστε την Εισαγωγή PDF/DOCX/OCR για να προστεθεί στη βιβλιοθήκη.');
  }

  function addComment() {
    const text = window.getSelection()?.toString() || 'Document note';
    setComments((items) => [{ id: Date.now(), text, reply: '', resolved: false }, ...items]);
    toast.success('Comment added.');
  }

  async function runAnalysis(action = 'summarize') {
    if (!selected) return;
    setBusy(true); setStatusText(`Running ${action.replaceAll('_', ' ')} review…`);
    try {
    const result = await documentApi.analyze(selected.id, {
      action,
      question: action === 'qa' ? 'What are the key obligations and missing risks?' : '',
      required_clauses: ['confidentiality', 'governing law', 'termination', 'liability', 'compliance', 'signature'],
    });
    setAnalysis(result);
    toast.success('Document review completed.');
    } catch (error) { toast.error(error.message || 'Review failed.'); }
    finally { setBusy(false); setStatusText('Ready'); }
  }

  async function operate(operation, extra = {}) {
    if (!selected) return;
    setBusy(true);
    try {
      const updated = await documentApi.operate(selected.id, { operation, instruction: generator.prompt, target_style: 'executive corporate', language: 'English', ...extra });
      setSelected(updated);
      setEditorHtml(updated.content_html || '');
      await refreshDocuments();
      await loadVersions(updated);
      toast.success(`${operation.replace('_', ' ')} completed.`);
    } catch (error) {
      toast.error(error.message || 'AI operation failed.');
    } finally {
      setBusy(false);
    }
  }

  async function applyDesigner() {
    if (!selected) return;

    setBusy(true);
    setStatusText('Εφαρμογή Luxury Document Design…');

    try {
      const updated = await documentApi.design(selected.id, {
        cover_style: luxuryDesign.theme.name,
        design_profile: luxuryDesign.profile.id,
        theme_id: luxuryDesign.theme.id,
        typography_preset_id: luxuryDesign.typography.id,
        layout_preset_id: luxuryDesign.layout.id,

        design: {
          margins: luxuryDesign.layout.page.margins,
          columns: luxuryDesign.layout.page.columns,
          spacing: luxuryDesign.typography.styles?.body?.lineHeight || 1.55,

          typography: {
            heading_font: luxuryDesign.typography.headingFont,
            body_font: luxuryDesign.typography.bodyFont,
            heading_size:
              luxuryDesign.typography.styles?.['document-title']?.fontSize || 34,
            body_size:
              luxuryDesign.typography.styles?.body?.fontSize || 11,
            paragraph_style: luxuryDesign.typography.id,
          },

          palette: {
            primary: luxuryDesign.theme.colors.primary,
            secondary: luxuryDesign.theme.colors.secondary,
            accent: luxuryDesign.theme.colors.accent,
            background: luxuryDesign.theme.colors.background,
            surface: luxuryDesign.theme.colors.surface,
            text: luxuryDesign.theme.colors.text,
          },

          fonts: {
            heading: luxuryDesign.typography.headingFont,
            body: luxuryDesign.typography.bodyFont,
          },

          background: luxuryDesign.theme.colors.background,
          watermark: true,
          page_border: `${luxuryDesign.theme.page.borderWidth || 1}px solid ${luxuryDesign.theme.colors.accent}`,
          header: luxuryDesign.layout.header,
          footer: luxuryDesign.layout.footer,
          cover: luxuryDesign.layout.cover,
          numbering: luxuryDesign.layout.numbering,
        },

        branding: luxuryDesign.branding,

        components: [
          { type: 'cover_page' },
          { type: 'company_information' },
          {
            type: 'legal_notices',
            text: luxuryDesign.branding.confidentialLabel,
          },
          { type: 'bank_details' },
          { type: 'certification_box' },
          { type: 'appendices' },
          { type: 'signature_blocks' },
          { type: 'corporate_seal' },
          { type: 'verification_qr' },
        ],

        tables: [
          {
            type: 'company_information',
            title: 'Company Information',
            headers: ['Field', 'Information'],
            rows: [
              ['Legal Name', profile?.company_name || 'Company'],
              ['Legal Form', profile?.legal_form || ''],
              ['Jurisdiction', profile?.jurisdiction || ''],
              ['Registration Number', profile?.registration_number || ''],
              ['Tax Number / EIN', profile?.ein_tax_number || ''],
            ],
          },
          {
            type: 'compliance',
            title: 'Compliance Matrix',
            headers: ['Control', 'Responsible Party', 'Status'],
            rows: [
              ['AML / KYC', profile?.company_name || 'Company', 'Required'],
              ['Signing Authority', 'Managing Member', 'Validated'],
              ['Corporate Standing', profile?.standing || 'On file', 'Recorded'],
            ],
          },
        ],
      });

      setSelected(updated);
      setEditorHtml(updated.content_html || '');
      setPageLayout(normalizePageLayout(updated.design?.pageLayout || updated.metadata?.page_layout));
      setLayoutDirty(false);
      setQuality(updated.quality_score || null);

      await refreshDocuments();
      await loadVersions(updated);

      toast.success('Το Luxury Document Design εφαρμόστηκε.');
    } catch (error) {
      toast.error(error.message || 'Η εφαρμογή του σχεδιασμού απέτυχε.');
    } finally {
      setBusy(false);
      setStatusText('Ready');
    }
  }

  async function redesign(presetId = selectedPresetId) {
    if (!selected) return;
    setPresetLoading(true);
    setPresetMessage('');
    try {
      const updated = await documentApi.redesign(selected.id, presetId || undefined);
      setSelected(updated); setEditorHtml(updated.content_html || ''); setPageLayout(normalizePageLayout(updated.design?.pageLayout || updated.metadata?.page_layout)); setLayoutDirty(false); setQuality(updated.quality_score); await refreshDocuments(); await loadVersions(updated);
      setPresetMessage(presetId ? `Design preset applied: ${designPresets.find((p) => p.id === presetId)?.name || presetId}` : 'Document redesigned without changing meaning.');
      toast.success(presetId ? 'Design preset applied — text preserved.' : 'Document redesigned without changing meaning.');
    } catch (error) {
      setPresetMessage(error.message || 'Redesign failed.');
      toast.error(error.message || 'Redesign failed.');
    } finally {
      setPresetLoading(false);
    }
  }

  async function scoreDocument() {
    if (!selected) return;
    setStatusText('Calculating quality score…');
    const score = await documentApi.quality(selected.id);
    setQuality(score);
    setStatusText('Ready');
    toast.success('Quality score calculated.');
  }

  async function buildPackage(package_type) {
    const created = await documentApi.createPackage({ package_type, title: `${package_type} executive package`, client: generator.parties[1] || 'Strategic Client', fields: generator.fields, tags: ['package', package_type, 'executive'] });
    setSelected(created); setEditorHtml(created.content_html || ''); setPageLayout(normalizePageLayout(created.design?.pageLayout || created.metadata?.page_layout)); setLayoutDirty(false); setQuality(created.quality_score); await refreshDocuments(); await loadVersions(created); toast.success(`${package_type} package generated.`);
  }

  async function compareWithFirstOther() {
    if (!selected) return;
    const other = documents.find((doc) => doc.id !== selected.id);
    if (!other) return toast.error('Create or select another document for comparison.');
    setCompareResult(await documentApi.compare(selected.id, other.id));
  }

  async function versionAction(version, action) {
    if (!selected || !version) return;
    const result = await documentApi.versionAction(selected.id, version.id, { action, name: action === 'rename' ? `${version.change_note} · executive` : undefined });
    if (action === 'restore') {
      const refreshed = await documentApi.list({ q: selected.title });
      const restored = refreshed.find((doc) => doc.id === selected.id) || selected;
      setSelected(restored);
      setEditorHtml(restored.content_html || '');
      setPageLayout(normalizePageLayout(restored.design?.pageLayout || restored.metadata?.page_layout));
      setLayoutDirty(false);
    }
    await loadVersions(selected);
    toast.success(`Version ${action} completed: ${result.version_id || version.id}`);
  }

  async function loadVersions(document) {
    const payload = await documentApi.versions(document.id);
    setVersions(payload || []);
    const activityPayload = await documentApi.activity(document.id);
    setActivity(activityPayload.events || []);
    await loadReviewWorkspace(document);
  }

  async function loadReviewWorkspace(document = selected) {
    if (!document?.id) return;
    try {
      const [reviewPayload, trackPayload] = await Promise.all([
        documentApi.review(document.id),
        documentApi.trackChanges(document.id),
      ]);
      setReviewState(reviewPayload || { comments: [], markers: [], open_count: 0, resolved_count: 0, status: document.status });
      setTrackState(trackPayload || { changes: [], pending_count: 0, accepted_count: 0, rejected_count: 0 });
    } catch (error) {
      toast.error(error.message || 'Review workspace could not load.');
    }
  }

  async function createBackendReviewItem(kind = reviewDraft.kind) {
    if (!selected) return;
    const selectedText = window.getSelection()?.toString() || '';
    const body = (reviewDraft.body || selectedText || `${kind === 'suggestion' ? 'Suggested change' : 'Review note'}`).trim();
    try {
      const payload = await documentApi.createReviewItem(selected.id, {
        kind,
        body,
        anchor: { selected_text: selectedText, document_title: selected.title },
        suggestion: kind === 'suggestion' ? { replacement: reviewDraft.suggestion || selectedText, selected_text: selectedText } : {},
      });
      setReviewState(payload.review || reviewState);
      setReviewDraft({ kind: 'comment', body: '', suggestion: '' });
      await refreshDocuments();
      toast.success(`${kind === 'suggestion' ? 'Suggestion' : 'Comment'} added to review history.`);
    } catch (error) {
      toast.error(error.message || 'Review item could not be created.');
    }
  }

  async function reviewItemAction(commentId, action) {
    if (!selected) return;
    try {
      const payload = await documentApi.reviewAction(selected.id, commentId, { action: normalizeReviewAction(action) });
      setReviewState(payload.review || reviewState);
      if (payload.document) {
        setSelected(payload.document);
        setEditorHtml(payload.document.content_html || '');
        lastSavedHtmlRef.current = payload.document.content_html || '';
        await loadVersions(payload.document);
        await refreshDocuments();
      }
      toast.success(`Review item ${action}.`);
    } catch (error) {
      toast.error(error.message || 'Review action failed.');
    }
  }

  async function addTrackedChange(change_type = 'replacement') {
    if (!selected) return;
    const selectedText = window.getSelection()?.toString() || '';
    try {
      const payload = await documentApi.createTrackChange(selected.id, {
        change_type,
        before: selectedText,
        after: reviewDraft.suggestion || reviewDraft.body || selectedText,
        range: { selected_text: selectedText },
        metadata: { source: 'review_sidebar' },
      });
      setTrackState(payload.track_changes || trackState);
      toast.success('Tracked change recorded.');
    } catch (error) {
      toast.error(error.message || 'Tracked change could not be recorded.');
    }
  }

  async function trackChangeAction(action, changeIds = []) {
    if (!selected) return;
    try {
      const updated = await documentApi.trackChangeAction(selected.id, { action, change_ids: changeIds });
      setSelected(updated);
      setEditorHtml(updated.content_html || '');
      setPageLayout(normalizePageLayout(updated.design?.pageLayout || updated.metadata?.page_layout));
      setLayoutDirty(false);
      await loadVersions(updated);
      await refreshDocuments();
      toast.success(`Tracked changes ${action}.`);
    } catch (error) {
      toast.error(error.message || 'Track change action failed.');
    }
  }

  async function compareWithLatestVersion() {
    if (!selected || !versionSummary.latest) return;
    setCompareResult(await documentApi.versionDiff(selected.id, versionSummary.latest.id));
  }

  async function toggleFavorite(document) {
    const updated = await documentApi.update(document.id, { favorite: !document.favorite });
    setSelected(updated.id === selected?.id ? updated : selected);
    await refreshDocuments();
  }

  async function importFile(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    setBusy(true);
    try {
      const imported = await documentApi.importFile(file, { title: file.name, category: 'Imported', tags: 'imported,ocr' });
      setSelected(imported);
      setEditorHtml(imported.content_html || '');
      setPageLayout(normalizePageLayout(imported.design?.pageLayout || imported.metadata?.page_layout));
      setLayoutDirty(false);
      await refreshDocuments();
      toast.success('Document imported and searchable text extracted.');
    } catch (error) {
      toast.error(error.message || 'Import failed.');
    } finally {
      setBusy(false);
      event.target.value = '';
    }
  }

  async function createFolder(payload = {}) {
    const name = String(payload.name || `Corporate Folder ${folders.length + 1}`).trim();
    if (!name) {
      toast.error('Folder name is required.');
      return;
    }
    try {
      const folder = await documentApi.createFolder({ ...payload, name });
      setFolders((current) => [...current, folder]);
      setFilters((current) => ({ ...current, folder_id: folder.id }));
      toast.success('Folder created.');
    } catch (error) {
      toast.error(error.message || 'Folder creation failed.');
    }
  }

  async function renameFolder(folderId, name) {
    const trimmed = String(name || '').trim();
    if (!trimmed) return toast.error('Folder name is required.');
    try {
      const updated = await documentApi.renameFolder(folderId, trimmed);
      setFolders((current) => current.map((folder) => (folder.id === folderId ? updated : folder)));
      toast.success('Folder renamed.');
    } catch (error) {
      toast.error(error.message || 'Folder rename failed.');
    }
  }

  async function deleteFolder(folderId) {
    try {
      await documentApi.deleteFolder(folderId);
      setFolders((current) => current.filter((folder) => folder.id !== folderId));
      setFilters((current) => ({ ...current, folder_id: current.folder_id === folderId ? '' : current.folder_id }));
      toast.success('Folder deleted.');
    } catch (error) {
      toast.error(error.message || 'Folder deletion failed.');
    }
  }

  async function moveFolder(folderId, parentId = null) {
    try {
      const updated = await documentApi.moveFolder(folderId, parentId);
      setFolders((current) => current.map((folder) => (folder.id === folderId ? updated : folder)));
      toast.success('Folder moved.');
    } catch (error) {
      toast.error(error.message || 'Folder move failed.');
    }
  }

  async function lifecycle(action) {
    if (!selected) return;
    setBusy(true);
    try {
      const updated = await documentApi.lifecycle(selected.id, action);
      setSelected(updated);
      setEditorHtml(updated.content_html || '');
      await refreshDocuments();
      await loadVersions(updated);
      toast.success(`Document ${action.replace('-', ' ')} completed.`);
    } catch (error) {
      toast.error(error.message || 'Document lifecycle update failed.');
    } finally {
      setBusy(false);
    }
  }

  async function download(format) {
    if (!selected) return;
    setBusy(true); setStatusText(`Exporting ${format.toUpperCase()}…`);
    try {
    const response = await fetch(exportDocumentUrl(selected.id, format), { headers: makeDocumentDownloadHeaders() });
    if (!response.ok) {
      throw new Error(`${format.toUpperCase()} export failed with status ${response.status}`);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${selected.title}.${format}`;
    link.click();
    URL.revokeObjectURL(url);
    toast.success(`${format.toUpperCase()} export generated.`);
    } catch (error) { toast.error(error.message || `${format.toUpperCase()} export failed.`); }
    finally { setBusy(false); setStatusText('Ready'); }
  }

  function showInspector(context = 'document') {
    setSelectionContext(context);
    setRightPanelMode('inspector');
    setRightPanelCollapsed(false);
  }

  function handleOfficeAction(action) {
    const directActions = {
      new: createBlankDocument,
      save: () => saveEditor(false),
      undo: undoEditor,
      redo: redoEditor,
      share: () => selected && navigator.clipboard?.writeText(documentApi.previewUrl(selected.id)).then(() => toast.success('Share link copied.')),
      print: () => window.print(),
      rename: renameSelectedDocument,
      bold: () => format('bold'),
      italic: () => format('italic'),
      underline: () => format('underline'),
      bullets: () => format('insertUnorderedList'),
      numbering: () => format('insertOrderedList'),
      left: () => format('justifyLeft'),
      center: () => format('justifyCenter'),
      right: () => format('justifyRight'),
      indent: () => format('indent'),
      outdent: () => format('outdent'),
      table: insertAdvancedTable,
      image: () => imageInputRef.current?.click(),
      seal: () => insertBrandAsset('seal'),
      comment: addComment,
      track: () => addTrackedChange('replacement'),
      accept: () => trackChangeAction('accept'),
      reject: () => trackChangeAction('reject'),
      legalReview: runLegalReview,
      quality: scoreDocument,
      generate: generateDocument,
      continue: () => operate('continue'),
      rewrite: () => operate('rewrite'),
      translate: () => operate('translate'),
      summarize: () => operate('summarize'),
      improve: () => operate('improve'),
      preview: () => setPrintPreview((value) => !value),
      pageWidth: () => setPage((current) => ({ ...current, zoom: normalizedPageLayout.orientation === 'landscape' ? 80 : 100 })),
      orientation: () => updatePageLayout((current) => ({ ...current, orientation: current.orientation === 'portrait' ? 'landscape' : 'portrait' })),
      size: () => updatePageLayout((current) => ({ ...current, size: current.size === 'A4' ? 'Letter' : 'A4' })),
      open: () => setLibraryOpen(true),
      toolCenter: () => setToolCenterOpen(true),
      split: () => setRightPanelCollapsed(false),
    };
    if (['docx', 'pdf', 'html', 'markdown'].includes(action)) return download(action);
    if (['pages', 'headings', 'bookmarks', 'outline'].includes(action)) return setNavigatorTab(action[0].toUpperCase() + action.slice(1));
    if (['title', 'paragraph', 'pageBreak', 'header', 'footer', 'pageNumber', 'signature', 'watermark'].includes(action)) return insertPremiumBlock(action);
    if (['shape', 'textBox', 'columns', 'toc'].includes(action)) return insertPremiumBlock(action === 'textBox' ? 'paragraph' : 'list');
    if (action === 'margins' || action === 'spacing') return showInspector('document');
    if (action === 'reviewPane') return showInspector('document');
    if (action === 'find' || action === 'replace') return setNavigatorTab('Outline');
    return directActions[action]?.();
  }

  return (
    <div className="document-office-shell min-h-screen bg-[#171717] pb-7 text-white">
      <DocumentOfficeChrome
        activeTab={ribbonTab}
        onTabChange={setRibbonTab}
        onAction={handleOfficeAction}
        document={selected}
        onRenameDocument={renameSelectedDocument}
        status={loading ? 'Loading Document Studio…' : statusText}
        busy={busy || loading}
        companyName={profile?.company_name}
        zoom={page.zoom}
        onZoomChange={(zoom) => setPage((current) => ({ ...current, zoom }))}
        pageCount={pageFlow.pageCount}
        wordCount={performance.words}
        characterCount={(selected?.content_text || '').length}
        language={selected?.language}
      />
      <div className="document-office-body">
      <details className="document-file-management" open={libraryOpen} onToggle={(event) => setLibraryOpen(event.currentTarget.open)}>
        <summary className="cursor-pointer text-xs font-medium text-white/50 hover:text-gold">File, library and batch management</summary>
      <section className="mt-3 rounded-xl border border-white/10 bg-black/20 p-4">
        <div className="flex flex-col xl:flex-row xl:items-end xl:justify-between gap-6">
          <div>
            <div className="text-xs uppercase tracking-[0.32em] text-gold">Document Intelligence & Corporate Studio</div>
            <h1 className="mt-3 text-4xl font-display tracking-tight">Luxury corporate document workspace</h1>
            <p className="mt-3 max-w-3xl text-white/65">Δημιουργήστε, επεξεργαστείτε, εισαγάγετε, αναλύστε, εκδώστε εκδόσεις και εξαγάγετε επαγγελματικά νομικά, οικονομικά και εταιρικά έγγραφα με εταιρική ταυτότητα, αναζητήσιμο κείμενο OCR και αρχεία PDF/DOCX υψηλής ποιότητας.</p>
          </div>
          <div className="grid grid-cols-3 gap-3 text-center">
            <Metric label="Έγγραφα" value={documents.length} />
            <Metric label="Πρότυπα" value={templates.length} />
            <Metric label="Φάκελοι" value={folders.length} />
          </div>
        </div>
        <div className="mt-6 flex flex-wrap items-center gap-3 rounded-2xl border border-white/10 bg-black/20 px-4 py-3 text-xs text-white/60"><span className={`h-2 w-2 rounded-full ${busy || loading ? 'bg-gold animate-pulse' : 'bg-emerald-400'}`} />{loading ? 'Loading Document Studio…' : statusText}</div>
        <div className="mt-4 grid gap-3 rounded-2xl border border-gold/20 bg-black/20 p-3 md:grid-cols-[1fr_auto_auto_auto_auto]">
          <input className="field" value={newDocumentTitle} onChange={(e) => setNewDocumentTitle(e.target.value)} placeholder="New document title" />
          <button className="btn gold" disabled={busy} onClick={createBlankDocument}>New document</button>
          <button className="btn secondary" disabled={!selected || busy} onClick={renameSelectedDocument}>Rename</button>
          <button className="btn secondary" disabled={!selected || busy} onClick={duplicateSelectedDocument}>Duplicate</button>
          <button className="btn secondary" disabled={!selected || busy} onClick={deleteSelectedDocument}>Delete</button>
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-2 rounded-2xl border border-gold/20 bg-black/20 p-3 text-xs text-white/70">
          <b className="text-gold">Batch & Collections</b>
          <span>{selectedIds.length} selected</span>
          <button className="btn secondary" disabled={busy} onClick={() => setSelectedIds(documents.map((document) => document.id))}>Select all</button>
          <button className="btn secondary" disabled={busy || !selectedIds.length} onClick={() => setSelectedIds([])}>Clear</button>
          <button className="btn secondary" disabled={busy} onClick={createCollectionFromSelection}>Create collection</button>
          <button className="btn secondary" disabled={busy} onClick={() => runBatch('archive')}>Batch archive</button>
          <button className="btn secondary" disabled={busy} onClick={() => runBatch('restore')}>Batch restore</button>
          <button className="btn secondary" disabled={busy} onClick={() => runBatch('trash')}>Batch trash</button>
          <button className="btn secondary" disabled={busy} onClick={() => runBatch('tags', { mode: 'append', tags: ['reviewed'] })}>Tag reviewed</button>
          <button className="btn secondary" disabled={busy} onClick={() => { const next = { ...filters, status: 'trashed' }; setFilters(next); refreshDocuments(next); }}>Trash view</button>
          <button className="btn secondary" disabled={busy} onClick={() => { const next = { ...filters, status: 'archived' }; setFilters(next); refreshDocuments(next); }}>Archive view</button>
          <button className="btn secondary" disabled={busy} onClick={() => { const next = { ...filters, status: '' }; setFilters(next); refreshDocuments(next); }}>All active</button>
        </div>
        <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-white/50">
          {collections.slice(0, 8).map((collection) => <button key={collection.id} className="rounded-full border border-gold/20 bg-gold/10 px-3 py-1 text-gold" onClick={() => { const next = { ...filters, collection_id: collection.id }; setFilters(next); refreshDocuments(next); }}>{collection.name} · {collection.document_ids?.length || 0}</button>)}
        </div>
      </section>
      <DocumentStudioSidebar
        filters={filters} setFilters={setFilters} categories={categories} folders={folders} documents={documents} loading={loading}
        selectedDocument={selected} onSearch={() => refreshDocuments()} onCreateFolder={createFolder} renameFolder={renameFolder}
        deleteFolder={deleteFolder} moveFolder={moveFolder} selectedIds={selectedIds} onToggleSelected={toggleSelected}
        onSelectDocument={(document) => { setSelected(document); setEditorHtml(document.content_html || ''); setPageLayout(normalizePageLayout(document.design?.pageLayout || document.metadata?.page_layout)); setLayoutDirty(false); setAnalysis(null); setQuality(document.quality_score || null); setCompareResult(null); loadVersions(document); setLibraryOpen(false); }}
      />
      </details>

      <div className={`document-office-workspace ${navigatorCollapsed ? 'navigator-is-collapsed' : ''}`}>
        <DocumentNavigator activeTab={navigatorTab} onTabChange={setNavigatorTab} outline={documentOutline} pageCount={pageFlow.pageCount} collapsed={navigatorCollapsed} onToggle={() => setNavigatorCollapsed(value => !value)} onOpenLibrary={() => setLibraryOpen(true)} />

        <PanelGroup direction="horizontal" className="document-editor-preview-group min-h-[900px] !overflow-visible">
        <ResizablePanel defaultSize={rightPanelCollapsed ? 100 : 60} minSize={45} className="!overflow-visible bg-[#252525]">

        <main className="document-editor-column flex flex-col gap-4 p-4">
          <Panel title="Corporate Generator" icon={Sparkles}>
            <div className="rounded-2xl border border-gold/30 bg-gold/10 p-4 text-xs text-white/75 space-y-2">
              <div className="flex items-center justify-between gap-2"><b>Ενεργό Μητρώο Εταιρείας</b><button className="btn secondary" onClick={createEnterpriseCompany}>Προσθήκη εταιρείας</button></div>
              <select className="field" value={profile?.id || ''} onChange={(e) => selectCompany(e.target.value)}>{companies.map((company) => <option key={company.id} value={company.id}>{company.company_name} · {company.jurisdiction || 'Jurisdiction on file'}</option>)}</select>
              <div className="grid grid-cols-2 gap-2"><span>People: {people.length}</span><span>Banks: {banks.length}</span></div>
              <div className="flex gap-2"><button className="btn secondary" onClick={addDefaultPerson}>Προσθήκη Διαχειριστή</button><button className="btn secondary" onClick={addDefaultBank}>Προσθήκη τράπεζας</button></div>
            </div>
            <div className="grid md:grid-cols-2 gap-3">
              <select className="field" value={generator.template_id} onChange={(e) => setGenerator({ ...generator, template_id: e.target.value })}>{templates.map((template) => <option key={template.id} value={template.id}>{template.name}</option>)}</select>
              <select className="field" value={generator.creation_mode} onChange={(e) => setGenerator({ ...generator, creation_mode: e.target.value })}>{DOCUMENT_CREATION_MODES.map((mode) => <option key={mode} value={mode}>{mode}</option>)}</select>
              <input className="field" value={generator.title} onChange={(e) => setGenerator({ ...generator, title: e.target.value })} />
              <select className="field" value={generator.fields.document_type || 'Contracts'} onChange={(e) => setGenerator({ ...generator, fields: { ...generator.fields, document_type: e.target.value } })}>{DOCUMENT_TYPES.map((type) => <option key={type}>{type}</option>)}</select>
              <input className="field" value={generator.parties.join(', ')} onChange={(e) => setGenerator({ ...generator, parties: e.target.value.split(',').map((x) => x.trim()).filter(Boolean) })} />
              <input className="field" value={profile?.jurisdiction || generator.jurisdiction} onChange={(e) => setGenerator({ ...generator, jurisdiction: e.target.value })} />
            </div>
            <textarea className="field min-h-[84px]" value={generator.fields.subject} onChange={(e) => setGenerator({ ...generator, fields: { ...generator.fields, subject: e.target.value } })} />
            <textarea className="field min-h-[96px]" value={generator.prompt} onChange={(e) => setGenerator({ ...generator, prompt: e.target.value })} onBlur={async () => { if (generator.prompt.trim()) { try { setIntelligencePreview(await documentApi.classify({ prompt: generator.prompt, title: generator.title, selected_type: generator.fields.document_type, template_id: generator.template_id })); } catch (_) {} } }} placeholder="AI document prompt, rewrite instruction, translation instruction or executive design brief." />
            {intelligencePreview && <div className="rounded-2xl border border-gold/30 bg-gold/10 p-4 text-xs text-white/80 space-y-2">
              <div><b>Αναγνωρισμένη κατηγορία:</b> {translateDocumentClass(intelligencePreview.document_class?.label)} ({Math.round((intelligencePreview.document_class?.confidence || 0) * 100)}%)</div>
              <div><b>Company:</b> {intelligencePreview.smart_fields?.company_name}</div>
              <div><b>Principal person:</b> {intelligencePreview.smart_fields?.managing_member || intelligencePreview.smart_fields?.authorized_signatory}</div>
              <select className="field" value={generator.fields.document_type || intelligencePreview.document_class?.label} onChange={(e) => { setGenerator({ ...generator, fields: { ...generator.fields, document_type: e.target.value, subject: '' } }); setIntelligencePreview({ ...intelligencePreview, document_class: { ...intelligencePreview.document_class, label: e.target.value } }); }}>
                {templatePayloadClasses(templates, intelligencePreview).map((item) => (
                  <option key={item.value} value={item.value}>{item.label}</option>
                ))}
              </select>
            </div>}
            <button className="btn gold disabled:opacity-50 disabled:cursor-not-allowed" disabled={busy || loading || !generator.title.trim()} onClick={generateDocument}><Wand2 className="h-4 w-4" />{busy ? 'Επεξεργασία…' : 'Παραγωγή Εγγράφου'}</button>
          </Panel>

          <Panel title="Template & Merge Engine" icon={FileText}>
            <div className="rounded-2xl border border-gold/20 bg-black/20 p-4 text-xs text-white/65 space-y-3">
              <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                <div><b className="text-gold">Professional Template Library</b><div className="text-white/45">Curated single-user Word/Docs-grade templates with merge-ready sections and compliance metadata.</div></div>
                <div className="flex gap-2">
                  <input className="field py-2" value={templateFilters.q} onChange={(e) => setTemplateFilters((current) => ({ ...current, q: e.target.value }))} placeholder="Search templates" />
                  <select className="field py-2" value={templateFilters.category} onChange={(e) => setTemplateFilters((current) => ({ ...current, category: e.target.value }))}>
                    <option value="">All categories</option>
                    {[...new Set(PROFESSIONAL_TEMPLATE_CATALOG.map((template) => template.category))].map((category) => <option key={category}>{category}</option>)}
                  </select>
                </div>
              </div>
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {professionalTemplateMatches.map((template) => (
                  <button key={template.id} type="button" className="rounded-2xl border border-white/10 bg-gradient-to-br from-white/[0.06] to-gold/[0.05] p-4 text-left transition hover:-translate-y-0.5 hover:border-gold" onClick={() => applyProfessionalTemplate(template)}>
                    <div className="text-[10px] uppercase tracking-[0.22em] text-gold">{template.category} · {template.jurisdiction}</div>
                    <div className="mt-2 font-display text-lg text-white">{template.name}</div>
                    <div className="mt-2 text-white/55">{template.tone}</div>
                    <div className="mt-3 flex flex-wrap gap-1">{template.blocks.slice(0, 4).map((block) => <span key={block} className="rounded-full border border-white/10 px-2 py-0.5 text-white/45">{block}</span>)}</div>
                  </button>
                ))}
              </div>
            </div>
            <div className="grid gap-3 md:grid-cols-3">
              {[
                { name: 'Banking Letterhead', category: 'Banking', tone: 'Institutional blue, strict spacing, compliance-ready' },
                { name: 'Law Firm Agreement', category: 'Legal', tone: 'Classic serif, gold rules, signature-first drafting' },
                { name: 'Executive Proposal', category: 'Proposal', tone: 'Modern consulting layout with premium cover and pricing' },
              ].map((preset) => (
                <button
                  key={preset.name}
                  type="button"
                  className="rounded-2xl border border-gold/20 bg-gradient-to-br from-gold/15 to-white/[0.03] p-4 text-left transition hover:-translate-y-0.5 hover:border-gold hover:shadow-xl"
                  onClick={() => setTemplateDraft({
                    name: preset.name,
                    category: preset.category,
                    tags: [preset.category.toLowerCase(), 'premium'],
                    content_html: `<article><h1>{{title}}</h1><p>{{company.name}}</p><p>${preset.tone}</p>{{#if signer}}<section><h2>Signature</h2><p>{{signer}}</p></section>{{/if}}</article>`,
                    merge_schema: { required: ['title', 'company.name'] },
                  })}
                >
                  <div className="text-xs uppercase tracking-[0.24em] text-gold">{preset.category}</div>
                  <div className="mt-2 font-display text-xl text-white">{preset.name}</div>
                  <div className="mt-2 text-xs text-white/55">{preset.tone}</div>
                </button>
              ))}
            </div>
            <div className="grid md:grid-cols-2 gap-3">
              <input className="field" value={templateDraft.name || ''} onChange={(e) => setTemplateDraft({ ...templateDraft, name: e.target.value })} placeholder="Template name" />
              <input className="field" value={templateDraft.category || ''} onChange={(e) => setTemplateDraft({ ...templateDraft, category: e.target.value })} placeholder="Category" />
              <input className="field md:col-span-2" value={(templateDraft.tags || []).join(', ')} onChange={(e) => setTemplateDraft({ ...templateDraft, tags: e.target.value.split(',').map((tag) => tag.trim()).filter(Boolean) })} placeholder="Tags" />
            </div>
            <textarea className="field min-h-[150px] font-mono text-xs" value={templateDraft.content_html || ''} onChange={(e) => setTemplateDraft({ ...templateDraft, content_html: e.target.value })} />
            <textarea className="field min-h-[110px] font-mono text-xs" value={mergeVariables} onChange={(e) => setMergeVariables(e.target.value)} />
            <div className="rounded-2xl border border-white/10 bg-black/20 p-3 text-xs text-white/65">
              <div className="mb-2 flex items-center justify-between"><b className="text-gold">Variables & Merge Fields</b><span className={mergeDiagnostics.valid ? 'text-emerald-300' : 'text-amber-200'}>{mergeDiagnostics.valid ? 'All fields populated' : `${mergeDiagnostics.missing.length} missing`}</span></div>
              <div className="flex flex-wrap gap-2">
                {['title', 'company.name', 'signer', 'date', 'amount', 'jurisdiction'].map((field) => <button key={field} type="button" className="rounded-full border border-gold/20 bg-gold/10 px-3 py-1 text-gold" onClick={() => setTemplateDraft((current) => ({ ...current, content_html: `${current.content_html || ''}${buildMergeFieldChip(field)}` }))}>{buildMergeFieldChip(field)}</button>)}
              </div>
              <div className="mt-3 grid gap-2 md:grid-cols-2">
                <div><b className="text-white">Fields:</b> {mergeDiagnostics.fields.join(', ') || 'None'}</div>
                <div><b className="text-white">Missing:</b> {mergeDiagnostics.missing.join(', ') || 'None'}</div>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <button className="btn gold" disabled={busy} onClick={() => saveTemplateDraft('save')}>Save template</button>
              <button className="btn secondary" disabled={busy || !templateDraft.id} onClick={() => saveTemplateDraft('publish')}>Publish</button>
              <button className="btn secondary" disabled={busy} onClick={() => previewTemplate()}>Merge preview</button>
            </div>
            <div className="grid md:grid-cols-2 gap-3">
              <div className="rounded-xl border border-white/10 bg-black/20 p-3 text-xs text-white/60">
                <b className="text-white">Template Library</b>
                {templateLibrary.slice(0, 8).map((template) => <button key={template.id} className="mt-2 block w-full rounded-xl border border-white/10 bg-gradient-to-r from-white/[0.06] to-gold/[0.04] p-3 text-left transition hover:border-gold" onClick={() => setTemplateDraft(template)}><span className="text-gold">{template.category}</span><div className="text-white">{template.name}</div><div>{template.status} · v{template.version_number || 1}</div></button>)}
              </div>
              <div className="rounded-xl border border-white/10 bg-white p-3 text-xs text-black">
                <b>Diagnostics</b>
                <pre className="whitespace-pre-wrap">{JSON.stringify(mergePreview?.diagnostics || {}, null, 2)}</pre>
                <div dangerouslySetInnerHTML={{ __html: sanitizeEditorHtml(mergePreview?.content_html || '<p>No preview</p>') }} />
              </div>
            </div>
          </Panel>

          <Panel className="order-first document-primary-editor" title={selected ? `Editor · ${selected.title}` : 'Professional Editor'} icon={FileText}>
            <div className="premium-toolbar document-legacy-toolbar sticky top-0 z-10 -mx-2 rounded-2xl border border-white/10 bg-ink-950/95 p-3 shadow-2xl backdrop-blur" role="toolbar" aria-label="Document editing toolbar">
              <div className="flex flex-wrap items-center gap-2">
                <select className="field max-w-[130px] py-2" aria-label="Review mode" value={reviewMode} onChange={(e) => setReviewMode(e.target.value)}>{['editing', 'reviewing', 'viewing'].map((mode) => <option key={mode}>{mode}</option>)}</select>
                <select className="field max-w-[110px] py-2" value={normalizedPageLayout.size} onChange={(e) => updatePageLayout((current) => ({ ...current, size: e.target.value }))}>{['A4', 'Letter'].map((x) => <option key={x}>{x}</option>)}</select>
                <select className="field max-w-[130px] py-2" value={normalizedPageLayout.orientation} onChange={(e) => updatePageLayout((current) => ({ ...current, orientation: e.target.value }))}>{['portrait', 'landscape'].map((x) => <option key={x}>{x}</option>)}</select>
                <select className="field max-w-[140px] py-2" onChange={(e) => format('fontName', e.target.value)} defaultValue="Inter">{['Inter', 'Georgia', 'Times New Roman', 'Arial', 'Calibri'].map((x) => <option key={x}>{x}</option>)}</select>
                <select className="field max-w-[90px] py-2" onChange={(e) => format('fontSize', e.target.value)} defaultValue="3">{[['2', '10'], ['3', '12'], ['4', '14'], ['5', '18'], ['6', '24']].map(([v, label]) => <option value={v} key={v}>{label}px</option>)}</select>
                {[
                  ['B', () => format('bold')], ['I', () => format('italic')], ['U', () => format('underline')], ['• List', () => format('insertUnorderedList')], ['1. List', () => format('insertOrderedList')], ['Left', () => format('justifyLeft')], ['Center', () => format('justifyCenter')], ['Right', () => format('justifyRight')], ['Indent', () => format('indent')], ['Outdent', () => format('outdent')],
                ].map(([label, action]) => <button key={label} type="button" className="rounded-lg border border-white/10 px-3 py-2 text-xs text-white/70 hover:border-gold hover:text-gold" disabled={!selected || busy} onClick={action}>{label}</button>)}
                <input type="color" title="Text color" className="h-9 w-10 rounded-lg bg-transparent" onChange={(e) => format('foreColor', e.target.value)} />
                {[
                  ['Title', 'title'], ['Paragraph', 'paragraph'], ['List block', 'list'], ['Logo', 'logo'], ['Header', 'header'], ['Footer', 'footer'], ['Page #', 'pageNumber'], ['Watermark', 'watermark'], ['Table', 'table'], ['Signature', 'signature'], ['Page break', 'pageBreak'],
                ].map(([label, kind]) => <button key={kind} className="rounded-lg border border-white/10 px-3 py-2 text-xs text-white/70 hover:border-gold hover:text-gold" disabled={!selected || busy} onClick={() => insertPremiumBlock(kind)}>{label}</button>)}
                <button className="rounded-lg border border-white/10 px-3 py-2 text-xs text-white/70 hover:border-gold" onClick={addComment}>Σχόλιο</button>
                <button className="rounded-lg border border-white/10 px-3 py-2 text-xs text-white/70 hover:border-gold" disabled={!history.past.length} onClick={undoEditor}>Αναίρεση</button>
                <button className="rounded-lg border border-white/10 px-3 py-2 text-xs text-white/70 hover:border-gold" disabled={!history.future.length} onClick={redoEditor}>Επανάληψη</button>
                <label className="ml-auto flex items-center gap-2 text-xs text-white/60">Μεγέθυνση<input type="range" min="60" max="130" value={page.zoom} onChange={(e) => setPage({ ...page, zoom: Number(e.target.value) })} /></label>
                <button className="rounded-lg border border-white/10 px-3 py-2 text-xs text-white/70 hover:border-gold" onClick={() => setPage({ ...page, zoom: 85 })}>Fit page</button>
                <button className="rounded-lg border border-white/10 px-3 py-2 text-xs text-white/70 hover:border-gold" onClick={() => setPage({ ...page, zoom: normalizedPageLayout.orientation === 'landscape' ? 80 : 100 })}>Fit width</button>
                <button className="rounded-lg border border-gold/30 bg-gold/10 px-3 py-2 text-xs text-gold hover:border-gold" onClick={() => setPrintPreview((value) => !value)}>{printPreview ? 'Return to editing' : 'Print preview'}</button>
              </div>
            </div>
            <div className="grid gap-2 rounded-2xl border border-white/10 bg-black/20 p-3 text-xs text-white/60 md:grid-cols-4">
              <b className="text-gold md:col-span-4">Page Setup</b>
              <span>Pages: {pageFlow.pageCount}</span>
              <span>Paper: {normalizedPageLayout.size} · {normalizedPageLayout.orientation}</span>
              <span>Size: {Math.round(activePageDimensions.width)} × {Math.round(activePageDimensions.height)} mm</span>
              <span>Zoom: {page.zoom}%</span>
              {['top', 'right', 'bottom', 'left'].map((side) => <label key={side} className="flex items-center gap-2 capitalize">{side}<input className="field py-1" type="number" min="5" max="50" value={normalizedPageLayout.margins[side]} onChange={(e) => updatePageLayout((current) => ({ ...current, margins: { ...current.margins, [side]: Number(e.target.value) } }))} /></label>)}
              <label className="flex items-center gap-2"><input type="checkbox" checked={normalizedPageLayout.header.enabled} onChange={(e) => updatePageLayout((current) => ({ ...current, header: { ...current.header, enabled: e.target.checked } }))} />Header enabled</label>
              <label className="flex items-center gap-2"><input type="checkbox" checked={normalizedPageLayout.header.differentFirstPage} onChange={(e) => updatePageLayout((current) => ({ ...current, header: { ...current.header, differentFirstPage: e.target.checked } }))} />First-page header</label>
              <select className="field py-2" value={normalizedPageLayout.header.align} onChange={(e) => updatePageLayout((current) => ({ ...current, header: { ...current.header, align: e.target.value } }))}>{['left', 'center', 'right'].map((x) => <option key={x}>{x}</option>)}</select>
              <label>Header top distance<input className="field mt-1 py-1" type="number" min="0" max="40" value={normalizedPageLayout.header.distanceMm} onChange={(e) => updatePageLayout((current) => ({ ...current, header: { ...current.header, distanceMm: Number(e.target.value) } }))} /></label>
              <label className="md:col-span-2">Header<input className="field mt-1 py-2" value={normalizedPageLayout.header.text} onChange={(e) => updatePageLayout((current) => ({ ...current, header: { ...current.header, text: e.target.value, enabled: true } }))} /></label>
              <label className="md:col-span-2">First-page header<input className="field mt-1 py-2" value={normalizedPageLayout.header.firstPageText} onChange={(e) => updatePageLayout((current) => ({ ...current, header: { ...current.header, firstPageText: e.target.value, differentFirstPage: true, enabled: true } }))} /></label>
              <label className="flex items-center gap-2"><input type="checkbox" checked={normalizedPageLayout.footer.enabled} onChange={(e) => updatePageLayout((current) => ({ ...current, footer: { ...current.footer, enabled: e.target.checked } }))} />Footer enabled</label>
              <label className="flex items-center gap-2"><input type="checkbox" checked={normalizedPageLayout.footer.differentFirstPage} onChange={(e) => updatePageLayout((current) => ({ ...current, footer: { ...current.footer, differentFirstPage: e.target.checked } }))} />First-page footer</label>
              <select className="field py-2" value={normalizedPageLayout.footer.align} onChange={(e) => updatePageLayout((current) => ({ ...current, footer: { ...current.footer, align: e.target.value } }))}>{['left', 'center', 'right'].map((x) => <option key={x}>{x}</option>)}</select>
              <label>Footer bottom distance<input className="field mt-1 py-1" type="number" min="0" max="40" value={normalizedPageLayout.footer.distanceMm} onChange={(e) => updatePageLayout((current) => ({ ...current, footer: { ...current.footer, distanceMm: Number(e.target.value) } }))} /></label>
              <label className="md:col-span-2">Footer<input className="field mt-1 py-2" value={normalizedPageLayout.footer.text} onChange={(e) => updatePageLayout((current) => ({ ...current, footer: { ...current.footer, text: e.target.value, enabled: true } }))} /></label>
              <label className="md:col-span-2">First-page footer<input className="field mt-1 py-2" value={normalizedPageLayout.footer.firstPageText} onChange={(e) => updatePageLayout((current) => ({ ...current, footer: { ...current.footer, firstPageText: e.target.value, differentFirstPage: true, enabled: true } }))} /></label>
              <select className="field py-2" value={normalizedPageLayout.pageNumbers.position} onChange={(e) => updatePageLayout((current) => ({ ...current, pageNumbers: { ...current.pageNumbers, position: e.target.value, enabled: e.target.value !== 'none' } }))}>{PAGE_NUMBER_POSITIONS.map((x) => <option key={x}>{x}</option>)}</select>
              <select className="field py-2" value={normalizedPageLayout.pageNumbers.format} onChange={(e) => updatePageLayout((current) => ({ ...current, pageNumbers: { ...current.pageNumbers, format: e.target.value } }))}>{PAGE_NUMBER_FORMATS.map((x) => <option key={x}>{x}</option>)}</select>
              <input type="color" className="h-10 rounded-xl bg-transparent" value={normalizedPageLayout.background} onChange={(e) => updatePageLayout((current) => ({ ...current, background: e.target.value }))} />
              <label className="flex items-center gap-2"><input type="checkbox" checked={normalizedPageLayout.printBackground} onChange={(e) => updatePageLayout((current) => ({ ...current, printBackground: e.target.checked }))} />Print background</label>
            </div>
            <div className="grid gap-3 rounded-2xl border border-gold/20 bg-black/20 p-3 text-xs text-white/65 md:grid-cols-4">
              <b className="text-gold md:col-span-4">Images & Logo Engine</b>
              <input className="field md:col-span-2" value={imageDraft.src} onChange={(e) => setImageDraft((current) => ({ ...current, src: e.target.value }))} placeholder="HTTPS image, logo URL, or uploaded data image" />
              <input className="field" value={imageDraft.alt} onChange={(e) => setImageDraft((current) => ({ ...current, alt: e.target.value }))} placeholder="Alt text" />
              <input className="field" value={imageDraft.caption} onChange={(e) => setImageDraft((current) => ({ ...current, caption: e.target.value }))} placeholder="Caption" />
              <select className="field py-2" value={imageDraft.role} onChange={(e) => setImageDraft((current) => ({ ...current, role: e.target.value }))}>{['image', 'logo', 'signature', 'seal', 'watermark'].map((x) => <option key={x}>{x}</option>)}</select>
              <select className="field py-2" value={imageDraft.align} onChange={(e) => setImageDraft((current) => ({ ...current, align: e.target.value }))}>{['inline', 'left', 'center', 'right', 'full-width'].map((x) => <option key={x}>{x}</option>)}</select>
              <select className="field py-2" value={imageDraft.shape} onChange={(e) => setImageDraft((current) => ({ ...current, shape: e.target.value }))}>{['square', 'rounded', 'circle', 'stamp'].map((x) => <option key={x}>{x}</option>)}</select>
              <label>Width %<input className="field mt-1 py-1" type="number" min="5" max="100" value={imageDraft.width} onChange={(e) => setImageDraft((current) => ({ ...current, width: Number(e.target.value) }))} /></label>
              <label>Opacity %<input className="field mt-1 py-1" type="number" min="5" max="100" value={imageDraft.opacity} onChange={(e) => setImageDraft((current) => ({ ...current, opacity: Number(e.target.value) }))} /></label>
              <label className="flex items-center gap-2"><input type="checkbox" checked={imageDraft.border} onChange={(e) => setImageDraft((current) => ({ ...current, border: e.target.checked }))} />Border</label>
              <label className="flex items-center gap-2"><input type="checkbox" checked={imageDraft.shadow} onChange={(e) => setImageDraft((current) => ({ ...current, shadow: e.target.checked }))} />Shadow</label>
              <input className="field md:col-span-2" value={imageDraft.link} onChange={(e) => setImageDraft((current) => ({ ...current, link: e.target.value }))} placeholder="Optional HTTPS link" />
              <div className="flex flex-wrap gap-2 md:col-span-4">
                <button className="btn gold" disabled={!selected || busy} onClick={() => insertImageAsset()}>Insert image</button>
                <button className="btn secondary" disabled={!selected || busy} onClick={() => imageInputRef.current?.click()}>Upload image</button>
                <button className="btn secondary" disabled={!selected || busy} onClick={() => insertBrandAsset('logo')}>Insert saved logo</button>
                <button className="btn secondary" disabled={!selected || busy} onClick={() => insertBrandAsset('signature')}>Insert signature</button>
                <button className="btn secondary" disabled={!selected || busy} onClick={() => insertBrandAsset('seal')}>Insert seal</button>
                <input ref={imageInputRef} type="file" className="hidden" accept="image/*" onChange={(event) => { handleImageUpload(event.target.files?.[0]); event.target.value = ''; }} />
              </div>
              <div className="md:col-span-4 text-white/50">Assets in document: {documentImages.length} · Drag-and-drop images directly onto the page; saved logos/signatures/seals come from Company Identity URLs.</div>
            </div>
            <div className="grid gap-3 rounded-2xl border border-gold/20 bg-black/20 p-3 text-xs text-white/65 md:grid-cols-4">
              <b className="text-gold md:col-span-4">Advanced Tables</b>
              <label>Rows<input className="field mt-1 py-1" type="number" min="1" max="100" value={tableDraft.rows} onChange={(e) => setTableDraft((current) => ({ ...current, rows: Number(e.target.value) }))} /></label>
              <label>Columns<input className="field mt-1 py-1" type="number" min="1" max="20" value={tableDraft.columns} onChange={(e) => setTableDraft((current) => ({ ...current, columns: Number(e.target.value) }))} /></label>
              <label>Header rows<input className="field mt-1 py-1" type="number" min="0" max="10" value={tableDraft.headerRows} onChange={(e) => setTableDraft((current) => ({ ...current, headerRows: Number(e.target.value) }))} /></label>
              <label>Width %<input className="field mt-1 py-1" type="number" min="20" max="100" value={tableDraft.width} onChange={(e) => setTableDraft((current) => ({ ...current, width: Number(e.target.value) }))} /></label>
              <input className="field md:col-span-2" value={tableDraft.caption} onChange={(e) => setTableDraft((current) => ({ ...current, caption: e.target.value }))} placeholder="Caption" />
              <select className="field py-2" value={tableDraft.style} onChange={(e) => setTableDraft((current) => ({ ...current, style: e.target.value }))}>{['executive', 'ledger', 'matrix', 'minimal'].map((x) => <option key={x}>{x}</option>)}</select>
              <div className="grid grid-cols-2 gap-2 md:col-span-4">
                <label className="flex items-center gap-2"><input type="checkbox" checked={tableDraft.repeatHeader} onChange={(e) => setTableDraft((current) => ({ ...current, repeatHeader: e.target.checked }))} />Repeat header on pages</label>
                <label className="flex items-center gap-2"><input type="checkbox" checked={tableDraft.bandedRows} onChange={(e) => setTableDraft((current) => ({ ...current, bandedRows: e.target.checked }))} />Banded rows</label>
                <label className="flex items-center gap-2"><input type="checkbox" checked={tableDraft.firstColumn} onChange={(e) => setTableDraft((current) => ({ ...current, firstColumn: e.target.checked }))} />First column headers</label>
                <label className="flex items-center gap-2"><input type="checkbox" checked={tableDraft.totalRow} onChange={(e) => setTableDraft((current) => ({ ...current, totalRow: e.target.checked }))} />Total row</label>
              </div>
              <div className="flex flex-wrap gap-2 md:col-span-4">
                <button className="btn gold" disabled={!selected || busy} onClick={insertAdvancedTable}>Insert advanced table</button>
                <button className="btn secondary" disabled={!selected || busy} onClick={() => setTableDraft({ ...defaultTableDraft, style: 'ledger', caption: 'Financial ledger', columns: 5, totalRow: true })}>Ledger preset</button>
                <button className="btn secondary" disabled={!selected || busy} onClick={() => setTableDraft({ ...defaultTableDraft, style: 'matrix', caption: 'Compliance matrix', rows: 6, columns: 3 })}>Matrix preset</button>
              </div>
              <div className="md:col-span-4 text-white/50">Tables in document: {documentTables.length} · Advanced: {documentTables.filter((table) => table.advanced).length} · Largest grid: {Math.max(0, ...documentTables.map((table) => table.rows))} rows × {Math.max(0, ...documentTables.map((table) => table.columns))} columns.</div>
            </div>
            {(layoutWarning || pageFlow.warning) && <div className="rounded-2xl border border-amber-400/30 bg-amber-500/10 p-3 text-xs text-amber-100">{layoutWarning || pageFlow.warning}</div>}
            <div className="premium-doc-shell document-editor-canvas overflow-x-auto rounded-3xl border border-white/10 bg-neutral-900/70 p-6" onDragOver={(e) => e.preventDefault()} onDrop={handleDrop}>
              <PaginatedDocumentWorkspace
                  document={selected}
                  html={editorHtml}
                  layout={normalizedPageLayout}
                  zoom={page.zoom}
                  editor={lexicalEditor}
                  editorElementRef={editorElementRef}
                  onPageFlowChange={(nextFlow) => {
                    setPageFlow(nextFlow);
                    setLayoutWarning(nextFlow.warning || '');
                  }}
                >
                  <div
                    className="lumina-document lumina-editor-page transition-transform"
                    data-design-profile={luxuryDesign.profile.id}
                    data-document-theme={luxuryDesign.theme.id}
                    data-typography-preset={luxuryDesign.typography.id}
                    data-layout-preset={luxuryDesign.layout.id}
                    style={{
                      ...luxuryCssVariables,
                      color: luxuryDesign.theme.colors.text,
                      fontFamily: luxuryDesign.typography.bodyFont,
                      fontSize: `${luxuryDesign.typography.styles?.body?.fontSize || 11}px`,
                      lineHeight: luxuryDesign.typography.styles?.body?.lineHeight || 1.55,
                    }}
                  >
                    <DocumentRichEditor
                      ref={editorApiRef}
                      html={editorHtml || '<h1>Start typing your document</h1><p>Use the toolbar to format content.</p>'}
                      onHtmlChange={onEditorChange}
                      disabled={busy || !selected || reviewMode === 'viewing'}
                      onEditorReady={setLexicalEditor}
                      onSelectionContextChange={(context) => { setSelectionContext(context); if (context !== 'document') { setRightPanelMode('inspector'); setRightPanelCollapsed(false); } }}
                    />
                  </div>
                </PaginatedDocumentWorkspace>
            </div>
            {comments.length > 0 && <div className="rounded-2xl border border-white/10 bg-black/20 p-4 text-xs text-white/70"><div className="mb-2 font-medium text-white">Σχόλια και Προτάσεις</div>{comments.map((comment) => <div key={comment.id} className="mb-2 rounded-xl border border-white/10 p-3"><div>{comment.text}</div><button className="mt-2 text-gold" onClick={() => setComments((items) => items.map((x) => x.id === comment.id ? { ...x, resolved: !x.resolved } : x))}>{comment.resolved ? 'Επαναφορά' : 'Επίλυση'}</button></div>)}</div>}
            <div className="document-editor-actions flex flex-wrap gap-2">
              <button className="btn gold disabled:opacity-50" disabled={!selected || busy} onClick={() => saveEditor(false)}>Αποθήκευση έκδοσης</button>
              <button className="btn secondary disabled:opacity-50" disabled={!selected || busy} onClick={() => saveEditor(true)}>Αυτόματη αποθήκευση</button>
              <button className="btn secondary disabled:opacity-50" disabled={!selected || busy} onClick={() => lifecycle('submit-review')}>Υποβολή για έλεγχο</button>
              <button className="btn secondary disabled:opacity-50" disabled={!selected || busy} onClick={() => lifecycle('approve')}>Έγκριση</button>
              <button className="btn secondary disabled:opacity-50" disabled={!selected || busy} onClick={() => lifecycle('archive')}>Αρχειοθέτηση</button>
              <button className="btn secondary disabled:opacity-50" disabled={!selected || busy} onClick={() => lifecycle('trash')}>Μεταφορά στον κάδο</button>
              <button className="btn gold" disabled={busy || !selected} onClick={() => operate('executive_quality')}><Sparkles className="h-4 w-4" />Αναβάθμιση σε Επαγγελματική Ποιότητα</button>
              <label className="btn secondary cursor-pointer"><Upload className="h-4 w-4" />Εισαγωγή PDF/DOCX/OCR<input type="file" className="hidden" accept=".pdf,.docx,.txt,.html,.md,image/*" onChange={importFile} /></label>
            </div>
          </Panel>
        </main>
        {rightPanelCollapsed && <button className="right-panel-restore" onClick={() => setRightPanelCollapsed(false)} aria-label="Restore preview panel"><PanelRightOpen size={16} /> Restore preview</button>}
        </ResizablePanel>
        {!rightPanelCollapsed && <PanelResizeHandle className="document-workspace-divider" aria-label="Resize editor and preview"><span /></PanelResizeHandle>}
        {!rightPanelCollapsed && <ResizablePanel defaultSize={40} minSize={30} className="!overflow-visible bg-[#1b1b1b]">

        <aside className="document-right-panel">
          <div className="right-panel-header"><div role="tablist"><button role="tab" aria-selected={rightPanelMode === 'preview'} className={rightPanelMode === 'preview' ? 'is-active' : ''} onClick={() => setRightPanelMode('preview')}>Preview</button><button role="tab" aria-selected={rightPanelMode === 'inspector'} className={rightPanelMode === 'inspector' ? 'is-active' : ''} onClick={() => setRightPanelMode('inspector')}>Inspector</button></div><button onClick={() => setRightPanelCollapsed(true)} aria-label="Collapse preview panel" title="Collapse panel"><PanelRightClose size={16} /></button></div>
          {rightPanelMode === 'preview' ? <Panel className="document-live-preview" title="Live Preview" icon={FileText}>
            <div className="mb-3 flex items-center justify-between text-[10px] uppercase tracking-[.18em] text-white/40"><span>Rendered document</span><span>{pageFlow.pageCount} pages · {page.zoom}%</span></div>
            <div className="document-preview-scroll rounded-xl border border-black/60 bg-[#303030] p-3">
              <PaginatedDocumentWorkspace document={selected} html={editorHtml} layout={normalizedPageLayout} zoom={Math.min(page.zoom, 72)} preview />
            </div>
            <div className="document-preview-actions" aria-label="Preview actions">
              <button className="preview-action-primary" disabled={!selected || busy} onClick={applyDesigner}>Luxury Design</button>
              <button disabled={!selected || busy} onClick={redesign}>Auto Redesign</button>
              <a className={!selected ? 'is-disabled' : ''} href={selected ? documentApi.previewUrl(selected.id) : undefined} target="_blank" rel="noreferrer" aria-disabled={!selected}>Presentation Preview</a>
            </div>
          </Panel> : <DocumentContextInspector context={selectionContext} format={format} pageLayout={normalizedPageLayout} updatePageLayout={updatePageLayout} imageDraft={imageDraft} setImageDraft={setImageDraft} tableDraft={tableDraft} setTableDraft={setTableDraft} onInsertImage={() => insertImageAsset()} onUploadImage={() => imageInputRef.current?.click()} onInsertTable={insertAdvancedTable} onInsertBrandAsset={insertBrandAsset} />}
          <Panel title="Company Identity" icon={ShieldCheck}>
            <div className="text-xs text-white/50">Company database profile automatically populates documents, people, authority, banks, jurisdiction, signatures and compliance metadata.</div>
            <input className="field" value={profile?.company_name || ''} onChange={(e) => setProfile({ ...profile, company_name: e.target.value })} />
            {selected && <div className="rounded-xl border border-white/10 bg-black/20 p-3 text-xs text-white/60 space-y-2">
              <b className="text-white">Document Metadata</b>
              <input className="field" value={selected.category || ''} onChange={(e) => setSelected({ ...selected, category: e.target.value })} placeholder="Category" />
              <input className="field" value={(selected.tags || []).join(', ')} onChange={(e) => setSelected({ ...selected, tags: e.target.value.split(',').map((tag) => tag.trim()).filter(Boolean) })} placeholder="Tags" />
              <input className="field" value={selected.status || 'draft'} onChange={(e) => setSelected({ ...selected, status: e.target.value })} placeholder="Status" />
              <textarea className="field min-h-[70px]" value={JSON.stringify(selected.metadata?.custom || {}, null, 2)} onChange={(e) => { try { setSelected({ ...selected, metadata: { ...(selected.metadata || {}), custom: JSON.parse(e.target.value || '{}') } }); } catch (_) {} }} />
              <button className="btn secondary" disabled={busy} onClick={async () => { const updated = await documentApi.update(selected.id, { category: selected.category, tags: selected.tags, status: selected.status, metadata: selected.metadata }); setSelected(updated); await refreshDocuments(); toast.success('Metadata saved.'); }}>Save metadata</button>
            </div>}
            <div className="grid grid-cols-2 gap-2">
              {['trading_name', 'legal_form', 'jurisdiction', 'registration_number', 'ein_tax_number', 'vat_number', 'registered_office', 'principal_office', 'formation_date', 'status', 'standing', 'capital', 'website', 'phone', 'email'].map((key) => <input key={key} className="field" placeholder={key.replaceAll('_', ' ')} value={profile?.[key] || ''} onChange={(e) => setProfile({ ...profile, [key]: e.target.value })} />)}
            </div>
            <textarea className="field min-h-[72px]" placeholder="Compliance notes" value={profile?.compliance_notes || ''} onChange={(e) => setProfile({ ...profile, compliance_notes: e.target.value })} />
            <div className="rounded-xl border border-white/10 bg-black/20 p-3 text-xs text-white/60"><b>Authorized people</b>{people.slice(0, 4).map((person) => <div key={person.id}>{person.full_name} · {person.role} · {person.authority}</div>)}</div>
            <div className="rounded-xl border border-white/10 bg-black/20 p-3 text-xs text-white/60"><b>Bank accounts</b>{banks.slice(0, 4).map((bank) => <div key={bank.id}>{bank.bank_name} · {bank.swift} · {bank.iban}</div>)}</div>
            <div className="grid grid-cols-3 gap-2">
              {['primary_color', 'secondary_color', 'accent_color'].map((key) => <input key={key} type="color" className="h-12 w-full rounded-xl bg-transparent" value={profile?.[key] || '#B9985A'} onChange={(e) => setProfile({ ...profile, [key]: e.target.value })} />)}
            </div>
            <div className="grid gap-2">
              {['logo_url', 'signature_url', 'seal_url'].map((key) => <input key={key} className="field" placeholder={key.replaceAll('_', ' ')} value={profile?.[key] || ''} onChange={(e) => setProfile({ ...profile, [key]: e.target.value })} />)}
            </div>
            <button className="btn disabled:opacity-50" disabled={!profile || busy} onClick={async () => { const saved = await documentApi.saveProfile(profile); setProfile(saved); toast.success('Η εταιρική ταυτότητα αποθηκεύτηκε.'); }}>Αποθήκευση εταιρικής ταυτότητας</button>
          </Panel>

          <Panel title="Luxury Document Designer" icon={Sparkles}>
            <div className="rounded-2xl border border-gold/30 bg-gold/10 p-4 text-xs text-white/75">
              <div className="font-medium text-white">
                Ζωντανός σχεδιασμός εταιρικών και τραπεζικών εγγράφων
              </div>
              <div className="mt-1 text-white/50">
                Οι αλλαγές εμφανίζονται άμεσα στην προεπισκόπηση.
              </div>
            </div>

            <label className="block text-xs text-white/55">
              Προφίλ εγγράφου
              <select
                className="field mt-1"
                value={luxuryDesigner.profileId}
                onChange={(event) => {
                  const profileId = event.target.value;

                  const defaults = {
                    [DOCUMENT_PROFILE_IDS.WYOMING_LLC]: {
                      themeId: 'executive-gold',
                      typographyPresetId: 'legal',
                      layoutPresetId: 'legal',
                    },
                    [DOCUMENT_PROFILE_IDS.GREEK_IKE]: {
                      themeId: 'corporate-white',
                      typographyPresetId: 'corporate',
                      layoutPresetId: 'corporate',
                    },
                    [DOCUMENT_PROFILE_IDS.BANK_OF_CYPRUS]: {
                      themeId: 'banking-blue',
                      typographyPresetId: 'banking',
                      layoutPresetId: 'banking',
                    },
                    [DOCUMENT_PROFILE_IDS.CORPORATE_GENERAL]: {
                      themeId: 'executive-gold',
                      typographyPresetId: 'executive',
                      layoutPresetId: 'corporate',
                    },
                  };

                  setLuxuryDesigner({
                    profileId,
                    ...(defaults[profileId] || defaults[DOCUMENT_PROFILE_IDS.CORPORATE_GENERAL]),
                  });
                }}
              >
                {luxuryProfileOptions.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="block text-xs text-white/55">
              Πολυτελές θέμα
              <select
                className="field mt-1"
                value={luxuryDesigner.themeId}
                onChange={(event) =>
                  setLuxuryDesigner((current) => ({
                    ...current,
                    themeId: event.target.value,
                  }))
                }
              >
                {luxuryThemeOptions.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="block text-xs text-white/55">
              Τυπογραφία
              <select
                className="field mt-1"
                value={luxuryDesigner.typographyPresetId}
                onChange={(event) =>
                  setLuxuryDesigner((current) => ({
                    ...current,
                    typographyPresetId: event.target.value,
                  }))
                }
              >
                {luxuryTypographyOptions.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="block text-xs text-white/55">
              Διάταξη σελίδας
              <select
                className="field mt-1"
                value={luxuryDesigner.layoutPresetId}
                onChange={(event) =>
                  setLuxuryDesigner((current) => ({
                    ...current,
                    layoutPresetId: event.target.value,
                  }))
                }
              >
                {luxuryLayoutOptions.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <div className="grid grid-cols-3 gap-2">
              <div
                className="h-12 rounded-xl border border-white/10"
                title="Κύριο χρώμα"
                style={{ background: luxuryDesign.theme.colors.primary }}
              />
              <div
                className="h-12 rounded-xl border border-white/10"
                title="Δευτερεύον χρώμα"
                style={{ background: luxuryDesign.theme.colors.secondary }}
              />
              <div
                className="h-12 rounded-xl border border-white/10"
                title="Χρώμα έμφασης"
                style={{ background: luxuryDesign.theme.colors.accent }}
              />
            </div>

            <div className="rounded-xl border border-white/10 bg-black/20 p-3 text-xs text-white/60 space-y-1">
              <div><b>Προφίλ:</b> {luxuryDesign.profile.nameEl}</div>
              <div><b>Θέμα:</b> {luxuryDesign.theme.nameEl}</div>
              <div><b>Τυπογραφία:</b> {luxuryDesign.typography.nameEl}</div>
              <div><b>Διάταξη:</b> {luxuryDesign.layout.nameEl}</div>
              <div>
                <b>Σελίδα:</b> {luxuryPageDimensions.widthMm} × {luxuryPageDimensions.heightMm} mm
              </div>
            </div>

            <div className="rounded-2xl border border-gold/20 bg-black/20 p-3 text-xs text-white/65 space-y-2">
              <b className="text-gold">Design Presets (text-preserving)</b>
              <div className="text-white/45">Apply a curated design preset that changes only the visual style — your document text is protected and never altered.</div>
              <select
                className="field"
                value={selectedPresetId}
                onChange={(e) => setSelectedPresetId(e.target.value)}
              >
                <option value="">— Select a preset —</option>
                {designPresets.map((preset) => (
                  <option key={preset.id} value={preset.id}>{preset.name}</option>
                ))}
              </select>
              <div className="flex flex-wrap gap-2">
                <button
                  className="btn gold disabled:opacity-50"
                  disabled={!selected || busy || presetLoading || !selectedPresetId}
                  onClick={() => redesign(selectedPresetId)}
                >
                  {presetLoading ? 'Εφαρμογή…' : 'Εφαρμογή Preset'}
                </button>
                <button
                  className="btn secondary disabled:opacity-50"
                  disabled={!selected || busy || presetLoading}
                  onClick={() => redesign('')}
                >
                  {presetLoading ? 'Εφαρμογή…' : 'Auto Redesign (legacy)'}
                </button>
              </div>
              {presetMessage && <div className="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-white/70">{presetMessage}</div>}
            </div>

            <button
              className="btn gold disabled:opacity-50"
              disabled={!selected || busy}
              onClick={applyDesigner}
            >
              Εφαρμογή Luxury Design στο έγγραφο
            </button>

            <button
              className="btn gold disabled:opacity-50"
              disabled={!selected || busy}
              onClick={() => redesign('')}
            >
              Αυτόματος επανασχεδιασμός
            </button>

            <a
              className={`btn secondary ${!selected ? 'pointer-events-none opacity-50' : ''}`}
              href={selected ? documentApi.previewUrl(selected.id) : '#'}
              target="_blank"
              rel="noreferrer"
            >
              Προεπισκόπηση παρουσίασης
            </a>
          </Panel>

          <Panel title="Package Builders" icon={FileText}>
            <div className="grid grid-cols-3 gap-2">
              {['proposal', 'banking', 'legal'].map((type) => <button key={type} className="btn secondary capitalize disabled:opacity-50" disabled={busy} onClick={() => buildPackage(type)}>{type}</button>)}
            </div>
            <div className="text-xs text-white/50">Proposal: cover, executive summary, company, scope, deliverables, timeline, pricing, terms, appendices, signature. Banking and legal packages generate complete annexed document suites.</div>
          </Panel>

          <Panel title="Navigation, Find & Proofing" icon={FileText}>
            <div className="rounded-xl border border-white/10 bg-black/20 p-3 text-xs text-white/60">
              <b className="text-white">Document Outline</b>
              {documentOutline.length === 0 && <div className="mt-2 text-white/40">No headings detected.</div>}
              {documentOutline.slice(0, 12).map((item) => <div key={item.id} className="mt-2" style={{ paddingLeft: `${(item.level - 1) * 10}px` }}>H{item.level} · {item.text}</div>)}
            </div>
            <div className="grid gap-2 rounded-xl border border-white/10 bg-black/20 p-3 text-xs text-white/60">
              <b className="text-white">Find & Replace</b>
              <input className="field" value={findReplace.find} onChange={(e) => setFindReplace((current) => ({ ...current, find: e.target.value }))} placeholder="Find text" />
              <input className="field" value={findReplace.replace} onChange={(e) => setFindReplace((current) => ({ ...current, replace: e.target.value }))} placeholder="Replace with" />
              <div>{findPreview.count} match(es)</div>
              <button className="btn secondary" disabled={!selected || busy || !findPreview.count} onClick={replaceAllMatches}>Replace all</button>
            </div>
            <div className="rounded-xl border border-white/10 bg-black/20 p-3 text-xs text-white/60">
              <b className="text-white">Spell Check Foundation</b>
              <div>Checked {spelling.checked} words · {spelling.unknown.length} flagged terms</div>
              <div className="mt-2 flex flex-wrap gap-1">{spelling.unknown.slice(0, 16).map((word) => <span key={word} className="rounded-full border border-amber-400/20 bg-amber-500/10 px-2 py-0.5 text-amber-100">{word}</span>)}</div>
            </div>
          </Panel>

          <Panel title="Review Sidebar" icon={History}>
            <div className="grid gap-2 rounded-xl border border-white/10 bg-black/20 p-3 text-xs text-white/60">
              <div className="flex items-center justify-between"><b className="text-white">Comments & Suggestions</b><span>{reviewState.open_count || 0} open · {reviewState.resolved_count || 0} resolved · {reviewMode}</span></div>
              <select className="field py-2" value={reviewDraft.kind} onChange={(e) => setReviewDraft((current) => ({ ...current, kind: e.target.value }))}>{['comment', 'suggestion'].map((kind) => <option key={kind}>{kind}</option>)}</select>
              <textarea className="field min-h-[70px]" value={reviewDraft.body} onChange={(e) => setReviewDraft((current) => ({ ...current, body: e.target.value }))} placeholder="Review comment or suggestion rationale" />
              <input className="field" value={reviewDraft.suggestion} onChange={(e) => setReviewDraft((current) => ({ ...current, suggestion: e.target.value }))} placeholder="Replacement text for suggestions / tracked changes" />
              <div className="flex flex-wrap gap-2">
                <button className="btn gold" disabled={!selected || busy} onClick={() => createBackendReviewItem(reviewDraft.kind)}>Add review item</button>
                <button className="btn secondary" disabled={!selected || busy} onClick={() => addTrackedChange('replacement')}>Track replacement</button>
                <button className="btn secondary" disabled={!selected || busy} onClick={() => loadReviewWorkspace()}>Refresh review</button>
              </div>
              <div className="max-h-56 overflow-auto space-y-2 pr-1">
                {reviewThreads.length === 0 && <div>No backend review comments yet.</div>}
                {reviewThreads.slice(0, 12).map((thread) => <div key={thread.id} className="rounded-xl border border-white/10 bg-white/[0.03] p-3"><div className="text-white/80">{thread.root.kind} · {thread.root.status} · {thread.replies.length} replies</div><div className="mt-1">{thread.root.body}</div>{thread.root.suggestion?.replacement || thread.root.suggestion?.after ? <div className="mt-1 rounded-lg border border-gold/20 bg-gold/10 p-2 text-gold">Suggestion: {thread.root.suggestion.replacement || thread.root.suggestion.after}</div> : null}<div className="mt-2 flex flex-wrap gap-1">{['resolve', 'reopen', 'accept', 'reject'].map((action) => <button key={action} className="rounded border border-white/10 px-2 py-1 text-white/55 hover:border-gold hover:text-gold" onClick={() => reviewItemAction(thread.root.id, action)}>{action}</button>)}</div></div>)}
              </div>
            </div>
            <div className="rounded-xl border border-white/10 bg-black/20 p-3 text-xs text-white/60">
              <div className="mb-2 flex items-center justify-between"><b className="text-white">Track Changes</b><span>{trackState.pending_count || 0} pending · {trackState.accepted_count || 0} accepted · {trackState.rejected_count || 0} rejected</span></div>
              <div className="mb-2 flex gap-2"><button className="btn secondary" disabled={!selected || busy || !(trackState.changes || []).length} onClick={() => trackChangeAction('accept')}>Accept all</button><button className="btn secondary" disabled={!selected || busy || !(trackState.changes || []).length} onClick={() => trackChangeAction('reject')}>Reject all</button></div>
              <div className="max-h-56 overflow-auto space-y-2 pr-1">
                {(trackState.changes || []).length === 0 && <div>No tracked changes recorded.</div>}
                {(trackState.changes || []).slice(0, 12).map((change) => <div key={change.id} className="rounded-xl border border-white/10 bg-white/[0.03] p-3"><div className="text-white/80">{change.change_type || change.type} · {change.status}</div><div className="mt-1 line-clamp-2">{buildTrackChangePreview(change)}</div><div className="mt-2 flex gap-1"><button className="rounded border border-white/10 px-2 py-1 text-white/55 hover:border-gold hover:text-gold" onClick={() => trackChangeAction('accept', [change.id])}>accept</button><button className="rounded border border-white/10 px-2 py-1 text-white/55 hover:border-gold hover:text-gold" onClick={() => trackChangeAction('reject', [change.id])}>reject</button></div></div>)}
              </div>
            </div>
            <div className="rounded-xl border border-white/10 bg-black/20 p-3 text-xs text-white/60">
              <b className="text-white">Accessibility & Performance</b>
              <div className="mt-2 grid grid-cols-2 gap-2"><span>A11y score: {accessibility.score}</span><span>Words: {performance.words}</span><span>Images: {performance.imageCount}</span><span>Payload: {Math.round(performance.estimatedBytes / 1024)} KB</span></div>
              <div className="mt-2 space-y-1">{[...accessibility.issues.map((issue) => issue.message), ...performance.warnings].slice(0, 6).map((message) => <div key={message} className="rounded-lg border border-amber-400/20 bg-amber-500/10 px-2 py-1 text-amber-100">{message}</div>)}</div>
            </div>
          </Panel>

          <Panel title="Intelligence" icon={Sparkles}>
            <div className="grid grid-cols-2 gap-2">
              {['grammar', 'legal_consistency', 'formatting', 'tone', 'executive_quality', 'duplicates', 'definitions', 'references', 'numbering', 'signature'].map((action) => <button key={action} className="btn secondary disabled:opacity-50" disabled={!selected || busy} onClick={() => runAnalysis(action)}>{action.replaceAll('_', ' ')}</button>)}
            </div>
            <div className="grid grid-cols-2 gap-2">
              {['rewrite', 'improve', 'summarize', 'expand', 'translate', 'continue', 'style', 'merge'].map((operation) => <button key={operation} className="btn secondary disabled:opacity-50" disabled={busy || !selected} onClick={() => operate(operation)}>{operation}</button>)}
            </div>
            {analysis && <div className="rounded-2xl bg-black/30 border border-white/10 p-4 text-sm text-white/70 space-y-3"><p>{analysis.summary}</p><p><b>Missing:</b> {analysis.missing_clauses.join(', ') || 'None'}</p><p><b>Improvements:</b> {analysis.improvements.join(' ')}</p></div>}
            <button className="btn gold disabled:opacity-50" disabled={!selected || busy} onClick={scoreDocument}>Υπολογισμός βαθμολογίας ποιότητας</button>
            <button className="btn gold disabled:opacity-50" disabled={!selected || busy} onClick={runLegalReview}>Εκτέλεση νομικού ελέγχου</button>
            {quality && <div className="rounded-2xl bg-black/30 border border-white/10 p-4 text-xs text-white/70 grid grid-cols-2 gap-2">{Object.entries(quality).map(([k, v]) => <div key={k}><b>{k}:</b> {Array.isArray(v) ? v.join(', ') || 'None' : v}</div>)}</div>}
            {selected?.metadata?.self_validation && <div className="rounded-2xl bg-emerald-500/10 border border-emerald-400/30 p-4 text-xs text-white/70"><b>Επικύρωση:</b> {selected.metadata.self_validation.passed ? 'Επιτυχής' : 'Αποτυχία'} · Class {selected.metadata.document_class?.label} · Prompt leakage {selected.metadata.self_validation.prompt_leak ? 'εντοπίστηκε' : 'κανένα'}</div>}
            {selected?.metadata?.legal_review && <div className={`rounded-2xl border p-4 text-xs text-white/70 ${selected.metadata.legal_review.passed ? 'bg-emerald-500/10 border-emerald-400/30' : 'bg-red-500/10 border-red-400/30'}`}><b>Legal Review:</b> {selected.metadata.legal_review.passed ? 'Passed' : 'Rejected'}<div>{(selected.metadata.legal_review.issues || []).map((issue) => issue.message).join(' ')}</div></div>}
          </Panel>

          <Panel title="Clause Library" icon={FileText}>
            <div className="max-h-72 space-y-2 overflow-auto pr-1">
              {clauses.map((clause) => <button key={clause.id} className="w-full rounded-xl border border-white/10 bg-white/[0.03] p-3 text-left text-xs text-white/70 hover:border-gold" disabled={!selected || busy} onClick={() => insertClause(clause.id)}><b>{clause.category} · {clause.title}</b><div className="mt-1 line-clamp-2 text-white/45">{clause.body}</div></button>)}
            </div>
          </Panel>

          <Panel title="Exports & Versions" icon={History}>
            <div className="grid grid-cols-3 gap-2">
              {EXPORT_FORMATS.map((format) => <button key={format} className="btn secondary disabled:opacity-50" disabled={!selected || busy} onClick={() => download(format)}><Download className="h-4 w-4" />{format === 'markdown' ? 'MD' : format.toUpperCase()}</button>)}
            </div>
            <div className="grid grid-cols-3 gap-2"><button className="btn secondary" disabled={!selected} onClick={() => window.print()}>Εκτύπωση</button><button className="btn secondary" disabled={!selected} onClick={() => selected && window.open(`mailto:?subject=${encodeURIComponent(selected.title)}&body=${encodeURIComponent('LUMINA document ready for review.')}`)}>Αποστολή email</button><button className="btn secondary" disabled={!selected} onClick={() => navigator.clipboard?.writeText(documentApi.previewUrl(selected.id)).then(() => toast.success('Ο σύνδεσμος κοινοποίησης αντιγράφηκε.'))}>Κοινοποίηση</button></div>
            <button className="btn secondary disabled:opacity-50" disabled={!selected || busy} onClick={() => selected && toggleFavorite(selected)}><Heart className="h-4 w-4" />{selected?.favorite ? 'Αφαίρεση από αγαπημένα' : 'Προσθήκη στα αγαπημένα'}</button>
            <button className="btn secondary disabled:opacity-50" disabled={!selected || documents.length < 2 || busy} onClick={compareWithFirstOther}>Παράλληλη σύγκριση</button>
            <button className="btn secondary disabled:opacity-50" disabled={!selected || !versionSummary.latest || busy} onClick={compareWithLatestVersion}>Compare latest version</button>
            {compareResult && <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3 text-xs"><div>Insertions: {compareResult.insertions.slice(0, 12).join(', ')}</div><div>Deletions: {compareResult.deletions.slice(0, 12).join(', ')}</div><div>Formatting: {JSON.stringify(compareResult.formatting_changes)}</div></div>}
            <div className="rounded-xl border border-white/10 bg-black/20 p-3 text-xs text-white/60"><b className="text-white">Version History</b><div>Versions: {versionSummary.count} · Named: {versionSummary.named} · Restorable: {versionSummary.restorable}</div><div>Latest: {versionSummary.latest?.change_note || 'None loaded'}</div></div>
            <div className="rounded-xl border border-white/10 bg-black/20 p-3 text-xs text-white/60">
              <div className="mb-2 font-medium text-white">Activity Timeline</div>
              {activity.length === 0 && <div>No activity loaded.</div>}
              {activity.slice(0, 12).map((event, index) => (
                <div key={`${event.version_id || event.at || index}-${index}`} className="border-b border-white/10 py-2 last:border-b-0">
                  <div className="text-white/80">{event.type || 'activity'} · {event.action || 'updated'}</div>
                  <div>{event.at || event.created_at || ''} · {event.actor || 'owner'}{event.version_number ? ` · v${event.version_number}` : ''}</div>
                </div>
              ))}
            </div>
            <div className="space-y-2 overflow-visible">
              {versions.length === 0 && <EmptyState title="No versions loaded" text="Select a document or save a version." />}
              {versions.map((version) => <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3 text-xs space-y-2" key={version.id}><div className="text-white">Version {version.version_number}</div><div className="text-white/50">{version.change_note}</div><div className="flex flex-wrap gap-1">{['restore', 'rename', 'duplicate', 'delete'].map((action) => <button key={action} disabled={busy} className="rounded border border-white/10 px-2 py-1 capitalize text-white/60 transition hover:border-gold hover:text-gold disabled:opacity-40" onClick={() => versionAction(version, action)}>{action}</button>)}</div></div>)}
            </div>
          </Panel>
        </aside>
        </ResizablePanel>}
        </PanelGroup>
      </div>
      {toolCenterOpen && <div className="document-tool-drawer" role="dialog" aria-modal="true" aria-label="Document tools"><div className="tool-drawer-header"><div><strong>Document tools</strong><span>Choose a focused property panel.</span></div><button onClick={() => setToolCenterOpen(false)} aria-label="Close document tools"><X size={18} /></button></div><div className="tool-drawer-content"><p>Advanced settings are available without interrupting the document canvas.</p><div className="tool-drawer-grid">{[['Page setup', 'document'], ['Text formatting', 'text'], ['Images & brand assets', 'image'], ['Tables', 'table'], ['Header & footer', 'header-footer']].map(([label, context]) => <button key={context} onClick={() => { setToolCenterOpen(false); showInspector(context); }}>{label}</button>)}</div></div></div>}
      </div>
    </div>
  );
}

function Metric({ label, value }) {
  return <div className="rounded-2xl border border-white/10 bg-black/20 px-6 py-4"><div className="text-2xl text-gold font-display">{value}</div><div className="text-[10px] uppercase tracking-[0.22em] text-white/45">{label}</div></div>;
}

function Panel({ title, icon: Icon, children, className = '' }) {
  return <section className={`rounded-xl border border-white/10 bg-[#202020] p-4 shadow-xl ${className}`}><div className="mb-3 flex items-center gap-2 border-b border-white/10 pb-2"><Icon className="h-4 w-4 shrink-0 text-gold" /><h2 className="text-sm font-medium leading-tight text-white/85">{title}</h2></div><div className="panel-body space-y-3">{children}</div></section>;
}

function EmptyState({ title, text }) {
  return <div className="rounded-2xl border border-dashed border-white/10 bg-black/20 p-4 text-center"><div className="text-sm text-white/70">{title}</div><div className="mt-1 text-xs text-white/40">{text}</div></div>;
}

const DOCUMENT_CLASS_TRANSLATIONS = {
  'Certificate of Authority': 'Πιστοποιητικό Εκπροσώπησης',
  'Certificate of Incumbency': 'Πιστοποιητικό Εταιρικής Σύνθεσης',
  'Corporate Resolution': 'Εταιρική Απόφαση',
  'Board Resolution': 'Απόφαση Διοικητικού Συμβουλίου',
  'Shareholders Resolution': 'Απόφαση Μετόχων / Εταίρων',
  'Banking Cover Letter': 'Συνοδευτική Επιστολή προς Τράπεζα',
  'AML Declaration': 'Δήλωση AML',
  'UBO Declaration': 'Δήλωση Πραγματικού Δικαιούχου',
  'KYC Declaration': 'Δήλωση KYC',
  'Source of Funds Declaration': 'Δήλωση Προέλευσης Κεφαλαίων',
  'Company Profile': 'Εταιρικό Προφίλ',
  'Invoice': 'Τιμολόγιο',
  'Proforma Invoice': 'Προτιμολόγιο',
  'Consulting Agreement': 'Σύμβαση Συμβουλευτικών Υπηρεσιών',
  'Agency Agreement': 'Σύμβαση Αντιπροσώπευσης',
  'Commission Agreement': 'Σύμβαση Προμήθειας',
  'NDA': 'Συμφωνία Εμπιστευτικότητας (NDA)',
  'NCNDA': 'Συμφωνία NCNDA',
  'IMFPA': 'Συμφωνία IMFPA',
  'Fee Protection Agreement': 'Συμφωνία Προστασίας Αμοιβής',
  'Power of Attorney': 'Πληρεξούσιο',
  'Affidavit': 'Ένορκη Δήλωση',
  'Memorandum': 'Υπόμνημα',
  'Compliance Letter': 'Επιστολή Συμμόρφωσης',
};

function translateDocumentClass(value) {
  return DOCUMENT_CLASS_TRANSLATIONS[value] || value || '';
}

function templatePayloadClasses(_templates, preview) {
  const backendValues = [
    'Certificate of Authority',
    'Certificate of Incumbency',
    'Corporate Resolution',
    'Board Resolution',
    'Shareholders Resolution',
    'Banking Cover Letter',
    'AML Declaration',
    'UBO Declaration',
    'KYC Declaration',
    'Source of Funds Declaration',
    'Company Profile',
    'Invoice',
    'Proforma Invoice',
    'Consulting Agreement',
    'Agency Agreement',
    'Commission Agreement',
    'NDA',
    'NCNDA',
    'IMFPA',
    'Fee Protection Agreement',
    'Power of Attorney',
    'Affidavit',
    'Memorandum',
    'Compliance Letter',
  ];

  const values = [
    preview?.document_class?.label,
    ...backendValues,
  ]
    .filter(Boolean)
    .filter((value, index, array) => array.indexOf(value) === index);

  return values.map((value) => ({
    value,
    label: translateDocumentClass(value),
  }));
}
