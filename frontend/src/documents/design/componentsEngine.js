
export const COMPONENT_TYPE_IDS = Object.freeze({
  COVER_PAGE: "cover-page",
  SECTION_HEADER: "section-header",
  PARAGRAPH: "paragraph",
  DATA_TABLE: "data-table",
  KEY_VALUE_TABLE: "key-value-table",
  CALLOUT: "callout",
  NOTICE: "notice",
  WARNING: "warning",
  CERTIFICATION: "certification",
  SIGNATURE_BLOCK: "signature-block",
  SIGNATURE_TABLE: "signature-table",
  WATERMARK: "watermark",
  DIVIDER: "divider",
  QUOTE: "quote",
  CHECKLIST: "checklist",
  ANNEX: "annex",
  EXHIBIT: "exhibit",
  PAGE_BREAK: "page-break",
});

export const COMPONENT_VARIANT_IDS = Object.freeze({
  DEFAULT: "default",
  EXECUTIVE: "executive",
  BANKING: "banking",
  LEGAL: "legal",
  MINIMAL: "minimal",
  GOLD: "gold",
  BLUE: "blue",
  EMERALD: "emerald",
  DANGER: "danger",
  SUCCESS: "success",
});

export const ALIGNMENT_IDS = Object.freeze({
  LEFT: "left",
  CENTER: "center",
  RIGHT: "right",
  JUSTIFY: "justify",
});

export const SIGNATURE_LAYOUT_IDS = Object.freeze({
  SINGLE: "single",
  DOUBLE: "double",
  TRIPLE: "triple",
  GRID: "grid",
});

export function createComponent({
  id,
  type,
  variant = COMPONENT_VARIANT_IDS.DEFAULT,
  title = "",
  subtitle = "",
  content = "",
  data = null,
  metadata = {},
  style = {},
  options = {},
} = {}) {
  return {
    id:
      id ||
      `${type || "component"}-${Date.now()}-${Math.random()
        .toString(36)
        .slice(2, 8)}`,
    type,
    variant,
    title,
    subtitle,
    content,
    data,
    metadata,
    style,
    options,
  };
}

export function createCoverPage({
  title = "",
  subtitle = "",
  companyName = "",
  preparedFor = "",
  preparedBy = "",
  date = "",
  version = "",
  confidentiality = "CONFIDENTIAL",
  logoUrl = "",
  sealUrl = "",
  backgroundUrl = "",
  variant = COMPONENT_VARIANT_IDS.EXECUTIVE,
  metadata = {},
} = {}) {
  return createComponent({
    type: COMPONENT_TYPE_IDS.COVER_PAGE,
    variant,
    title,
    subtitle,
    data: {
      companyName,
      preparedFor,
      preparedBy,
      date,
      version,
      confidentiality,
      logoUrl,
      sealUrl,
      backgroundUrl,
    },
    metadata,
    options: {
      separatePage: true,
      verticalAlignment: "center",
    },
  });
}

export function createSectionHeader({
  title = "",
  subtitle = "",
  number = "",
  level = 1,
  variant = COMPONENT_VARIANT_IDS.DEFAULT,
  metadata = {},
} = {}) {
  return createComponent({
    type: COMPONENT_TYPE_IDS.SECTION_HEADER,
    variant,
    title,
    subtitle,
    data: {
      number,
      level,
    },
    metadata,
    options: {
      keepWithNext: true,
      avoidPageBreakInside: true,
    },
  });
}

export function createParagraph({
  content = "",
  alignment = ALIGNMENT_IDS.JUSTIFY,
  variant = COMPONENT_VARIANT_IDS.DEFAULT,
  metadata = {},
  style = {},
} = {}) {
  return createComponent({
    type: COMPONENT_TYPE_IDS.PARAGRAPH,
    variant,
    content,
    metadata,
    style,
    options: {
      alignment,
      allowPageBreak: true,
    },
  });
}

export function createDataTable({
  title = "",
  columns = [],
  rows = [],
  variant = COMPONENT_VARIANT_IDS.BANKING,
  striped = true,
  compact = false,
  repeatHeader = true,
  metadata = {},
} = {}) {
  return createComponent({
    type: COMPONENT_TYPE_IDS.DATA_TABLE,
    variant,
    title,
    data: {
      columns,
      rows,
    },
    metadata,
    options: {
      striped,
      compact,
      repeatHeader,
      avoidPageBreakInside: false,
    },
  });
}

export function createKeyValueTable({
  title = "",
  items = [],
  variant = COMPONENT_VARIANT_IDS.BANKING,
  columns = 2,
  metadata = {},
} = {}) {
  return createComponent({
    type: COMPONENT_TYPE_IDS.KEY_VALUE_TABLE,
    variant,
    title,
    data: {
      items,
    },
    metadata,
    options: {
      columns,
      avoidPageBreakInside: true,
    },
  });
}

export function createCallout({
  title = "",
  content = "",
  icon = "",
  variant = COMPONENT_VARIANT_IDS.GOLD,
  metadata = {},
} = {}) {
  return createComponent({
    type: COMPONENT_TYPE_IDS.CALLOUT,
    variant,
    title,
    content,
    data: {
      icon,
    },
    metadata,
    options: {
      avoidPageBreakInside: true,
    },
  });
}

export function createNotice({
  title = "Notice",
  content = "",
  variant = COMPONENT_VARIANT_IDS.BLUE,
  metadata = {},
} = {}) {
  return createComponent({
    type: COMPONENT_TYPE_IDS.NOTICE,
    variant,
    title,
    content,
    metadata,
    options: {
      avoidPageBreakInside: true,
    },
  });
}

export function createWarning({
  title = "Warning",
  content = "",
  variant = COMPONENT_VARIANT_IDS.DANGER,
  metadata = {},
} = {}) {
  return createComponent({
    type: COMPONENT_TYPE_IDS.WARNING,
    variant,
    title,
    content,
    metadata,
    options: {
      avoidPageBreakInside: true,
    },
  });
}

export function createCertification({
  title = "Certification",
  content = "",
  certifiedBy = "",
  role = "",
  date = "",
  variant = COMPONENT_VARIANT_IDS.LEGAL,
  metadata = {},
} = {}) {
  return createComponent({
    type: COMPONENT_TYPE_IDS.CERTIFICATION,
    variant,
    title,
    content,
    data: {
      certifiedBy,
      role,
      date,
    },
    metadata,
    options: {
      avoidPageBreakInside: true,
    },
  });
}

export function createSignatureBlock({
  name = "",
  role = "",
  company = "",
  date = "",
  signatureUrl = "",
  sealUrl = "",
  label = "Signature",
  variant = COMPONENT_VARIANT_IDS.LEGAL,
  metadata = {},
} = {}) {
  return createComponent({
    type: COMPONENT_TYPE_IDS.SIGNATURE_BLOCK,
    variant,
    data: {
      name,
      role,
      company,
      date,
      signatureUrl,
      sealUrl,
      label,
    },
    metadata,
    options: {
      avoidPageBreakInside: true,
      signatureLine: true,
    },
  });
}

export function createSignatureTable({
  signatories = [],
  layout = SIGNATURE_LAYOUT_IDS.DOUBLE,
  title = "",
  variant = COMPONENT_VARIANT_IDS.LEGAL,
  metadata = {},
} = {}) {
  return createComponent({
    type: COMPONENT_TYPE_IDS.SIGNATURE_TABLE,
    variant,
    title,
    data: {
      signatories,
    },
    metadata,
    options: {
      layout,
      avoidPageBreakInside: true,
    },
  });
}

export function createWatermark({
  text = "CONFIDENTIAL",
  imageUrl = "",
  opacity = 0.08,
  rotation = -35,
  position = "center",
  repeat = false,
  metadata = {},
} = {}) {
  return createComponent({
    type: COMPONENT_TYPE_IDS.WATERMARK,
    data: {
      text,
      imageUrl,
    },
    metadata,
    options: {
      opacity,
      rotation,
      position,
      repeat,
      fixed: true,
    },
  });
}

export function createDivider({
  label = "",
  variant = COMPONENT_VARIANT_IDS.GOLD,
  thickness = 1,
  metadata = {},
} = {}) {
  return createComponent({
    type: COMPONENT_TYPE_IDS.DIVIDER,
    variant,
    data: {
      label,
    },
    metadata,
    options: {
      thickness,
      avoidPageBreakInside: true,
    },
  });
}

export function createQuote({
  content = "",
  author = "",
  source = "",
  variant = COMPONENT_VARIANT_IDS.LEGAL,
  metadata = {},
} = {}) {
  return createComponent({
    type: COMPONENT_TYPE_IDS.QUOTE,
    variant,
    content,
    data: {
      author,
      source,
    },
    metadata,
    options: {
      avoidPageBreakInside: true,
    },
  });
}

export function createChecklist({
  title = "",
  items = [],
  variant = COMPONENT_VARIANT_IDS.BANKING,
  metadata = {},
} = {}) {
  return createComponent({
    type: COMPONENT_TYPE_IDS.CHECKLIST,
    variant,
    title,
    data: {
      items: items.map((item, index) => ({
        id: item.id || `check-${index + 1}`,
        label:
          typeof item === "string"
            ? item
            : item.label,
        checked:
          typeof item === "string"
            ? false
            : Boolean(item.checked),
        required:
          typeof item === "string"
            ? false
            : Boolean(item.required),
        note:
          typeof item === "string"
            ? ""
            : item.note || "",
      })),
    },
    metadata,
    options: {
      avoidPageBreakInside: false,
    },
  });
}

export function createAnnex({
  title = "",
  number = "",
  content = "",
  items = [],
  variant = COMPONENT_VARIANT_IDS.LEGAL,
  metadata = {},
} = {}) {
  return createComponent({
    type: COMPONENT_TYPE_IDS.ANNEX,
    variant,
    title,
    content,
    data: {
      number,
      items,
    },
    metadata,
    options: {
      separatePage: true,
      pageBreakBefore: true,
    },
  });
}

export function createExhibit({
  title = "",
  label = "",
  content = "",
  fileUrl = "",
  variant = COMPONENT_VARIANT_IDS.LEGAL,
  metadata = {},
} = {}) {
  return createComponent({
    type: COMPONENT_TYPE_IDS.EXHIBIT,
    variant,
    title,
    content,
    data: {
      label,
      fileUrl,
    },
    metadata,
    options: {
      separatePage: true,
      pageBreakBefore: true,
    },
  });
}

export function createPageBreak({
  metadata = {},
} = {}) {
  return createComponent({
    type: COMPONENT_TYPE_IDS.PAGE_BREAK,
    metadata,
    options: {
      pageBreakBefore: true,
    },
  });
}

export function getComponentDefaultStyle(
  component,
  theme = {}
) {
  const colors = theme.colors || {};
  const components = theme.components || {};

  const base = {
    color:
      colors.text ||
      "var(--doc-text)",
    fontFamily:
      "var(--doc-body-font)",
  };

  const styles = {
    [COMPONENT_TYPE_IDS.COVER_PAGE]: {
      ...base,
      background:
        colors.background ||
        "var(--doc-background)",
      color:
        colors.heading ||
        "var(--doc-heading)",
      borderColor:
        colors.accent ||
        "var(--doc-accent)",
    },

    [COMPONENT_TYPE_IDS.SECTION_HEADER]: {
      ...base,
      color:
        colors.heading ||
        "var(--doc-heading)",
      borderColor:
        colors.accent ||
        "var(--doc-accent)",
    },

    [COMPONENT_TYPE_IDS.DATA_TABLE]: {
      ...base,
      borderColor:
        components.tableBorder ||
        "var(--doc-table-border)",
      headerBackground:
        components.tableHeader ||
        "var(--doc-table-header)",
      headerColor:
        components.tableHeaderText ||
        "var(--doc-table-header-text)",
      stripeBackground:
        components.tableStripe ||
        "var(--doc-table-stripe)",
    },

    [COMPONENT_TYPE_IDS.KEY_VALUE_TABLE]: {
      ...base,
      borderColor:
        components.tableBorder ||
        "var(--doc-table-border)",
      labelBackground:
        colors.surface ||
        "var(--doc-surface)",
    },

    [COMPONENT_TYPE_IDS.CALLOUT]: {
      ...base,
      background:
        components.calloutBackground ||
        "var(--doc-callout-background)",
      borderColor:
        components.calloutBorder ||
        "var(--doc-callout-border)",
    },

    [COMPONENT_TYPE_IDS.NOTICE]: {
      ...base,
      background: "#EEF5FA",
      borderColor:
        colors.secondary ||
        "var(--doc-secondary)",
    },

    [COMPONENT_TYPE_IDS.WARNING]: {
      ...base,
      background:
        components.warningBackground ||
        "var(--doc-warning-background)",
      borderColor:
        components.warningBorder ||
        "var(--doc-warning-border)",
    },

    [COMPONENT_TYPE_IDS.CERTIFICATION]: {
      ...base,
      borderColor:
        colors.accent ||
        "var(--doc-accent)",
      background:
        colors.surface ||
        "var(--doc-surface)",
    },

    [COMPONENT_TYPE_IDS.SIGNATURE_BLOCK]: {
      ...base,
      lineColor:
        components.signatureLine ||
        "var(--doc-signature-line)",
    },

    [COMPONENT_TYPE_IDS.DIVIDER]: {
      ...base,
      borderColor:
        colors.accent ||
        "var(--doc-accent)",
    },

    [COMPONENT_TYPE_IDS.QUOTE]: {
      ...base,
      color:
        colors.secondary ||
        "var(--doc-secondary)",
      borderColor:
        colors.accent ||
        "var(--doc-accent)",
    },
  };

  return {
    ...base,
    ...(styles[component?.type] || {}),
    ...(component?.style || {}),
  };
}

export function normalizeComponent(component = {}) {
  return createComponent({
    ...component,
    metadata: {
      createdAt:
        component.metadata?.createdAt ||
        new Date().toISOString(),
      updatedAt:
        new Date().toISOString(),
      ...(component.metadata || {}),
    },
  });
}

export function cloneComponent(
  component,
  overrides = {}
) {
  const cloned = JSON.parse(
    JSON.stringify(component)
  );

  return normalizeComponent({
    ...cloned,
    ...overrides,
    id:
      overrides.id ||
      `${component.type}-${Date.now()}-${Math.random()
        .toString(36)
        .slice(2, 8)}`,
  });
}

export function updateComponent(
  component,
  updates = {}
) {
  return normalizeComponent({
    ...component,
    ...updates,
    data: {
      ...(component.data || {}),
      ...(updates.data || {}),
    },
    style: {
      ...(component.style || {}),
      ...(updates.style || {}),
    },
    options: {
      ...(component.options || {}),
      ...(updates.options || {}),
    },
    metadata: {
      ...(component.metadata || {}),
      ...(updates.metadata || {}),
    },
  });
}

export function validateComponent(
  component
) {
  const errors = [];

  if (!component) {
    errors.push("Component is required.");
    return {
      valid: false,
      errors,
    };
  }

  if (!component.type) {
    errors.push(
      "Component type is required."
    );
  }

  if (
    component.type &&
    !Object.values(
      COMPONENT_TYPE_IDS
    ).includes(component.type)
  ) {
    errors.push(
      `Unsupported component type: ${component.type}`
    );
  }

  if (
    component.type ===
      COMPONENT_TYPE_IDS.DATA_TABLE &&
    !Array.isArray(component.data?.rows)
  ) {
    errors.push(
      "Data table rows must be an array."
    );
  }

  if (
    component.type ===
      COMPONENT_TYPE_IDS.SIGNATURE_TABLE &&
    !Array.isArray(
      component.data?.signatories
    )
  ) {
    errors.push(
      "Signature table signatories must be an array."
    );
  }

  return {
    valid: errors.length === 0,
    errors,
  };
}

export function serializeComponent(
  component
) {
  return JSON.stringify(
    normalizeComponent(component)
  );
}

export function parseComponent(
  serialized
) {
  try {
    return normalizeComponent(
      JSON.parse(serialized)
    );
  } catch {
    return null;
  }
}

export function serializeComponents(
  components = []
) {
  return JSON.stringify(
    components.map(normalizeComponent)
  );
}

export function parseComponents(
  serialized
) {
  try {
    const parsed = JSON.parse(serialized);

    return Array.isArray(parsed)
      ? parsed.map(normalizeComponent)
      : [];
  } catch {
    return [];
  }
}

export default {
  typeIds: COMPONENT_TYPE_IDS,
  variantIds: COMPONENT_VARIANT_IDS,
  alignmentIds: ALIGNMENT_IDS,
  signatureLayoutIds:
    SIGNATURE_LAYOUT_IDS,
  create: createComponent,
  createCoverPage,
  createSectionHeader,
  createParagraph,
  createDataTable,
  createKeyValueTable,
  createCallout,
  createNotice,
  createWarning,
  createCertification,
  createSignatureBlock,
  createSignatureTable,
  createWatermark,
  createDivider,
  createQuote,
  createChecklist,
  createAnnex,
  createExhibit,
  createPageBreak,
  getDefaultStyle:
    getComponentDefaultStyle,
  normalize: normalizeComponent,
  clone: cloneComponent,
  update: updateComponent,
  validate: validateComponent,
  serialize: serializeComponent,
  parse: parseComponent,
  serializeMany:
    serializeComponents,
  parseMany:
    parseComponents,
};
