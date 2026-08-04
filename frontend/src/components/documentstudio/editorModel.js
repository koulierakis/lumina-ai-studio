import { ElementNode } from 'lexical';

const SAFE_IMAGE_SRC_PATTERN = /^(https?:\/\/|data:image\/(png|jpe?g|gif|webp|svg\+xml);base64,|blob:)/i;

function escapeHtml(value = '') {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function clampNumber(value, fallback, min, max) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(max, Math.max(min, parsed));
}

export function sanitizeEditorHtml(html = '') {
  const source = String(html || '')
    .replace(/<script[\s\S]*?>[\s\S]*?<\/script>/gi, '')
    .replace(/<style[\s\S]*?>[\s\S]*?<\/style>/gi, '')
    .replace(/<(iframe|object|embed|form|meta|link|base)\b[\s\S]*?<\/\1>/gi, '')
    .replace(/<\/?(iframe|object|embed|form|input|button|textarea|select|option|meta|link|base)\b[^>]*>/gi, '')
    .replace(/\son\w+=("[^"]*"|'[^']*'|[^\s>]+)/gi, '')
    .replace(/\ssrcdoc=("[^"]*"|'[^']*'|[^\s>]+)/gi, '')
    .replace(/javascript:/gi, '')
    .replace(/vbscript:/gi, '')
    .replace(/data:text\/html/gi, '')
    .replace(/<img\b([^>]*)>/gi, (match, attributes = '') => {
      const srcMatch = attributes.match(/\ssrc=("([^"]*)"|'([^']*)'|([^\s>]+))/i);
      const src = srcMatch?.[2] || srcMatch?.[3] || srcMatch?.[4] || '';
      if (!SAFE_IMAGE_SRC_PATTERN.test(src)) return '';
      return match;
    });
  return source.replace(/<(a)\b([^>]*)>/gi, (match, tag, attributes = '') => {
    const hrefMatch = attributes.match(/\shref=("([^"]*)"|'([^']*)'|([^\s>]+))/i);
    const href = (hrefMatch?.[2] || hrefMatch?.[3] || hrefMatch?.[4] || '').trim();
    if (href && !/^(https?:|mailto:|tel:|#|\/)/i.test(href)) {
      return `<${tag}${attributes.replace(hrefMatch[0], '')}>`;
    }
    return match;
  });
}

export const IMAGE_WRAP_STYLES = ['inline', 'center', 'left', 'right', 'full-width'];
export const IMAGE_SHAPES = ['square', 'rounded', 'circle', 'stamp'];
export const IMAGE_ROLES = ['image', 'logo', 'signature', 'seal', 'watermark'];

export const DEFAULT_IMAGE_ASSET = {
  src: '',
  alt: '',
  caption: '',
  width: 45,
  align: 'center',
  shape: 'rounded',
  role: 'image',
  opacity: 100,
  border: true,
  shadow: false,
  link: '',
};

export function isSafeImageSource(src = '') {
  return SAFE_IMAGE_SRC_PATTERN.test(String(src || '').trim());
}

export function normalizeImageAsset(asset = {}) {
  const source = { ...DEFAULT_IMAGE_ASSET, ...(asset || {}) };
  const role = IMAGE_ROLES.includes(source.role) ? source.role : DEFAULT_IMAGE_ASSET.role;
  const align = IMAGE_WRAP_STYLES.includes(source.align) ? source.align : DEFAULT_IMAGE_ASSET.align;
  const shape = IMAGE_SHAPES.includes(source.shape) ? source.shape : DEFAULT_IMAGE_ASSET.shape;
  const defaultWidth = role === 'logo' ? 24 : role === 'signature' ? 32 : role === 'seal' ? 22 : DEFAULT_IMAGE_ASSET.width;
  return {
    ...source,
    src: String(source.src || '').trim(),
    alt: String(source.alt || role),
    caption: String(source.caption || ''),
    width: clampNumber(source.width, defaultWidth, 5, 100),
    align,
    shape,
    role,
    opacity: clampNumber(source.opacity, 100, 5, 100),
    border: source.border !== false,
    shadow: Boolean(source.shadow),
    link: String(source.link || '').trim(),
  };
}

function imageFigureStyle(asset) {
  const base = ['margin:18px 0', 'break-inside:avoid', 'page-break-inside:avoid'];
  if (asset.align === 'center') base.push('text-align:center');
  if (asset.align === 'right') base.push('text-align:right');
  if (asset.align === 'left') base.push('text-align:left');
  if (asset.align === 'full-width') base.push('width:100%', 'text-align:center');
  if (asset.align === 'inline') base.push('display:inline-block', 'vertical-align:middle', 'margin:4px 8px');
  if (asset.role === 'watermark') base.push('position:absolute', 'inset:38% auto auto 12%', 'transform:rotate(-28deg)', 'z-index:0', 'pointer-events:none');
  return base.join(';');
}

function imageElementStyle(asset) {
  const width = asset.align === 'full-width' ? 100 : asset.width;
  const base = [`width:${width}%`, 'max-width:100%', 'height:auto', 'object-fit:contain'];
  if (asset.role === 'logo') base.push('max-height:42mm');
  if (asset.role === 'signature') base.push('max-height:28mm');
  if (asset.role === 'seal') base.push('max-height:32mm');
  if (asset.shape === 'rounded') base.push('border-radius:14px');
  if (asset.shape === 'circle') base.push('border-radius:9999px', 'aspect-ratio:1/1');
  if (asset.shape === 'stamp') base.push('border-radius:9999px', 'padding:8px', 'background:#fff');
  if (asset.border) base.push('border:1px solid #d1d5db');
  if (asset.shadow) base.push('box-shadow:0 14px 35px rgba(17,24,39,.18)');
  if (asset.opacity < 100) base.push(`opacity:${asset.opacity / 100}`);
  return base.join(';');
}

export function buildImageFigureHtml(asset = {}) {
  const normalized = normalizeImageAsset(asset);
  if (!isSafeImageSource(normalized.src)) return '';
  const image = `<img src="${escapeHtml(normalized.src)}" alt="${escapeHtml(normalized.alt)}" data-lumina-image-role="${escapeHtml(normalized.role)}" style="${imageElementStyle(normalized)}" />`;
  const linkedImage = normalized.link && /^https?:\/\//i.test(normalized.link) ? `<a href="${escapeHtml(normalized.link)}">${image}</a>` : image;
  const caption = normalized.caption ? `<figcaption style="margin-top:8px;font-size:11px;color:#6b7280;text-align:${normalized.align === 'right' ? 'right' : normalized.align === 'left' ? 'left' : 'center'}">${escapeHtml(normalized.caption)}</figcaption>` : '';
  return `<figure data-lumina-image="true" data-lumina-image-role="${escapeHtml(normalized.role)}" style="${imageFigureStyle(normalized)}">${linkedImage}${caption}</figure>`;
}

export function extractDocumentImages(html = '') {
  const matches = [...String(html || '').matchAll(/<img\b([^>]*)>/gi)];
  return matches.map((match, index) => {
    const attributes = match[1] || '';
    const readAttr = (name) => {
      const attrMatch = attributes.match(new RegExp(`\\s${name}=("([^"]*)"|'([^']*)'|([^\\s>]+))`, 'i'));
      return attrMatch?.[2] || attrMatch?.[3] || attrMatch?.[4] || '';
    };
    return normalizeImageAsset({
      src: readAttr('src'),
      alt: readAttr('alt') || `Image ${index + 1}`,
      role: readAttr('data-lumina-image-role') || 'image',
    });
  }).filter((asset) => isSafeImageSource(asset.src));
}

export const DEFAULT_TABLE_MODEL = {
  rows: 3,
  columns: 3,
  headerRows: 1,
  caption: '',
  style: 'executive',
  width: 100,
  repeatHeader: true,
  bandedRows: true,
  totalRow: false,
  firstColumn: false,
};

export const TABLE_STYLES = ['executive', 'ledger', 'matrix', 'minimal'];

export function normalizeTableModel(model = {}) {
  const source = { ...DEFAULT_TABLE_MODEL, ...(model || {}) };
  const rows = Math.round(clampNumber(source.rows, DEFAULT_TABLE_MODEL.rows, 1, 100));
  const columns = Math.round(clampNumber(source.columns, DEFAULT_TABLE_MODEL.columns, 1, 20));
  const headerRows = Math.round(clampNumber(source.headerRows, DEFAULT_TABLE_MODEL.headerRows, 0, rows));
  return {
    ...source,
    rows,
    columns,
    headerRows,
    caption: String(source.caption || ''),
    style: TABLE_STYLES.includes(source.style) ? source.style : DEFAULT_TABLE_MODEL.style,
    width: clampNumber(source.width, DEFAULT_TABLE_MODEL.width, 20, 100),
    repeatHeader: source.repeatHeader !== false,
    bandedRows: source.bandedRows !== false,
    totalRow: Boolean(source.totalRow),
    firstColumn: Boolean(source.firstColumn),
  };
}

function tablePalette(style) {
  const palettes = {
    executive: { head: '#111827', headText: '#ffffff', border: '#d1d5db', band: '#f9fafb', total: '#f3f4f6' },
    ledger: { head: '#1e3a8a', headText: '#ffffff', border: '#bfdbfe', band: '#eff6ff', total: '#dbeafe' },
    matrix: { head: '#3f3f46', headText: '#ffffff', border: '#d4d4d8', band: '#fafafa', total: '#e4e4e7' },
    minimal: { head: '#ffffff', headText: '#111827', border: '#e5e7eb', band: '#ffffff', total: '#f9fafb' },
  };
  return palettes[style] || palettes.executive;
}

export function buildAdvancedTableHtml(model = {}) {
  const table = normalizeTableModel(model);
  const palette = tablePalette(table.style);
  const cellBase = `border:1px solid ${palette.border};padding:10px 12px;vertical-align:top;line-height:1.45`;
  const caption = table.caption ? `<caption style="caption-side:top;text-align:left;font-weight:700;margin-bottom:8px;color:#111827">${escapeHtml(table.caption)}</caption>` : '';
  const colgroup = `<colgroup>${Array.from({ length: table.columns }, () => `<col style="width:${100 / table.columns}%" />`).join('')}</colgroup>`;
  const headerRows = Array.from({ length: table.headerRows }, (_, rowIndex) => `<tr>${Array.from({ length: table.columns }, (_, columnIndex) => `<th scope="col" style="${cellBase};background:${palette.head};color:${palette.headText};font-weight:700;text-align:left${table.firstColumn && columnIndex === 0 ? ';min-width:28mm' : ''}">Header ${rowIndex + 1}.${columnIndex + 1}</th>`).join('')}</tr>`).join('');
  const bodyRowCount = Math.max(1, table.rows - table.headerRows);
  const bodyRows = Array.from({ length: bodyRowCount }, (_, rowIndex) => {
    const isTotal = table.totalRow && rowIndex === bodyRowCount - 1;
    const background = isTotal ? palette.total : table.bandedRows && rowIndex % 2 === 1 ? palette.band : '#ffffff';
    return `<tr>${Array.from({ length: table.columns }, (_, columnIndex) => {
      const tag = table.firstColumn && columnIndex === 0 ? 'th scope="row"' : 'td';
      const weight = isTotal || (table.firstColumn && columnIndex === 0) ? ';font-weight:700' : '';
      return `<${tag} style="${cellBase};background:${background};color:#111827${weight}">${isTotal ? 'Total' : `Cell ${rowIndex + 1}.${columnIndex + 1}`}</${tag.split(' ')[0]}>`;
    }).join('')}</tr>`;
  }).join('');
  const thead = headerRows ? `<thead style="display:${table.repeatHeader ? 'table-header-group' : 'table-row-group'}">${headerRows}</thead>` : '';
  return `<table data-lumina-table="advanced" data-lumina-table-style="${escapeHtml(table.style)}" style="width:${table.width}%;border-collapse:collapse;margin:24px 0;font-size:13px;break-inside:auto;page-break-inside:auto">${caption}${colgroup}${thead}<tbody>${bodyRows}</tbody></table>`;
}

export function summarizeTables(html = '') {
  return [...String(html || '').matchAll(/<table\b([\s\S]*?)<\/table>/gi)].map((match, index) => ({
    index: index + 1,
    advanced: /data-lumina-table="advanced"/i.test(match[0]),
    rows: (match[0].match(/<tr\b/gi) || []).length,
    columns: Math.max(...(match[0].match(/<tr\b[\s\S]*?<\/tr>/gi) || ['']).map((row) => (row.match(/<(td|th)\b/gi) || []).length), 0),
  }));
}

export function extractDocumentOutline(html = '') {
  return [...String(html || '').matchAll(/<h([1-6])\b[^>]*>([\s\S]*?)<\/h\1>/gi)].map((match, index) => {
    const text = match[2].replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim() || `Heading ${index + 1}`;
    return { id: `outline-${index + 1}`, level: Number(match[1]), text, index };
  });
}

export function findReplacePreview(html = '', query = '') {
  const needle = String(query || '').trim();
  if (!needle) return { count: 0, snippets: [] };
  const text = String(html || '').replace(/<[^>]+>/g, ' ');
  const escaped = needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const regex = new RegExp(escaped, 'gi');
  const matches = [...text.matchAll(regex)];
  return {
    count: matches.length,
    snippets: matches.slice(0, 8).map((match) => text.slice(Math.max(0, match.index - 30), Math.min(text.length, match.index + needle.length + 30)).trim()),
  };
}

export function applyFindReplace(html = '', query = '', replacement = '') {
  const needle = String(query || '').trim();
  if (!needle) return String(html || '');
  const escaped = needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return String(html || '').replace(new RegExp(escaped, 'gi'), String(replacement ?? ''));
}

const COMMON_WORDS = new Set('a about above after again all also an and any are as at be because been before being below between both but by can company contract corporate date document each effective for from further has have if in into is it its law legal may must no not of on or other our page party per professional report shall should signature such than that the their then there these this to under up use version was will with within without you your'.split(' '));

export function spellCheckFoundation(html = '', customWords = []) {
  const allowed = new Set([...COMMON_WORDS, ...customWords.map((word) => String(word).toLowerCase())]);
  const text = String(html || '').replace(/<[^>]+>/g, ' ');
  const words = [...text.matchAll(/\b[A-Za-z][A-Za-z'-]{2,}\b/g)].map((match) => match[0]);
  const unknown = [...new Set(words.filter((word) => !allowed.has(word.toLowerCase()) && !/^[A-Z]{2,}$/.test(word)))].sort((a, b) => a.localeCompare(b));
  return { checked: words.length, unknown: unknown.slice(0, 50), language: 'en' };
}

export function documentAccessibilityAudit(html = '', layout = {}) {
  const source = String(html || '');
  const images = [...source.matchAll(/<img\b([^>]*)>/gi)];
  const headings = extractDocumentOutline(source);
  const tables = summarizeTables(source);
  const issues = [];
  images.forEach((match, index) => {
    if (!/\salt=("[^"]+"|'[^']+'|[^\s>]+)/i.test(match[1] || '')) {
      issues.push({ severity: 'warning', code: 'image-alt', message: `Image ${index + 1} is missing alternative text.` });
    }
  });
  if (!headings.length) issues.push({ severity: 'warning', code: 'headings', message: 'Add headings for screen-reader navigation.' });
  headings.reduce((previous, heading) => {
    if (previous && heading.level - previous.level > 1) {
      issues.push({ severity: 'warning', code: 'heading-order', message: `Heading ${heading.text} skips a level.` });
    }
    return heading;
  }, null);
  if (tables.some((table) => table.rows > 1 && table.columns > 1) && !/<th\b/i.test(source)) {
    issues.push({ severity: 'warning', code: 'table-headers', message: 'Data tables should include header cells.' });
  }
  const normalized = normalizePageLayout(layout);
  if (!normalized.header.enabled && !normalized.footer.enabled) {
    issues.push({ severity: 'info', code: 'page-regions', message: 'Enable headers or footers for exported document context.' });
  }
  return {
    score: Math.max(0, 100 - issues.filter((issue) => issue.severity === 'warning').length * 12 - issues.filter((issue) => issue.severity === 'info').length * 4),
    issues,
    imageCount: images.length,
    headingCount: headings.length,
    tableCount: tables.length,
  };
}

export function documentPerformanceAudit(html = '', pageFlow = {}) {
  const source = String(html || '');
  const text = source.replace(/<[^>]+>/g, ' ');
  const imageCount = (source.match(/<img\b/gi) || []).length;
  const tableCount = (source.match(/<table\b/gi) || []).length;
  const heavyTables = summarizeTables(source).filter((table) => table.rows * table.columns > 400).length;
  const estimatedBytes = new Blob([source]).size;
  const warnings = [];
  if (estimatedBytes > 750_000) warnings.push('Large HTML payload may slow autosave and export.');
  if (imageCount > 40) warnings.push('Many embedded images can increase PDF/DOCX export time.');
  if (heavyTables) warnings.push('Very large tables should be split across sections.');
  if ((pageFlow.pageCount || 1) > 120) warnings.push('Documents over 120 pages may need split-package export.');
  return {
    estimatedBytes,
    words: text.trim() ? text.trim().split(/\s+/).length : 0,
    imageCount,
    tableCount,
    heavyTables,
    pageCount: pageFlow.pageCount || 1,
    warnings,
  };
}

export class PageBreakNode extends ElementNode {
  static getType() {
    return 'page-break';
  }

  static clone(node) {
    return new PageBreakNode(node.__key);
  }

  constructor(key) {
    super(key);
  }

  createDOM(config) {
    const element = document.createElement('div');
    element.setAttribute('data-lumina-page-break', 'true');
    element.className = 'lumina-page-break-marker';
    element.style.borderTop = '1px dashed #B9985A';
    element.style.margin = '24px 0';
    element.style.padding = '8px 0';
    element.style.color = '#B9985A';
    element.style.fontSize = '11px';
    element.style.letterSpacing = '0.12em';
    element.style.textTransform = 'uppercase';
    element.textContent = 'Page break';
    return element;
  }

  updateDOM(prevNode, dom) {
    return false;
  }

  exportJSON() {
    return {
      ...super.exportJSON(),
      type: 'page-break',
      version: 1,
    };
  }

  static importJSON(serializedNode) {
    return createPageBreakNode();
  }

  static importDOM() {
    return {
      div: (node) => {
        if (node instanceof HTMLElement && node.getAttribute('data-lumina-page-break') === 'true') {
          return {
            conversion: () => ({ node: createPageBreakNode() }),
            priority: 0,
          };
        }
        return null;
      },
    };
  }

  exportDOM(editor) {
    return {
      after: (generatedElement) => {
        const element = document.createElement('div');
        element.setAttribute('data-lumina-page-break', 'true');
        element.setAttribute('style', 'break-after:page;page-break-after:always;');
        return { element };
      },
    };
  }

  getTextContent() {
    return '';
  }
}

export function createPageBreakNode() {
  try {
    return new PageBreakNode();
  } catch (error) {
    return {
      getType: () => 'page-break',
      exportJSON: () => ({ type: 'page-break', version: 1 }),
      getTextContent: () => '',
    };
  }
}

export const PAGE_SIZES_MM = {
  A4: { width: 210, height: 297 },
  Letter: { width: 215.9, height: 279.4 },
  'US Letter': { width: 215.9, height: 279.4 },
};

export const PAGE_NUMBER_POSITIONS = ['none', 'top-left', 'top-center', 'top-right', 'bottom-left', 'bottom-center', 'bottom-right'];
export const PAGE_NUMBER_FORMATS = ['1', 'Page 1', 'Page 1 of 5'];
export const PAGE_ALIGNMENTS = ['left', 'center', 'right'];

export const DEFAULT_PAGE_LAYOUT = {
  size: 'A4',
  orientation: 'portrait',
  margins: { top: 22, right: 18, bottom: 22, left: 18 },
  background: '#ffffff',
  printBackground: true,
  header: { enabled: true, text: '{{DOCUMENT_TITLE}}', firstPageText: '', align: 'center', distanceMm: 8, repeat: true, differentFirstPage: false, logoPlaceholder: '' },
  footer: { enabled: true, text: '{{CURRENT_DATE}}', firstPageText: '', align: 'center', distanceMm: 8, repeat: true, differentFirstPage: false },
  pageNumbers: { enabled: true, position: 'bottom-center', format: 'Page 1 of 5' },
};

export function normalizePageLayout(layout = {}) {
  const margins = { ...DEFAULT_PAGE_LAYOUT.margins, ...(layout.margins || {}) };
  const requestedSize = layout.size === 'US Letter' ? 'Letter' : layout.size;
  const size = PAGE_SIZES_MM[requestedSize] ? requestedSize : DEFAULT_PAGE_LAYOUT.size;
  const orientation = layout.orientation === 'landscape' ? 'landscape' : 'portrait';
  const header = normalizeHeaderFooter(layout.header, DEFAULT_PAGE_LAYOUT.header);
  const footer = normalizeHeaderFooter(layout.footer, DEFAULT_PAGE_LAYOUT.footer);
  const rawPageNumbers = { ...DEFAULT_PAGE_LAYOUT.pageNumbers, ...(layout.pageNumbers || {}) };
  const pageNumberPosition = PAGE_NUMBER_POSITIONS.includes(rawPageNumbers.position) ? rawPageNumbers.position : DEFAULT_PAGE_LAYOUT.pageNumbers.position;
  return {
    ...DEFAULT_PAGE_LAYOUT,
    ...layout,
    size,
    orientation,
    margins: {
      top: clampMargin(margins.top, DEFAULT_PAGE_LAYOUT.margins.top),
      right: clampMargin(margins.right, DEFAULT_PAGE_LAYOUT.margins.right),
      bottom: clampMargin(margins.bottom, DEFAULT_PAGE_LAYOUT.margins.bottom),
      left: clampMargin(margins.left, DEFAULT_PAGE_LAYOUT.margins.left),
    },
    background: normalizeColor(layout.background, DEFAULT_PAGE_LAYOUT.background),
    printBackground: layout.printBackground !== false,
    header,
    footer,
    pageNumbers: {
      ...rawPageNumbers,
      enabled: rawPageNumbers.enabled !== false && pageNumberPosition !== 'none',
      position: pageNumberPosition,
      format: normalizePageNumberFormat(rawPageNumbers.format),
    },
  };
}

function normalizeHeaderFooter(value = {}, defaults = {}) {
  const source = { ...defaults, ...(value || {}) };
  const distanceSource = value?.distanceMm ?? value?.spacing ?? defaults.distanceMm;
  return {
    ...source,
    enabled: source.enabled !== false,
    text: String(source.text ?? ''),
    firstPageText: String(source.firstPageText ?? ''),
    align: PAGE_ALIGNMENTS.includes(source.align) ? source.align : defaults.align,
    distanceMm: clampDistance(distanceSource, defaults.distanceMm),
    repeat: source.repeat !== false,
    differentFirstPage: Boolean(source.differentFirstPage || source.firstPageOnly),
    logoPlaceholder: String(source.logoPlaceholder ?? ''),
  };
}

function normalizeColor(value, fallback) {
  const text = String(value || '').trim();
  return /^#[0-9a-f]{3}([0-9a-f]{3})?$/i.test(text) ? text : fallback;
}

function clampDistance(value, fallback) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 0) return fallback;
  return Math.min(40, parsed);
}

function normalizePageNumberFormat(format = '') {
  if (format === 'X') return '1';
  if (format === 'Page X') return 'Page 1';
  if (format === 'Page X of Y') return 'Page 1 of 5';
  return PAGE_NUMBER_FORMATS.includes(format) ? format : DEFAULT_PAGE_LAYOUT.pageNumbers.format;
}

function clampMargin(value, fallback) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) return fallback;
  return Math.min(80, Math.max(5, parsed));
}

export function pageDimensions(layout = {}) {
  const normalized = normalizePageLayout(layout);
  const base = PAGE_SIZES_MM[normalized.size] || PAGE_SIZES_MM.A4;
  return normalized.orientation === 'landscape'
    ? { width: base.height, height: base.width }
    : base;
}

export const MM_TO_PX = 96 / 25.4;

export function mmToPx(mm = 0) {
  return Number(mm || 0) * MM_TO_PX;
}

export function pageContentBox(layout = {}) {
  const normalized = normalizePageLayout(layout);
  const dimensions = pageDimensions(normalized);
  return {
    widthMm: Math.max(20, dimensions.width - normalized.margins.left - normalized.margins.right),
    heightMm: Math.max(20, dimensions.height - normalized.margins.top - normalized.margins.bottom),
    widthPx: mmToPx(Math.max(20, dimensions.width - normalized.margins.left - normalized.margins.right)),
    heightPx: mmToPx(Math.max(20, dimensions.height - normalized.margins.top - normalized.margins.bottom)),
  };
}

export function pageBodyContentBox(layout = {}) {
  const normalized = normalizePageLayout(layout);
  const box = pageContentBox(normalized);
  const headerReserve = normalized.header.enabled ? normalized.header.distanceMm + 8 : 0;
  const footerReserve = normalized.footer.enabled ? normalized.footer.distanceMm + 8 : 0;
  const pageNumberReserve = normalized.pageNumbers.enabled ? 6 : 0;
  return {
    ...box,
    heightMm: Math.max(20, box.heightMm - headerReserve - footerReserve - pageNumberReserve),
    heightPx: mmToPx(Math.max(20, box.heightMm - headerReserve - footerReserve - pageNumberReserve)),
  };
}

export function normalizeLegacyPageBreaks(html = '') {
  return sanitizeEditorHtml(html)
    .replace(/<div([^>]*)page-break-after\s*:\s*always([^>]*)><\/div>/gi, '<div data-lumina-page-break="true"></div>')
    .replace(/<div([^>]*)break-after\s*:\s*page([^>]*)><\/div>/gi, '<div data-lumina-page-break="true"></div>');
}

export function splitHtmlIntoPageBlocks(html = '') {
  const normalized = normalizeLegacyPageBreaks(html);
  const blocks = normalized.match(/<(h[1-6]|p|ul|ol|table|figure|section|div|blockquote)[\s\S]*?<\/\1>/gi) || [normalized];
  return blocks.filter((block) => block.trim()).map((block) => ({
    html: block,
    pageBreak: /data-lumina-page-break="true"|page-break-after\s*:\s*always|break-after\s*:\s*page/i.test(block),
    weight: estimateBlockWeight(block),
  }));
}

export function calculateMeasuredPages({ blockMetrics = [], contentHeightPx = 1, scrollHeightPx = 0 } = {}) {
  const availableHeight = Math.max(1, Number(contentHeightPx) || 1);
  if (!Array.isArray(blockMetrics) || blockMetrics.length === 0) {
    return Math.max(1, Math.ceil((Number(scrollHeightPx) || 0) / availableHeight));
  }

  let pages = 1;
  let used = 0;
  blockMetrics.forEach((metric) => {
    if (metric?.pageBreak) {
      pages += 1;
      used = 0;
      return;
    }
    const height = Math.max(0, Number(metric?.height) || 0);
    if (height > availableHeight) {
      const consumed = Math.ceil(height / availableHeight);
      pages += Math.max(0, consumed - (used > 0 ? 0 : 1));
      used = height % availableHeight;
      if (used === 0) used = availableHeight;
      return;
    }
    if (used > 0 && used + height > availableHeight) {
      pages += 1;
      used = 0;
    }
    used += height;
  });
  return Math.max(pages, Math.ceil((Number(scrollHeightPx) || 0) / availableHeight));
}

export function estimateBlockWeight(block = '') {
  if (/data-lumina-page-break="true"/i.test(block)) return 0;
  if (/<table/i.test(block)) return 10 + (block.match(/<tr/gi)?.length || 1) * 4;
  if (/<figure|<img/i.test(block)) return 18;
  if (/<h1/i.test(block)) return 8;
  if (/<h2|<h3/i.test(block)) return 6;
  const text = block.replace(/<[^>]+>/g, ' ').trim();
  return Math.max(3, Math.ceil(text.length / 120));
}

export function paginateDocumentHtml(html = '', layout = {}) {
  const normalized = normalizePageLayout(layout);
  const bodyHeight = pageBodyContentBox(normalized).heightMm;
  const capacity = Math.max(12, Math.floor(bodyHeight / 4.2));
  const pages = [[]];
  let used = 0;
  splitHtmlIntoPageBlocks(html).forEach((block) => {
    if (block.pageBreak) {
      if (pages[pages.length - 1].length) pages.push([]);
      used = 0;
      return;
    }
    if (used + block.weight > capacity && pages[pages.length - 1].length) {
      pages.push([]);
      used = 0;
    }
    pages[pages.length - 1].push(block.html);
    used += block.weight;
  });
  return pages.map((blocks, index) => ({
    pageNumber: index + 1,
    html: blocks.join('') || '<p></p>',
  }));
}

export function formatPageNumber(format = 'Page X of Y', pageNumber = 1, pageCount = 1) {
  const normalized = normalizePageNumberFormat(format);
  if (normalized === '1') return String(pageNumber);
  if (normalized === 'Page 1') return `Page ${pageNumber}`;
  return `Page ${pageNumber} of ${pageCount}`;
}

export function renderLayoutText(template = '', document = {}, pageNumber = 1, pageCount = 1) {
  document = document || {};
  const today = new Date().toISOString().slice(0, 10);
  return String(template || '')
    .replaceAll('{{DOCUMENT_TITLE}}', (document?.title ?? 'Untitled'))
    .replaceAll('{{CURRENT_DATE}}', today)
    .replaceAll('{{PAGE_NUMBER}}', String(pageNumber))
    .replaceAll('{{TOTAL_PAGES}}', String(pageCount))
    .replaceAll('{{title}}', (document?.title ?? 'Untitled'))
    .replaceAll('{{date}}', today)
    .replaceAll('{{page}}', String(pageNumber))
    .replaceAll('{{pages}}', String(pageCount));
}

export function getPageRegionText(region = {}, document = {}, pageNumber = 1, pageCount = 1) {
  region = region || {};
  document = document || {};
  if (!region.enabled) return '';
  if (!region.repeat && pageNumber > 1) return '';
  const template = region?.differentFirstPage && pageNumber === 1 && region?.firstPageText ? region.firstPageText : (region?.text ?? '');
  return renderLayoutText(template, document, pageNumber, pageCount);
}

export function buildExportLayoutPayload(layout = {}) {
  const normalized = normalizePageLayout(layout);
  return {
    page: {
      size: normalized.size,
      orientation: normalized.orientation,
      margins: normalized.margins,
      background: normalized.background,
      printBackground: normalized.printBackground,
    },
    header: normalized.header,
    footer: normalized.footer,
    pageNumbers: normalized.pageNumbers,
  };
}
