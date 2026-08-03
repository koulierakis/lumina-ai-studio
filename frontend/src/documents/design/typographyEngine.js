
export const TYPOGRAPHY_PRESET_IDS = Object.freeze({
  EXECUTIVE: "executive",
  BANKING: "banking",
  LEGAL: "legal",
  CORPORATE: "corporate",
  GOVERNMENT: "government",
  MINIMAL: "minimal",
  LUXURY: "luxury",
  NOTARY: "notary",
});

export const TEXT_STYLE_IDS = Object.freeze({
  DOCUMENT_TITLE: "document-title",
  DOCUMENT_SUBTITLE: "document-subtitle",
  HEADING_1: "heading-1",
  HEADING_2: "heading-2",
  HEADING_3: "heading-3",
  HEADING_4: "heading-4",
  BODY: "body",
  BODY_SMALL: "body-small",
  LEAD: "lead",
  CAPTION: "caption",
  FOOTNOTE: "footnote",
  TABLE_HEADER: "table-header",
  TABLE_BODY: "table-body",
  QUOTE: "quote",
  CALLOUT: "callout",
  SIGNATURE_NAME: "signature-name",
  SIGNATURE_ROLE: "signature-role",
  CONFIDENTIAL: "confidential",
  PAGE_NUMBER: "page-number",
  LABEL: "label",
  VALUE: "value",
});

const createStyle = ({
  fontFamily,
  fontSize,
  fontWeight = 400,
  lineHeight = 1.5,
  letterSpacing = 0,
  textTransform = "none",
  textAlign = "left",
  fontStyle = "normal",
  marginTop = 0,
  marginBottom = 0,
  color = "var(--doc-text)",
  decoration = "none",
  keepWithNext = false,
} = {}) => ({
  fontFamily,
  fontSize,
  fontWeight,
  lineHeight,
  letterSpacing,
  textTransform,
  textAlign,
  fontStyle,
  marginTop,
  marginBottom,
  color,
  decoration,
  keepWithNext,
});

const BASE_FONTS = Object.freeze({
  serif: "Georgia, 'Times New Roman', serif",
  traditionalSerif: "'Times New Roman', Times, serif",
  sans: "Arial, Helvetica, sans-serif",
  modernSans: "'Segoe UI', Arial, Helvetica, sans-serif",
});

const createBaseStyles = ({
  headingFont = BASE_FONTS.serif,
  bodyFont = BASE_FONTS.sans,
  titleSize = 34,
  bodySize = 11,
  bodyLineHeight = 1.55,
  headingWeight = 600,
} = {}) => ({
  [TEXT_STYLE_IDS.DOCUMENT_TITLE]: createStyle({
    fontFamily: headingFont,
    fontSize: titleSize,
    fontWeight: headingWeight,
    lineHeight: 1.15,
    letterSpacing: 0.2,
    marginBottom: 10,
    color: "var(--doc-heading)",
    keepWithNext: true,
  }),

  [TEXT_STYLE_IDS.DOCUMENT_SUBTITLE]: createStyle({
    fontFamily: bodyFont,
    fontSize: 14,
    fontWeight: 400,
    lineHeight: 1.4,
    letterSpacing: 0.1,
    marginBottom: 18,
    color: "var(--doc-muted-text)",
    keepWithNext: true,
  }),

  [TEXT_STYLE_IDS.HEADING_1]: createStyle({
    fontFamily: headingFont,
    fontSize: 24,
    fontWeight: headingWeight,
    lineHeight: 1.25,
    marginTop: 20,
    marginBottom: 10,
    color: "var(--doc-heading)",
    keepWithNext: true,
  }),

  [TEXT_STYLE_IDS.HEADING_2]: createStyle({
    fontFamily: headingFont,
    fontSize: 18,
    fontWeight: headingWeight,
    lineHeight: 1.3,
    marginTop: 16,
    marginBottom: 8,
    color: "var(--doc-heading)",
    keepWithNext: true,
  }),

  [TEXT_STYLE_IDS.HEADING_3]: createStyle({
    fontFamily: headingFont,
    fontSize: 14,
    fontWeight: 600,
    lineHeight: 1.35,
    marginTop: 14,
    marginBottom: 6,
    color: "var(--doc-heading)",
    keepWithNext: true,
  }),

  [TEXT_STYLE_IDS.HEADING_4]: createStyle({
    fontFamily: bodyFont,
    fontSize: 12,
    fontWeight: 700,
    lineHeight: 1.4,
    marginTop: 12,
    marginBottom: 5,
    color: "var(--doc-heading)",
    keepWithNext: true,
  }),

  [TEXT_STYLE_IDS.BODY]: createStyle({
    fontFamily: bodyFont,
    fontSize: bodySize,
    fontWeight: 400,
    lineHeight: bodyLineHeight,
    marginBottom: 8,
    color: "var(--doc-text)",
  }),

  [TEXT_STYLE_IDS.BODY_SMALL]: createStyle({
    fontFamily: bodyFont,
    fontSize: 9.5,
    fontWeight: 400,
    lineHeight: 1.45,
    marginBottom: 6,
    color: "var(--doc-text)",
  }),

  [TEXT_STYLE_IDS.LEAD]: createStyle({
    fontFamily: bodyFont,
    fontSize: 13,
    fontWeight: 400,
    lineHeight: 1.6,
    marginBottom: 12,
    color: "var(--doc-text)",
  }),

  [TEXT_STYLE_IDS.CAPTION]: createStyle({
    fontFamily: bodyFont,
    fontSize: 8.5,
    fontWeight: 400,
    lineHeight: 1.35,
    marginTop: 4,
    marginBottom: 8,
    color: "var(--doc-muted-text)",
  }),

  [TEXT_STYLE_IDS.FOOTNOTE]: createStyle({
    fontFamily: bodyFont,
    fontSize: 8,
    fontWeight: 400,
    lineHeight: 1.35,
    marginBottom: 4,
    color: "var(--doc-muted-text)",
  }),

  [TEXT_STYLE_IDS.TABLE_HEADER]: createStyle({
    fontFamily: bodyFont,
    fontSize: 9,
    fontWeight: 700,
    lineHeight: 1.3,
    letterSpacing: 0.15,
    textTransform: "uppercase",
    color: "var(--doc-table-header-text)",
    keepWithNext: true,
  }),

  [TEXT_STYLE_IDS.TABLE_BODY]: createStyle({
    fontFamily: bodyFont,
    fontSize: 9.5,
    fontWeight: 400,
    lineHeight: 1.4,
    color: "var(--doc-text)",
  }),

  [TEXT_STYLE_IDS.QUOTE]: createStyle({
    fontFamily: headingFont,
    fontSize: 13,
    fontWeight: 400,
    lineHeight: 1.6,
    fontStyle: "italic",
    marginTop: 12,
    marginBottom: 12,
    color: "var(--doc-secondary)",
  }),

  [TEXT_STYLE_IDS.CALLOUT]: createStyle({
    fontFamily: bodyFont,
    fontSize: 10.5,
    fontWeight: 500,
    lineHeight: 1.5,
    marginBottom: 8,
    color: "var(--doc-text)",
  }),

  [TEXT_STYLE_IDS.SIGNATURE_NAME]: createStyle({
    fontFamily: headingFont,
    fontSize: 12,
    fontWeight: 600,
    lineHeight: 1.3,
    marginTop: 4,
    marginBottom: 2,
    color: "var(--doc-heading)",
  }),

  [TEXT_STYLE_IDS.SIGNATURE_ROLE]: createStyle({
    fontFamily: bodyFont,
    fontSize: 9,
    fontWeight: 400,
    lineHeight: 1.3,
    marginBottom: 2,
    color: "var(--doc-muted-text)",
  }),

  [TEXT_STYLE_IDS.CONFIDENTIAL]: createStyle({
    fontFamily: bodyFont,
    fontSize: 8,
    fontWeight: 700,
    lineHeight: 1.2,
    letterSpacing: 1.2,
    textTransform: "uppercase",
    textAlign: "center",
    color: "var(--doc-muted-text)",
  }),

  [TEXT_STYLE_IDS.PAGE_NUMBER]: createStyle({
    fontFamily: bodyFont,
    fontSize: 8,
    fontWeight: 400,
    lineHeight: 1.2,
    textAlign: "center",
    color: "var(--doc-muted-text)",
  }),

  [TEXT_STYLE_IDS.LABEL]: createStyle({
    fontFamily: bodyFont,
    fontSize: 8.5,
    fontWeight: 700,
    lineHeight: 1.3,
    letterSpacing: 0.3,
    textTransform: "uppercase",
    color: "var(--doc-muted-text)",
  }),

  [TEXT_STYLE_IDS.VALUE]: createStyle({
    fontFamily: bodyFont,
    fontSize: 10.5,
    fontWeight: 500,
    lineHeight: 1.4,
    color: "var(--doc-text)",
  }),
});

export const TYPOGRAPHY_PRESETS = Object.freeze({
  [TYPOGRAPHY_PRESET_IDS.EXECUTIVE]: {
    id: TYPOGRAPHY_PRESET_IDS.EXECUTIVE,
    name: "Executive",
    nameEl: "Executive",
    headingFont: BASE_FONTS.serif,
    bodyFont: BASE_FONTS.sans,
    styles: createBaseStyles({
      headingFont: BASE_FONTS.serif,
      bodyFont: BASE_FONTS.sans,
      titleSize: 36,
      bodySize: 11,
      headingWeight: 700,
    }),
  },

  [TYPOGRAPHY_PRESET_IDS.BANKING]: {
    id: TYPOGRAPHY_PRESET_IDS.BANKING,
    name: "Banking",
    nameEl: "Τραπεζικό",
    headingFont: BASE_FONTS.serif,
    bodyFont: BASE_FONTS.sans,
    styles: createBaseStyles({
      headingFont: BASE_FONTS.serif,
      bodyFont: BASE_FONTS.sans,
      titleSize: 32,
      bodySize: 10.5,
      headingWeight: 600,
    }),
  },

  [TYPOGRAPHY_PRESET_IDS.LEGAL]: {
    id: TYPOGRAPHY_PRESET_IDS.LEGAL,
    name: "Legal",
    nameEl: "Νομικό",
    headingFont: BASE_FONTS.traditionalSerif,
    bodyFont: BASE_FONTS.traditionalSerif,
    styles: createBaseStyles({
      headingFont: BASE_FONTS.traditionalSerif,
      bodyFont: BASE_FONTS.traditionalSerif,
      titleSize: 30,
      bodySize: 11.5,
      bodyLineHeight: 1.65,
      headingWeight: 700,
    }),
  },

  [TYPOGRAPHY_PRESET_IDS.CORPORATE]: {
    id: TYPOGRAPHY_PRESET_IDS.CORPORATE,
    name: "Corporate",
    nameEl: "Εταιρικό",
    headingFont: BASE_FONTS.modernSans,
    bodyFont: BASE_FONTS.sans,
    styles: createBaseStyles({
      headingFont: BASE_FONTS.modernSans,
      bodyFont: BASE_FONTS.sans,
      titleSize: 32,
      bodySize: 10.5,
      headingWeight: 700,
    }),
  },

  [TYPOGRAPHY_PRESET_IDS.GOVERNMENT]: {
    id: TYPOGRAPHY_PRESET_IDS.GOVERNMENT,
    name: "Government",
    nameEl: "Δημόσια Διοίκηση",
    headingFont: BASE_FONTS.sans,
    bodyFont: BASE_FONTS.sans,
    styles: createBaseStyles({
      headingFont: BASE_FONTS.sans,
      bodyFont: BASE_FONTS.sans,
      titleSize: 30,
      bodySize: 10.5,
      headingWeight: 700,
    }),
  },

  [TYPOGRAPHY_PRESET_IDS.MINIMAL]: {
    id: TYPOGRAPHY_PRESET_IDS.MINIMAL,
    name: "Minimal",
    nameEl: "Μίνιμαλ",
    headingFont: BASE_FONTS.modernSans,
    bodyFont: BASE_FONTS.modernSans,
    styles: createBaseStyles({
      headingFont: BASE_FONTS.modernSans,
      bodyFont: BASE_FONTS.modernSans,
      titleSize: 30,
      bodySize: 10.5,
      headingWeight: 600,
    }),
  },

  [TYPOGRAPHY_PRESET_IDS.LUXURY]: {
    id: TYPOGRAPHY_PRESET_IDS.LUXURY,
    name: "Luxury",
    nameEl: "Πολυτελές",
    headingFont: BASE_FONTS.serif,
    bodyFont: BASE_FONTS.sans,
    styles: createBaseStyles({
      headingFont: BASE_FONTS.serif,
      bodyFont: BASE_FONTS.sans,
      titleSize: 38,
      bodySize: 11,
      headingWeight: 600,
    }),
  },

  [TYPOGRAPHY_PRESET_IDS.NOTARY]: {
    id: TYPOGRAPHY_PRESET_IDS.NOTARY,
    name: "Notary",
    nameEl: "Συμβολαιογραφικό",
    headingFont: BASE_FONTS.traditionalSerif,
    bodyFont: BASE_FONTS.traditionalSerif,
    styles: createBaseStyles({
      headingFont: BASE_FONTS.traditionalSerif,
      bodyFont: BASE_FONTS.traditionalSerif,
      titleSize: 29,
      bodySize: 12,
      bodyLineHeight: 1.7,
      headingWeight: 700,
    }),
  },
});

export const DEFAULT_TYPOGRAPHY_PRESET_ID =
  TYPOGRAPHY_PRESET_IDS.EXECUTIVE;

export function getTypographyPreset(
  presetId = DEFAULT_TYPOGRAPHY_PRESET_ID
) {
  return (
    TYPOGRAPHY_PRESETS[presetId] ||
    TYPOGRAPHY_PRESETS[DEFAULT_TYPOGRAPHY_PRESET_ID]
  );
}

export function getTypographyPresetOptions(language = "el") {
  return Object.values(TYPOGRAPHY_PRESETS).map((preset) => ({
    id: preset.id,
    label: language === "el" ? preset.nameEl : preset.name,
    headingFont: preset.headingFont,
    bodyFont: preset.bodyFont,
  }));
}

export function getTextStyle(
  styleId,
  presetId = DEFAULT_TYPOGRAPHY_PRESET_ID
) {
  const preset = getTypographyPreset(presetId);

  return (
    preset.styles[styleId] ||
    preset.styles[TEXT_STYLE_IDS.BODY]
  );
}

export function resolveTypography({
  presetId = DEFAULT_TYPOGRAPHY_PRESET_ID,
  styles = {},
  headingFont,
  bodyFont,
} = {}) {
  const preset = getTypographyPreset(presetId);

  const resolvedStyles = Object.fromEntries(
    Object.entries(preset.styles).map(([styleId, style]) => [
      styleId,
      {
        ...style,
        ...(styles[styleId] || {}),
        fontFamily:
          styles[styleId]?.fontFamily ||
          (
            styleId.includes("heading") ||
            styleId === TEXT_STYLE_IDS.DOCUMENT_TITLE ||
            styleId === TEXT_STYLE_IDS.QUOTE ||
            styleId === TEXT_STYLE_IDS.SIGNATURE_NAME
              ? headingFont || style.fontFamily
              : bodyFont || style.fontFamily
          ),
      },
    ])
  );

  return {
    id: preset.id,
    name: preset.name,
    nameEl: preset.nameEl,
    headingFont: headingFont || preset.headingFont,
    bodyFont: bodyFont || preset.bodyFont,
    styles: resolvedStyles,
  };
}

export function typographyStyleToCss(style = {}) {
  return {
    fontFamily: style.fontFamily,
    fontSize:
      typeof style.fontSize === "number"
        ? `${style.fontSize}px`
        : style.fontSize,
    fontWeight: style.fontWeight,
    lineHeight: style.lineHeight,
    letterSpacing:
      typeof style.letterSpacing === "number"
        ? `${style.letterSpacing}px`
        : style.letterSpacing,
    textTransform: style.textTransform,
    textAlign: style.textAlign,
    fontStyle: style.fontStyle,
    marginTop:
      typeof style.marginTop === "number"
        ? `${style.marginTop}px`
        : style.marginTop,
    marginBottom:
      typeof style.marginBottom === "number"
        ? `${style.marginBottom}px`
        : style.marginBottom,
    color: style.color,
    textDecoration: style.decoration,
  };
}

export function createTypographyCssVariables(config = {}) {
  const typography = resolveTypography(config);
  const body = typography.styles[TEXT_STYLE_IDS.BODY];
  const title = typography.styles[TEXT_STYLE_IDS.DOCUMENT_TITLE];
  const h1 = typography.styles[TEXT_STYLE_IDS.HEADING_1];
  const h2 = typography.styles[TEXT_STYLE_IDS.HEADING_2];
  const h3 = typography.styles[TEXT_STYLE_IDS.HEADING_3];
  const small = typography.styles[TEXT_STYLE_IDS.BODY_SMALL];

  return {
    "--doc-heading-font": typography.headingFont,
    "--doc-body-font": typography.bodyFont,
    "--doc-title-size": `${title.fontSize}px`,
    "--doc-h1-size": `${h1.fontSize}px`,
    "--doc-h2-size": `${h2.fontSize}px`,
    "--doc-h3-size": `${h3.fontSize}px`,
    "--doc-body-size": `${body.fontSize}px`,
    "--doc-small-size": `${small.fontSize}px`,
    "--doc-line-height": String(body.lineHeight),
    "--doc-letter-spacing": `${body.letterSpacing}px`,
  };
}

export function applyTypographyToElement(element, config = {}) {
  if (!element) {
    return;
  }

  const typography = resolveTypography(config);
  const variables = createTypographyCssVariables(config);

  Object.entries(variables).forEach(([name, value]) => {
    element.style.setProperty(name, String(value));
  });

  element.dataset.typographyPreset = typography.id;
}

export function createTypographyClassMap(config = {}) {
  const typography = resolveTypography(config);

  return Object.fromEntries(
    Object.entries(typography.styles).map(([styleId, style]) => [
      styleId,
      typographyStyleToCss(style),
    ])
  );
}

export function serializeTypography(config = {}) {
  return JSON.stringify(resolveTypography(config));
}

export function parseTypography(serialized) {
  try {
    return resolveTypography(JSON.parse(serialized));
  } catch {
    return resolveTypography();
  }
}

export default {
  presetIds: TYPOGRAPHY_PRESET_IDS,
  styleIds: TEXT_STYLE_IDS,
  presets: TYPOGRAPHY_PRESETS,
  defaultPresetId: DEFAULT_TYPOGRAPHY_PRESET_ID,
  getPreset: getTypographyPreset,
  getPresetOptions: getTypographyPresetOptions,
  getStyle: getTextStyle,
  resolve: resolveTypography,
  styleToCss: typographyStyleToCss,
  createCssVariables: createTypographyCssVariables,
  applyToElement: applyTypographyToElement,
  createClassMap: createTypographyClassMap,
  serialize: serializeTypography,
  parse: parseTypography,
};
