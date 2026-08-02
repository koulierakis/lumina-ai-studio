import { useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import { Download, FileText, Heart, History, ShieldCheck, Sparkles, Upload, Wand2 } from 'lucide-react';
import { DOCUMENT_CREATION_MODES, DOCUMENT_TYPES, EXPORT_FORMATS, documentApi, documentStats, exportDocumentUrl, makeDocumentDownloadHeaders, summarizeDocument } from '../documents/model';

import DocumentStudioSidebar from "../components/documentstudio/DocumentStudioSidebar";
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

export default function DocumentStudio() {
  const [documents, setDocuments] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [companies, setCompanies] = useState([]);
  const [people, setPeople] = useState([]);
  const [banks, setBanks] = useState([]);
  const [clauses, setClauses] = useState([]);
  const [folders, setFolders] = useState([]);
  const [profile, setProfile] = useState(null);
  const [selected, setSelected] = useState(null);
  const [versions, setVersions] = useState([]);
  const [analysis, setAnalysis] = useState(null);
  const [quality, setQuality] = useState(null);
  const [compareResult, setCompareResult] = useState(null);
  const [filters, setFilters] = useState(initialFilters);
  const [generator, setGenerator] = useState(defaultGenerator);
  const [editorHtml, setEditorHtml] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [statusText, setStatusText] = useState('Ready');
  const [intelligencePreview, setIntelligencePreview] = useState(null);
  const [outlineMode, setOutlineMode] = useState('page');
  const [page, setPage] = useState({ size: 'A4', orientation: 'portrait', zoom: 90, margin: 22, lineHeight: 1.55 });

  const [luxuryDesigner, setLuxuryDesigner] = useState({
    profileId: DOCUMENT_PROFILE_IDS.BANK_OF_CYPRUS,
    themeId: 'banking-blue',
    typographyPresetId: 'banking',
    layoutPresetId: 'banking',
  });
  const [comments, setComments] = useState([]);
  const [history, setHistory] = useState({ past: [], future: [] });
  const editorRef = useRef(null);

  const categories = useMemo(() => [...new Set(templates.map((item) => item.category))], [templates]);

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
    const [templatePayload, profilePayload, companyPayload, peoplePayload, bankPayload, clausePayload, folderPayload, docs] = await Promise.all([
      documentApi.templates(),
      documentApi.profile(),
      documentApi.companies(),
      documentApi.people(),
      documentApi.banks(),
      documentApi.clauses(),
      documentApi.folders(),
      documentApi.list(filters),
    ]);
    setTemplates(templatePayload.templates || []);
    setProfile(profilePayload);
    setCompanies(companyPayload || []);
    setPeople(peoplePayload || []);
    setBanks(bankPayload || []);
    setClauses(clausePayload || templatePayload.clause_library || []);
    setFolders(folderPayload || []);
    setDocuments(docs || []);
    if (!selected && docs?.[0]) {
      setSelected(docs[0]);
      setEditorHtml(docs[0].content_html || '');
      await loadVersions(docs[0]);
    }
    setLoading(false);
  }

  useEffect(() => {
    loadAll().catch((error) => toast.error(error.message || 'Document Studio could not load.'));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function refreshDocuments(nextFilters = filters) {
    const docs = await documentApi.list(nextFilters);
    setDocuments(docs || []);
    return docs || [];
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

  async function saveEditor(autosave = false) {
    if (!selected) return;
    setBusy(true);
    setStatusText(autosave ? 'Autosaving…' : 'Saving version…');
    try {
    const contentText = editorHtml.replace(/<[^>]+>/g, ' ');
    const updated = await documentApi.update(selected.id, { content_html: editorHtml, content_text: contentText, autosave, change_note: autosave ? 'Autosave' : 'Manual editor save' });
    setSelected(updated);
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

  function syncEditorHistory(nextHtml) {
    setHistory((previous) => ({ past: [...previous.past.slice(-80), editorHtml], future: [] }));
    setEditorHtml(nextHtml);
  }

  function onEditorInput() {
    const nextHtml = editorRef.current?.innerHTML || '';
    syncEditorHistory(nextHtml);
  }

  function format(command, value = null) {
    editorRef.current?.focus();
    document.execCommand(command, false, value);
    onEditorInput();
  }

  function insertHtml(markup) {
    editorRef.current?.focus();
    document.execCommand('insertHTML', false, markup);
    onEditorInput();
  }

  function undoEditor() {
    setHistory((previous) => {
      const past = [...previous.past];
      const last = past.pop();
      if (!last) return previous;
      setEditorHtml(last);
      return { past, future: [editorHtml, ...previous.future].slice(0, 80) };
    });
  }

  function redoEditor() {
    setHistory((previous) => {
      const future = [...previous.future];
      const next = future.shift();
      if (!next) return previous;
      setEditorHtml(next);
      return { past: [...previous.past, editorHtml].slice(-80), future };
    });
  }

  function handleDrop(event) {
    event.preventDefault();
    const file = event.dataTransfer.files?.[0];
    if (!file) return;
    if (file.type.startsWith('image/')) {
      const reader = new FileReader();
      reader.onload = () => insertHtml(`<figure style="margin:24px 0"><img src="${reader.result}" style="max-width:100%;border:1px solid #d1d5db"/><figcaption>Inserted image</figcaption></figure>`);
      reader.readAsDataURL(file);
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

  async function redesign() {
    if (!selected) return;
    const updated = await documentApi.redesign(selected.id);
    setSelected(updated); setEditorHtml(updated.content_html || ''); setQuality(updated.quality_score); await refreshDocuments(); await loadVersions(updated); toast.success('Document redesigned without changing meaning.');
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
    setSelected(created); setEditorHtml(created.content_html || ''); setQuality(created.quality_score); await refreshDocuments(); await loadVersions(created); toast.success(`${package_type} package generated.`);
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
    }
    await loadVersions(selected);
    toast.success(`Version ${action} completed: ${result.version_id || version.id}`);
  }

  async function loadVersions(document) {
    const payload = await documentApi.versions(document.id);
    setVersions(payload || []);
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

  return (
    <div className="min-h-screen bg-ink-950 text-white p-4 sm:p-6 lg:p-8 space-y-6">
      <section className="rounded-3xl border border-white/10 bg-gradient-to-br from-white/[0.08] to-gold/10 p-8 shadow-2xl">
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
      </section>

      <div className="grid grid-cols-1 2xl:grid-cols-[360px_1fr_420px] gap-6">
        <DocumentStudioSidebar
          filters={filters}
          setFilters={setFilters}
          categories={categories}
          folders={folders}
          documents={documents}
          loading={loading}
          selectedDocument={selected}
          onSearch={() => refreshDocuments()}
          onCreateFolder={createFolder}
          renameFolder={renameFolder}
          deleteFolder={deleteFolder}
          moveFolder={moveFolder}
          onSelectDocument={(document) => {
            setSelected(document);
            setEditorHtml(document.content_html || "");
            setAnalysis(null);
            setQuality(document.quality_score || null);
            setCompareResult(null);
            loadVersions(document);
          }}
        />

        <main className="space-y-4">
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

          <Panel title={selected ? `Editor · ${selected.title}` : 'Professional Editor'} icon={FileText}>
            <div className="sticky top-0 z-10 -mx-2 rounded-2xl border border-white/10 bg-ink-950/95 p-3 shadow-2xl backdrop-blur">
              <div className="flex flex-wrap items-center gap-2">
                <select className="field max-w-[110px] py-2" value={page.size} onChange={(e) => setPage({ ...page, size: e.target.value })}>{['A4', 'Letter', 'Legal'].map((x) => <option key={x}>{x}</option>)}</select>
                <select className="field max-w-[130px] py-2" value={page.orientation} onChange={(e) => setPage({ ...page, orientation: e.target.value })}>{['portrait', 'landscape'].map((x) => <option key={x}>{x}</option>)}</select>
                <select className="field max-w-[140px] py-2" onChange={(e) => format('fontName', e.target.value)} defaultValue="Inter">{['Inter', 'Georgia', 'Times New Roman', 'Arial', 'Calibri'].map((x) => <option key={x}>{x}</option>)}</select>
                <select className="field max-w-[90px] py-2" onChange={(e) => format('fontSize', e.target.value)} defaultValue="3">{[['2', '10'], ['3', '12'], ['4', '14'], ['5', '18'], ['6', '24']].map(([v, label]) => <option value={v} key={v}>{label}px</option>)}</select>
                {[
                  ['B', () => format('bold')], ['I', () => format('italic')], ['U', () => format('underline')], ['• List', () => format('insertUnorderedList')], ['1. List', () => format('insertOrderedList')], ['Left', () => format('justifyLeft')], ['Center', () => format('justifyCenter')], ['Right', () => format('justifyRight')], ['Indent', () => format('indent')], ['Outdent', () => format('outdent')],
                ].map(([label, action]) => <button key={label} type="button" className="rounded-lg border border-white/10 px-3 py-2 text-xs text-white/70 hover:border-gold hover:text-gold" disabled={!selected || busy} onClick={action}>{label}</button>)}
                <input type="color" title="Text color" className="h-9 w-10 rounded-lg bg-transparent" onChange={(e) => format('foreColor', e.target.value)} />
                <button className="rounded-lg border border-white/10 px-3 py-2 text-xs text-white/70 hover:border-gold" onClick={() => insertHtml('<table style="width:100%;border-collapse:collapse;margin:24px 0"><tr><th style="border:1px solid #d1d5db;padding:8px">Header</th><th style="border:1px solid #d1d5db;padding:8px">Value</th></tr><tr><td style="border:1px solid #d1d5db;padding:8px">Item</td><td style="border:1px solid #d1d5db;padding:8px">TBD</td></tr></table>')}>Πίνακας</button>
                <button className="rounded-lg border border-white/10 px-3 py-2 text-xs text-white/70 hover:border-gold" onClick={() => insertHtml('<div style="break-after:page;page-break-after:always;border-top:1px dashed #B9985A;margin:32px 0"></div>')}>Αλλαγή σελίδας</button>
                <button className="rounded-lg border border-white/10 px-3 py-2 text-xs text-white/70 hover:border-gold" onClick={() => insertHtml('<section><h2>Signature Block</h2><div style="display:grid;grid-template-columns:1fr 1fr;gap:32px;margin-top:48px"><div style="border-top:1px solid #111827;padding-top:8px">Authorized Signatory<br/>Date:</div><div style="border-top:1px solid #111827;padding-top:8px">Initials<br/>Date:</div></div></section>')}>Υπογραφή</button>
                <button className="rounded-lg border border-white/10 px-3 py-2 text-xs text-white/70 hover:border-gold" onClick={addComment}>Σχόλιο</button>
                <button className="rounded-lg border border-white/10 px-3 py-2 text-xs text-white/70 hover:border-gold" disabled={!history.past.length} onClick={undoEditor}>Αναίρεση</button>
                <button className="rounded-lg border border-white/10 px-3 py-2 text-xs text-white/70 hover:border-gold" disabled={!history.future.length} onClick={redoEditor}>Επανάληψη</button>
                <label className="ml-auto flex items-center gap-2 text-xs text-white/60">Μεγέθυνση<input type="range" min="60" max="130" value={page.zoom} onChange={(e) => setPage({ ...page, zoom: Number(e.target.value) })} /></label>
              </div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-black/20 p-3 text-xs text-white/50">Paper: {page.size} · {page.orientation} · {page.zoom}% · drag images/signatures into the page</div>
            <div className="overflow-x-auto rounded-3xl border border-white/10 bg-neutral-900/70 p-6" onDragOver={(e) => e.preventDefault()} onDrop={handleDrop}>
              <div
                className="lumina-document lumina-document-page mx-auto shadow-2xl transition-transform"
                data-design-profile={luxuryDesign.profile.id}
                data-document-theme={luxuryDesign.theme.id}
                data-typography-preset={luxuryDesign.typography.id}
                data-layout-preset={luxuryDesign.layout.id}
                style={{
                  ...luxuryCssVariables,
                  width: `${luxuryPageDimensions.widthMm}mm`,
                  minHeight: `${luxuryPageDimensions.heightMm}mm`,
                  paddingTop: `${luxuryDesign.layout.page.margins.top}mm`,
                  paddingRight: `${luxuryDesign.layout.page.margins.right}mm`,
                  paddingBottom: `${luxuryDesign.layout.page.margins.bottom}mm`,
                  paddingLeft: `${luxuryDesign.layout.page.margins.left}mm`,
                  background: luxuryDesign.theme.colors.background,
                  color: luxuryDesign.theme.colors.text,
                  fontFamily: luxuryDesign.typography.bodyFont,
                  fontSize: `${luxuryDesign.typography.styles?.body?.fontSize || 11}px`,
                  lineHeight: luxuryDesign.typography.styles?.body?.lineHeight || 1.55,
                  border: `${luxuryDesign.theme.page.borderWidth || 1}px solid ${luxuryDesign.theme.colors.accent}`,
                  transform: `scale(${page.zoom / 100})`,
                  transformOrigin: 'top center',
                  marginBottom: `${Math.max(0, page.zoom - 100) * 8}px`,
                  boxSizing: 'border-box',
                }}
              >
                <header
                  contentEditable
                  suppressContentEditableWarning
                  className="mb-8 pb-3 text-xs"
                  style={{
                    minHeight: `${luxuryDesign.layout.header.heightMm}mm`,
                    borderBottom: luxuryDesign.layout.header.borderBottom
                      ? `1px solid ${luxuryDesign.theme.colors.border}`
                      : 'none',
                    color: luxuryDesign.theme.colors.mutedText,
                    fontFamily: luxuryDesign.typography.bodyFont,
                  }}
                >
                  {profile?.company_name || 'Company'} · {selected?.title || 'Untitled'} · Page 1
                </header>
                <article ref={editorRef} contentEditable={!busy && !!selected} suppressContentEditableWarning className="prose prose-neutral max-w-none min-h-[760px] outline-none" onInput={onEditorInput} dangerouslySetInnerHTML={{ __html: editorHtml || '<h1>Start typing your document</h1><p>Use the toolbar to format content.</p>' }} />
                <footer
                  contentEditable
                  suppressContentEditableWarning
                  className="mt-8 pt-3 text-xs"
                  style={{
                    minHeight: `${luxuryDesign.layout.footer.heightMm}mm`,
                    borderTop: luxuryDesign.layout.footer.borderTop
                      ? `1px solid ${luxuryDesign.theme.colors.border}`
                      : 'none',
                    color: luxuryDesign.theme.colors.mutedText,
                    fontFamily: luxuryDesign.typography.bodyFont,
                  }}
                >
                  {luxuryDesign.branding.confidentialLabel} · Page 1 · Document No. {selected?.metadata?.verification_code || 'DRAFT'}
                </footer>
              </div>
            </div>
            {comments.length > 0 && <div className="rounded-2xl border border-white/10 bg-black/20 p-4 text-xs text-white/70"><div className="mb-2 font-medium text-white">Σχόλια και Προτάσεις</div>{comments.map((comment) => <div key={comment.id} className="mb-2 rounded-xl border border-white/10 p-3"><div>{comment.text}</div><button className="mt-2 text-gold" onClick={() => setComments((items) => items.map((x) => x.id === comment.id ? { ...x, resolved: !x.resolved } : x))}>{comment.resolved ? 'Επαναφορά' : 'Επίλυση'}</button></div>)}</div>}
            <div className="flex flex-wrap gap-2">
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

        <aside className="space-y-4">
          <Panel title="Company Identity" icon={ShieldCheck}>
            <div className="text-xs text-white/50">Company database profile automatically populates documents, people, authority, banks, jurisdiction, signatures and compliance metadata.</div>
            <input className="field" value={profile?.company_name || ''} onChange={(e) => setProfile({ ...profile, company_name: e.target.value })} />
            <div className="grid grid-cols-2 gap-2">
              {['trading_name', 'legal_form', 'jurisdiction', 'registration_number', 'ein_tax_number', 'vat_number', 'registered_office', 'principal_office', 'formation_date', 'status', 'standing', 'capital', 'website', 'phone', 'email'].map((key) => <input key={key} className="field" placeholder={key.replaceAll('_', ' ')} value={profile?.[key] || ''} onChange={(e) => setProfile({ ...profile, [key]: e.target.value })} />)}
            </div>
            <textarea className="field min-h-[72px]" placeholder="Compliance notes" value={profile?.compliance_notes || ''} onChange={(e) => setProfile({ ...profile, compliance_notes: e.target.value })} />
            <div className="rounded-xl border border-white/10 bg-black/20 p-3 text-xs text-white/60"><b>Authorized people</b>{people.slice(0, 4).map((person) => <div key={person.id}>{person.full_name} · {person.role} · {person.authority}</div>)}</div>
            <div className="rounded-xl border border-white/10 bg-black/20 p-3 text-xs text-white/60"><b>Bank accounts</b>{banks.slice(0, 4).map((bank) => <div key={bank.id}>{bank.bank_name} · {bank.swift} · {bank.iban}</div>)}</div>
            <div className="grid grid-cols-3 gap-2">
              {['primary_color', 'secondary_color', 'accent_color'].map((key) => <input key={key} type="color" className="h-12 w-full rounded-xl bg-transparent" value={profile?.[key] || '#B9985A'} onChange={(e) => setProfile({ ...profile, [key]: e.target.value })} />)}
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
              onClick={redesign}
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
            {compareResult && <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3 text-xs"><div>Insertions: {compareResult.insertions.slice(0, 12).join(', ')}</div><div>Deletions: {compareResult.deletions.slice(0, 12).join(', ')}</div><div>Formatting: {JSON.stringify(compareResult.formatting_changes)}</div></div>}
            <div className="space-y-2 overflow-visible">
              {versions.length === 0 && <EmptyState title="No versions loaded" text="Select a document or save a version." />}
              {versions.map((version) => <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3 text-xs space-y-2" key={version.id}><div className="text-white">Version {version.version_number}</div><div className="text-white/50">{version.change_note}</div><div className="flex flex-wrap gap-1">{['restore', 'rename', 'duplicate', 'delete'].map((action) => <button key={action} disabled={busy} className="rounded border border-white/10 px-2 py-1 capitalize text-white/60 transition hover:border-gold hover:text-gold disabled:opacity-40" onClick={() => versionAction(version, action)}>{action}</button>)}</div></div>)}
            </div>
          </Panel>
        </aside>
      </div>
    </div>
  );
}

function Metric({ label, value }) {
  return <div className="rounded-2xl border border-white/10 bg-black/20 px-6 py-4"><div className="text-2xl text-gold font-display">{value}</div><div className="text-[10px] uppercase tracking-[0.22em] text-white/45">{label}</div></div>;
}

function Panel({ title, icon: Icon, children }) {
  return <section className="rounded-3xl border border-white/10 bg-white/[0.045] p-5 shadow-xl backdrop-blur-sm"><div className="mb-4 flex items-center gap-3"><Icon className="h-5 w-5 shrink-0 text-gold" /><h2 className="font-display text-xl leading-tight">{title}</h2></div><div className="space-y-3">{children}</div></section>;
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
