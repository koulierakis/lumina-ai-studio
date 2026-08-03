
export const PAGE_SIZE_IDS = Object.freeze({
  A4: "a4",
  LETTER: "letter",
  LEGAL: "legal",
});

export const ORIENTATION_IDS = Object.freeze({
  PORTRAIT: "portrait",
  LANDSCAPE: "landscape",
});

export const LAYOUT_PRESET_IDS = Object.freeze({
  CORPORATE: "corporate",
  BANKING: "banking",
  LEGAL: "legal",
  EXECUTIVE: "executive",
  COMPACT: "compact",
  NOTARY: "notary",
});

export const PAGE_SIZES = Object.freeze({
  [PAGE_SIZE_IDS.A4]: {
    id: PAGE_SIZE_IDS.A4,
    name: "A4",
    widthMm: 210,
    heightMm: 297,
  },

  [PAGE_SIZE_IDS.LETTER]: {
    id: PAGE_SIZE_IDS.LETTER,
    name: "Letter",
    widthMm: 215.9,
    heightMm: 279.4,
  },

  [PAGE_SIZE_IDS.LEGAL]: {
    id: PAGE_SIZE_IDS.LEGAL,
    name: "Legal",
    widthMm: 215.9,
    heightMm: 355.6,
  },
});

const BASE_HEADER = Object.freeze({
  enabled: true,
  heightMm: 16,
  showLogo: true,
  showCompanyName: true,
  showDocumentTitle: false,
  showVersion: false,
  showDate: false,
  showConfidentiality: true,
  alignment: "space-between",
  borderBottom: true,
  borderWidth: 0.5,
});

const BASE_FOOTER = Object.freeze({
  enabled: true,
  heightMm: 14,
  showCompanyName: true,
  showDocumentTitle: false,
  showConfidentiality: true,
  showPageNumber: true,
  showTotalPages: true,
  showVersion: false,
  alignment: "space-between",
  borderTop: true,
  borderWidth: 0.5,
});

const BASE_COVER = Object.freeze({
  enabled: true,
  separatePage: true,
  showLogo: true,
  showCompanyName: true,
  showTitle: true,
  showSubtitle: true,
  showDate: true,
  showVersion: true,
  showConfidentiality: true,
  showPreparedFor: true,
  showPreparedBy: true,
  verticalAlignment: "center",
});

const BASE_NUMBERING = Object.freeze({
  pageNumbers: true,
  pageNumberStart: 1,
  includeCover: false,
  sectionNumbers: true,
  headingNumbers: true,
  tableNumbers: true,
  figureNumbers: true,
  annexNumbers: true,
  pageFormat: "Page {page} of {total}",
});

const BASE_PRINT = Object.freeze({
  printBackground: true,
  avoidPageBreakInside: true,
  orphans: 3,
  widows: 3,
  bleedMm: 0,
  cropMarks: false,
  grayscaleSafe: true,
});

function createLayoutPreset({
  id,
  name,
  nameEl,
  pageSize = PAGE_SIZE_IDS.A4,
  orientation = ORIENTATION_IDS.PORTRAIT,
  margins,
  header,
  footer,
  cover,
  numbering,
  print,
  columns = 1,
  columnGapMm = 8,
  pageGapPx = 24,
  contentMaxWidthMm,
} = {}) {
  return {
    id,
    name,
    nameEl,
    page: {
      size: pageSize,
      orientation,
      margins: {
        top: 22,
        right: 20,
        bottom: 22,
        left: 20,
        ...(margins || {}),
      },
      columns,
      columnGapMm,
      pageGapPx,
      contentMaxWidthMm,
    },
    header: {
      ...BASE_HEADER,
      ...(header || {}),
    },
    footer: {
      ...BASE_FOOTER,
      ...(footer || {}),
    },
    cover: {
      ...BASE_COVER,
      ...(cover || {}),
    },
    numbering: {
      ...BASE_NUMBERING,
      ...(numbering || {}),
    },
    print: {
      ...BASE_PRINT,
      ...(print || {}),
    },
  };
}

export const LAYOUT_PRESETS = Object.freeze({
  [LAYOUT_PRESET_IDS.CORPORATE]: createLayoutPreset({
    id: LAYOUT_PRESET_IDS.CORPORATE,
    name: "Corporate",
    nameEl: "Εταιρικό",
    margins: {
      top: 22,
      right: 20,
      bottom: 22,
      left: 20,
    },
    header: {
      heightMm: 15,
      showDocumentTitle: true,
    },
    footer: {
      heightMm: 13,
      showVersion: true,
    },
  }),

  [LAYOUT_PRESET_IDS.BANKING]: createLayoutPreset({
    id: LAYOUT_PRESET_IDS.BANKING,
    name: "Banking",
    nameEl: "Τραπεζικό",
    margins: {
      top: 24,
      right: 21,
      bottom: 24,
      left: 21,
    },
    header: {
      heightMm: 17,
      showDocumentTitle: true,
      showDate: true,
    },
    footer: {
      heightMm: 14,
      showVersion: true,
      showConfidentiality: true,
    },
    cover: {
      verticalAlignment: "start",
    },
  }),

  [LAYOUT_PRESET_IDS.LEGAL]: createLayoutPreset({
    id: LAYOUT_PRESET_IDS.LEGAL,
    name: "Legal",
    nameEl: "Νομικό",
    margins: {
      top: 25,
      right: 25,
      bottom: 25,
      left: 28,
    },
    header: {
      heightMm: 14,
      showLogo: false,
      showCompanyName: true,
      showDocumentTitle: true,
    },
    footer: {
      heightMm: 13,
      showCompanyName: false,
      showDocumentTitle: true,
    },
    cover: {
      verticalAlignment: "center",
    },
  }),

  [LAYOUT_PRESET_IDS.EXECUTIVE]: createLayoutPreset({
    id: LAYOUT_PRESET_IDS.EXECUTIVE,
    name: "Executive",
    nameEl: "Executive",
    margins: {
      top: 23,
      right: 22,
      bottom: 23,
      left: 22,
    },
    header: {
      heightMm: 18,
      showLogo: true,
      showCompanyName: true,
      showDocumentTitle: false,
    },
    footer: {
      heightMm: 14,
      showVersion: true,
    },
    cover: {
      verticalAlignment: "center",
    },
  }),

  [LAYOUT_PRESET_IDS.COMPACT]: createLayoutPreset({
    id: LAYOUT_PRESET_IDS.COMPACT,
    name: "Compact",
    nameEl: "Συμπαγές",
    margins: {
      top: 16,
      right: 16,
      bottom: 16,
      left: 16,
    },
    header: {
      heightMm: 12,
    },
    footer: {
      heightMm: 11,
    },
    cover: {
      enabled: false,
    },
    pageGapPx: 16,
  }),

  [LAYOUT_PRESET_IDS.NOTARY]: createLayoutPreset({
    id: LAYOUT_PRESET_IDS.NOTARY,
    name: "Notary",
    nameEl: "Συμβολαιογραφικό",
    margins: {
      top: 28,
      right: 28,
      bottom: 28,
      left: 30,
    },
    header: {
      heightMm: 12,
      showLogo: false,
      showCompanyName: false,
      showDocumentTitle: false,
      showConfidentiality: false,
      borderBottom: false,
    },
    footer: {
      heightMm: 12,
      showCompanyName: false,
      showDocumentTitle: false,
      showConfidentiality: false,
      borderTop: false,
    },
    cover: {
      enabled: false,
    },
  }),
});

export const DEFAULT_LAYOUT_PRESET_ID =
  LAYOUT_PRESET_IDS.CORPORATE;

export function getPageSize(
  pageSizeId = PAGE_SIZE_IDS.A4
) {
  return (
    PAGE_SIZES[pageSizeId] ||
    PAGE_SIZES[PAGE_SIZE_IDS.A4]
  );
}

export function getLayoutPreset(
  presetId = DEFAULT_LAYOUT_PRESET_ID
) {
  return (
    LAYOUT_PRESETS[presetId] ||
    LAYOUT_PRESETS[DEFAULT_LAYOUT_PRESET_ID]
  );
}

export function getLayoutPresetOptions(language = "el") {
  return Object.values(LAYOUT_PRESETS).map((preset) => ({
    id: preset.id,
    label:
      language === "el"
        ? preset.nameEl
        : preset.name,
  }));
}

export function resolvePageDimensions({
  size = PAGE_SIZE_IDS.A4,
  orientation = ORIENTATION_IDS.PORTRAIT,
} = {}) {
  const pageSize = getPageSize(size);

  if (orientation === ORIENTATION_IDS.LANDSCAPE) {
    return {
      widthMm: pageSize.heightMm,
      heightMm: pageSize.widthMm,
    };
  }

  return {
    widthMm: pageSize.widthMm,
    heightMm: pageSize.heightMm,
  };
}

export function resolveLayout({
  presetId = DEFAULT_LAYOUT_PRESET_ID,
  page = {},
  header = {},
  footer = {},
  cover = {},
  numbering = {},
  print = {},
} = {}) {
  const preset = getLayoutPreset(presetId);

  return {
    ...preset,
    page: {
      ...preset.page,
      ...page,
      margins: {
        ...preset.page.margins,
        ...(page.margins || {}),
      },
    },
    header: {
      ...preset.header,
      ...header,
    },
    footer: {
      ...preset.footer,
      ...footer,
    },
    cover: {
      ...preset.cover,
      ...cover,
    },
    numbering: {
      ...preset.numbering,
      ...numbering,
    },
    print: {
      ...preset.print,
      ...print,
    },
  };
}

export function calculateContentArea(layoutConfig = {}) {
  const layout = resolveLayout(layoutConfig);
  const dimensions = resolvePageDimensions({
    size: layout.page.size,
    orientation: layout.page.orientation,
  });

  const horizontalMargins =
    layout.page.margins.left +
    layout.page.margins.right;

  const verticalMargins =
    layout.page.margins.top +
    layout.page.margins.bottom;

  const headerHeight =
    layout.header.enabled
      ? layout.header.heightMm
      : 0;

  const footerHeight =
    layout.footer.enabled
      ? layout.footer.heightMm
      : 0;

  return {
    pageWidthMm: dimensions.widthMm,
    pageHeightMm: dimensions.heightMm,
    contentWidthMm:
      dimensions.widthMm -
      horizontalMargins,
    contentHeightMm:
      dimensions.heightMm -
      verticalMargins -
      headerHeight -
      footerHeight,
    headerHeightMm: headerHeight,
    footerHeightMm: footerHeight,
  };
}

export function createLayoutCssVariables(
  layoutConfig = {}
) {
  const layout = resolveLayout(layoutConfig);
  const dimensions = resolvePageDimensions({
    size: layout.page.size,
    orientation: layout.page.orientation,
  });

  return {
    "--doc-page-width": `${dimensions.widthMm}mm`,
    "--doc-page-height": `${dimensions.heightMm}mm`,

    "--doc-margin-top":
      `${layout.page.margins.top}mm`,
    "--doc-margin-right":
      `${layout.page.margins.right}mm`,
    "--doc-margin-bottom":
      `${layout.page.margins.bottom}mm`,
    "--doc-margin-left":
      `${layout.page.margins.left}mm`,

    "--doc-header-height":
      `${layout.header.heightMm}mm`,
    "--doc-footer-height":
      `${layout.footer.heightMm}mm`,

    "--doc-column-count":
      String(layout.page.columns),

    "--doc-column-gap":
      `${layout.page.columnGapMm}mm`,

    "--doc-page-gap":
      `${layout.page.pageGapPx}px`,
  };
}

export function layoutToPageStyle(
  layoutConfig = {}
) {
  const layout = resolveLayout(layoutConfig);
  const dimensions = resolvePageDimensions({
    size: layout.page.size,
    orientation: layout.page.orientation,
  });

  return {
    width: `${dimensions.widthMm}mm`,
    minHeight: `${dimensions.heightMm}mm`,
    paddingTop:
      `${layout.page.margins.top}mm`,
    paddingRight:
      `${layout.page.margins.right}mm`,
    paddingBottom:
      `${layout.page.margins.bottom}mm`,
    paddingLeft:
      `${layout.page.margins.left}mm`,
    columnCount: layout.page.columns,
    columnGap:
      `${layout.page.columnGapMm}mm`,
    boxSizing: "border-box",
    position: "relative",
    overflow: "hidden",
    background:
      "var(--doc-background, #ffffff)",
    color:
      "var(--doc-text, #202020)",
  };
}

export function applyLayoutToElement(
  element,
  layoutConfig = {}
) {
  if (!element) {
    return;
  }

  const layout = resolveLayout(layoutConfig);
  const variables =
    createLayoutCssVariables(layoutConfig);
  const style =
    layoutToPageStyle(layoutConfig);

  Object.entries(variables).forEach(
    ([name, value]) => {
      element.style.setProperty(
        name,
        String(value)
      );
    }
  );

  Object.entries(style).forEach(
    ([name, value]) => {
      element.style[name] = value;
    }
  );

  element.dataset.layoutPreset =
    layout.id;

  element.dataset.pageSize =
    layout.page.size;

  element.dataset.orientation =
    layout.page.orientation;
}

export function formatPageNumber(
  format,
  page,
  total
) {
  return String(
    format || "Page {page} of {total}"
  )
    .replace("{page}", String(page))
    .replace("{total}", String(total));
}

export function createPageDescriptor({
  id,
  index = 0,
  type = "content",
  title = "",
  sectionId = null,
  pageNumber = null,
  content = [],
  metadata = {},
} = {}) {
  return {
    id:
      id ||
      `page-${Date.now()}-${index}`,
    index,
    type,
    title,
    sectionId,
    pageNumber,
    content,
    metadata,
  };
}

export function paginateBlocks({
  blocks = [],
  maxHeight = 1000,
  measureBlock,
} = {}) {
  const pages = [];
  let currentPage = [];
  let currentHeight = 0;

  blocks.forEach((block, index) => {
    const measuredHeight =
      typeof measureBlock === "function"
        ? Number(measureBlock(block, index)) || 0
        : Number(block.estimatedHeight) || 100;

    const avoidBreak =
      Boolean(block.avoidPageBreakInside);

    if (
      currentPage.length > 0 &&
      currentHeight + measuredHeight >
        maxHeight
    ) {
      pages.push(currentPage);
      currentPage = [];
      currentHeight = 0;
    }

    if (
      avoidBreak &&
      measuredHeight > maxHeight
    ) {
      pages.push([block]);
      return;
    }

    currentPage.push(block);
    currentHeight += measuredHeight;
  });

  if (currentPage.length > 0) {
    pages.push(currentPage);
  }

  return pages;
}

export function createPrintCss(
  layoutConfig = {}
) {
  const layout = resolveLayout(layoutConfig);
  const dimensions = resolvePageDimensions({
    size: layout.page.size,
    orientation: layout.page.orientation,
  });

  const sizeRule =
    layout.page.orientation ===
    ORIENTATION_IDS.LANDSCAPE
      ? `${dimensions.widthMm}mm ${dimensions.heightMm}mm`
      : layout.page.size.toUpperCase();

  return `
@page {
  size: ${sizeRule};
  margin: 0;
}

@media print {
  html,
  body {
    margin: 0 !important;
    padding: 0 !important;
    background: #ffffff !important;
  }

  .document-page {
    width: ${dimensions.widthMm}mm !important;
    min-height: ${dimensions.heightMm}mm !important;
    page-break-after: always;
    break-after: page;
    box-shadow: none !important;
    margin: 0 !important;
  }

  .document-page:last-child {
    page-break-after: auto;
    break-after: auto;
  }

  .avoid-page-break {
    page-break-inside: avoid;
    break-inside: avoid;
  }

  .page-break-before {
    page-break-before: always;
    break-before: page;
  }

  .page-break-after {
    page-break-after: always;
    break-after: page;
  }

  * {
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }
}
`;
}

export function serializeLayout(
  layoutConfig = {}
) {
  return JSON.stringify(
    resolveLayout(layoutConfig)
  );
}

export function parseLayout(serialized) {
  try {
    return resolveLayout(
      JSON.parse(serialized)
    );
  } catch {
    return resolveLayout();
  }
}

export default {
  pageSizeIds: PAGE_SIZE_IDS,
  orientationIds: ORIENTATION_IDS,
  presetIds: LAYOUT_PRESET_IDS,
  pageSizes: PAGE_SIZES,
  presets: LAYOUT_PRESETS,
  defaultPresetId:
    DEFAULT_LAYOUT_PRESET_ID,
  getPageSize,
  getPreset: getLayoutPreset,
  getPresetOptions:
    getLayoutPresetOptions,
  resolveDimensions:
    resolvePageDimensions,
  resolve: resolveLayout,
  calculateContentArea,
  createCssVariables:
    createLayoutCssVariables,
  pageStyle: layoutToPageStyle,
  applyToElement:
    applyLayoutToElement,
  formatPageNumber,
  createPageDescriptor,
  paginateBlocks,
  createPrintCss,
  serialize: serializeLayout,
  parse: parseLayout,
};
