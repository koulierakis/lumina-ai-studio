import { ElementNode } from 'lexical';

export function sanitizeEditorHtml(html = '') {
  return String(html || '')
    .replace(/<script[\s\S]*?>[\s\S]*?<\/script>/gi, '')
    .replace(/<style[\s\S]*?>[\s\S]*?<\/style>/gi, '')
    .replace(/\son\w+=("[^"]*"|'[^']*'|[^\s>]+)/gi, '')
    .replace(/javascript:/gi, '');
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

export const DEFAULT_PAGE_LAYOUT = {
  size: 'A4',
  orientation: 'portrait',
  margins: { top: 22, right: 18, bottom: 22, left: 18 },
  background: '#ffffff',
  printBackground: true,
  header: { enabled: true, text: '{{title}}', spacing: 8, firstPageOnly: false },
  footer: { enabled: true, text: '{{date}}', spacing: 8, firstPageOnly: false },
  pageNumbers: { enabled: true, position: 'bottom-center', format: 'Page X of Y' },
};

export function normalizePageLayout(layout = {}) {
  const margins = { ...DEFAULT_PAGE_LAYOUT.margins, ...(layout.margins || {}) };
  const requestedSize = layout.size === 'US Letter' ? 'Letter' : layout.size;
  const size = PAGE_SIZES_MM[requestedSize] ? requestedSize : DEFAULT_PAGE_LAYOUT.size;
  const orientation = layout.orientation === 'landscape' ? 'landscape' : 'portrait';
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
    header: { ...DEFAULT_PAGE_LAYOUT.header, ...(layout.header || {}) },
    footer: { ...DEFAULT_PAGE_LAYOUT.footer, ...(layout.footer || {}) },
    pageNumbers: { ...DEFAULT_PAGE_LAYOUT.pageNumbers, ...(layout.pageNumbers || {}) },
  };
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
  const dimensions = pageDimensions(normalized);
  const bodyHeight = dimensions.height - normalized.margins.top - normalized.margins.bottom - (normalized.header.enabled ? 14 : 0) - (normalized.footer.enabled ? 14 : 0);
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
  if (format === 'X') return String(pageNumber);
  if (format === 'Page X') return `Page ${pageNumber}`;
  return `Page ${pageNumber} of ${pageCount}`;
}

export function renderLayoutText(template = '', document = {}, pageNumber = 1, pageCount = 1) {
  const today = new Date().toISOString().slice(0, 10);
  return String(template || '')
    .replaceAll('{{title}}', document.title || 'Untitled')
    .replaceAll('{{date}}', today)
    .replaceAll('{{page}}', String(pageNumber))
    .replaceAll('{{pages}}', String(pageCount));
}
