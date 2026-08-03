
export const DOCUMENT_THEME_IDS = Object.freeze({
  EXECUTIVE_BLACK: "executive-black",
  EXECUTIVE_GOLD: "executive-gold",
  CORPORATE_WHITE: "corporate-white",
  BANKING_BLUE: "banking-blue",
  BANKING_PLATINUM: "banking-platinum",
  LAW_FIRM: "law-firm",
  NOTARY: "notary",
  GOVERNMENT: "government",
  LUXURY_EMERALD: "luxury-emerald",
  MINIMAL: "minimal",
});

const baseTypography = {
  headingFont: "Georgia, 'Times New Roman', serif",
  bodyFont: "Arial, Helvetica, sans-serif",
  headingWeight: 600,
  bodyWeight: 400,
  titleSize: 34,
  heading1Size: 24,
  heading2Size: 18,
  heading3Size: 14,
  bodySize: 11,
  smallSize: 9,
  lineHeight: 1.55,
  letterSpacing: 0,
};

const basePage = {
  size: "A4",
  orientation: "portrait",
  marginTop: 22,
  marginRight: 20,
  marginBottom: 22,
  marginLeft: 20,
  contentWidth: 170,
  pageGap: 24,
  borderWidth: 1,
  borderRadius: 0,
};

const baseComponents = {
  tableHeaderText: "#FFFFFF",
  tableStripe: "#F7F7F7",
  tableBorder: "#D6D6D6",
  calloutBackground: "#F6F6F6",
  calloutBorder: "#CFCFCF",
  warningBackground: "#FFF8E6",
  warningBorder: "#D8A928",
  signatureLine: "#222222",
};

export const DOCUMENT_THEMES = Object.freeze({
  [DOCUMENT_THEME_IDS.EXECUTIVE_BLACK]: {
    id: DOCUMENT_THEME_IDS.EXECUTIVE_BLACK,
    name: "Executive Black",
    nameEl: "Executive Μαύρο",
    description: "Ισχυρή, αυστηρή και πολυτελής εταιρική εμφάνιση.",
    colors: {
      primary: "#0B0B0C",
      secondary: "#242427",
      accent: "#C7A760",
      background: "#FFFFFF",
      surface: "#F4F4F3",
      text: "#151515",
      mutedText: "#676767",
      border: "#B9B9B9",
      heading: "#0B0B0C",
      link: "#876A2E",
    },
    typography: {
      ...baseTypography,
      headingFont: "Georgia, 'Times New Roman', serif",
      headingWeight: 700,
    },
    page: {
      ...basePage,
      borderWidth: 2,
    },
    components: {
      ...baseComponents,
      tableHeader: "#0B0B0C",
      tableStripe: "#F2F2F2",
      calloutBorder: "#C7A760",
    },
  },

  [DOCUMENT_THEME_IDS.EXECUTIVE_GOLD]: {
    id: DOCUMENT_THEME_IDS.EXECUTIVE_GOLD,
    name: "Executive Gold",
    nameEl: "Executive Χρυσό",
    description: "Premium εταιρική παρουσίαση με χρυσές λεπτομέρειες.",
    colors: {
      primary: "#17130C",
      secondary: "#443719",
      accent: "#B9985A",
      background: "#FFFDF8",
      surface: "#F7F1E4",
      text: "#1F1C17",
      mutedText: "#736A5D",
      border: "#D4C29E",
      heading: "#241D10",
      link: "#8F6E2D",
    },
    typography: {
      ...baseTypography,
      headingFont: "Georgia, 'Times New Roman', serif",
      headingWeight: 600,
      letterSpacing: 0.15,
    },
    page: {
      ...basePage,
      borderWidth: 2,
    },
    components: {
      ...baseComponents,
      tableHeader: "#2B2417",
      tableStripe: "#FBF7EE",
      tableBorder: "#D9C9A8",
      calloutBackground: "#FAF5E9",
      calloutBorder: "#B9985A",
    },
  },

  [DOCUMENT_THEME_IDS.CORPORATE_WHITE]: {
    id: DOCUMENT_THEME_IDS.CORPORATE_WHITE,
    name: "Corporate White",
    nameEl: "Εταιρικό Λευκό",
    description: "Καθαρό και σύγχρονο εταιρικό έγγραφο.",
    colors: {
      primary: "#17202A",
      secondary: "#43505D",
      accent: "#9A7A3A",
      background: "#FFFFFF",
      surface: "#F7F8FA",
      text: "#20252A",
      mutedText: "#6D747B",
      border: "#D9DDE2",
      heading: "#17202A",
      link: "#245A8D",
    },
    typography: {
      ...baseTypography,
      headingFont: "Arial, Helvetica, sans-serif",
      headingWeight: 700,
    },
    page: {
      ...basePage,
    },
    components: {
      ...baseComponents,
      tableHeader: "#17202A",
    },
  },

  [DOCUMENT_THEME_IDS.BANKING_BLUE]: {
    id: DOCUMENT_THEME_IDS.BANKING_BLUE,
    name: "Banking Blue",
    nameEl: "Τραπεζικό Μπλε",
    description: "Θεσμική τραπεζική και compliance εμφάνιση.",
    colors: {
      primary: "#063B59",
      secondary: "#0D5E83",
      accent: "#B69045",
      background: "#FFFFFF",
      surface: "#EEF5F8",
      text: "#17242C",
      mutedText: "#63727A",
      border: "#BFD0D8",
      heading: "#063B59",
      link: "#0D5E83",
    },
    typography: {
      ...baseTypography,
      headingFont: "Georgia, 'Times New Roman', serif",
    },
    page: {
      ...basePage,
    },
    components: {
      ...baseComponents,
      tableHeader: "#063B59",
      tableStripe: "#F0F6F8",
      tableBorder: "#BFD0D8",
      calloutBackground: "#EDF5F8",
      calloutBorder: "#0D5E83",
    },
  },

  [DOCUMENT_THEME_IDS.BANKING_PLATINUM]: {
    id: DOCUMENT_THEME_IDS.BANKING_PLATINUM,
    name: "Banking Platinum",
    nameEl: "Τραπεζικό Πλατινένιο",
    description: "Υψηλού επιπέδου ουδέτερο banking layout.",
    colors: {
      primary: "#30363B",
      secondary: "#69747C",
      accent: "#A58A57",
      background: "#FFFFFF",
      surface: "#F2F4F5",
      text: "#252A2E",
      mutedText: "#727B82",
      border: "#C7CDD1",
      heading: "#30363B",
      link: "#4E6575",
    },
    typography: {
      ...baseTypography,
      headingFont: "Georgia, 'Times New Roman', serif",
      headingWeight: 600,
    },
    page: {
      ...basePage,
    },
    components: {
      ...baseComponents,
      tableHeader: "#3A4146",
      tableStripe: "#F3F5F6",
      tableBorder: "#C7CDD1",
      calloutBackground: "#F1F3F4",
      calloutBorder: "#A58A57",
    },
  },

  [DOCUMENT_THEME_IDS.LAW_FIRM]: {
    id: DOCUMENT_THEME_IDS.LAW_FIRM,
    name: "Law Firm",
    nameEl: "Δικηγορικό Γραφείο",
    description: "Κλασικό διεθνές νομικό ύφος.",
    colors: {
      primary: "#1B2430",
      secondary: "#394B5A",
      accent: "#8B6F3D",
      background: "#FFFFFF",
      surface: "#F7F6F3",
      text: "#1C1C1C",
      mutedText: "#646464",
      border: "#C9C6BE",
      heading: "#1B2430",
      link: "#334E68",
    },
    typography: {
      ...baseTypography,
      headingFont: "Georgia, 'Times New Roman', serif",
      bodyFont: "'Times New Roman', Times, serif",
      bodySize: 11.5,
      lineHeight: 1.6,
    },
    page: {
      ...basePage,
      marginLeft: 24,
      marginRight: 24,
    },
    components: {
      ...baseComponents,
      tableHeader: "#1B2430",
      calloutBackground: "#F7F6F3",
      calloutBorder: "#8B6F3D",
    },
  },

  [DOCUMENT_THEME_IDS.NOTARY]: {
    id: DOCUMENT_THEME_IDS.NOTARY,
    name: "Notary",
    nameEl: "Συμβολαιογραφικό",
    description: "Επίσημη και παραδοσιακή παρουσίαση.",
    colors: {
      primary: "#241C17",
      secondary: "#59483C",
      accent: "#8A6436",
      background: "#FFFDF7",
      surface: "#F7F2E8",
      text: "#1D1916",
      mutedText: "#6B625A",
      border: "#CBBDAA",
      heading: "#241C17",
      link: "#6F4D28",
    },
    typography: {
      ...baseTypography,
      headingFont: "'Times New Roman', Times, serif",
      bodyFont: "'Times New Roman', Times, serif",
      bodySize: 12,
      lineHeight: 1.65,
    },
    page: {
      ...basePage,
      marginLeft: 26,
      marginRight: 26,
    },
    components: {
      ...baseComponents,
      tableHeader: "#3A2D24",
      tableStripe: "#FBF7EF",
      calloutBackground: "#F7F2E8",
      calloutBorder: "#8A6436",
    },
  },

  [DOCUMENT_THEME_IDS.GOVERNMENT]: {
    id: DOCUMENT_THEME_IDS.GOVERNMENT,
    name: "Government",
    nameEl: "Δημόσια Διοίκηση",
    description: "Επίσημη διοικητική μορφοποίηση.",
    colors: {
      primary: "#173B62",
      secondary: "#496A8B",
      accent: "#B08A3C",
      background: "#FFFFFF",
      surface: "#F3F6F9",
      text: "#1D2833",
      mutedText: "#667684",
      border: "#BFCAD4",
      heading: "#173B62",
      link: "#245B8D",
    },
    typography: {
      ...baseTypography,
      headingFont: "Arial, Helvetica, sans-serif",
      bodyFont: "Arial, Helvetica, sans-serif",
      headingWeight: 700,
    },
    page: {
      ...basePage,
    },
    components: {
      ...baseComponents,
      tableHeader: "#173B62",
      tableStripe: "#F1F5F8",
      calloutBackground: "#EEF3F7",
      calloutBorder: "#496A8B",
    },
  },

  [DOCUMENT_THEME_IDS.LUXURY_EMERALD]: {
    id: DOCUMENT_THEME_IDS.LUXURY_EMERALD,
    name: "Luxury Emerald",
    nameEl: "Luxury Σμαραγδί",
    description: "Πολυτελές πράσινο εταιρικό theme.",
    colors: {
      primary: "#0D3B32",
      secondary: "#1E6656",
      accent: "#C2A05A",
      background: "#FFFEFA",
      surface: "#EDF5F1",
      text: "#172622",
      mutedText: "#64756F",
      border: "#B7CCC5",
      heading: "#0D3B32",
      link: "#176454",
    },
    typography: {
      ...baseTypography,
      headingFont: "Georgia, 'Times New Roman', serif",
      headingWeight: 600,
    },
    page: {
      ...basePage,
      borderWidth: 2,
    },
    components: {
      ...baseComponents,
      tableHeader: "#0D3B32",
      tableStripe: "#F0F7F4",
      tableBorder: "#B7CCC5",
      calloutBackground: "#EDF5F1",
      calloutBorder: "#C2A05A",
    },
  },

  [DOCUMENT_THEME_IDS.MINIMAL]: {
    id: DOCUMENT_THEME_IDS.MINIMAL,
    name: "Minimal",
    nameEl: "Μίνιμαλ",
    description: "Απλό, καθαρό και ευανάγνωστο.",
    colors: {
      primary: "#202020",
      secondary: "#626262",
      accent: "#8A8A8A",
      background: "#FFFFFF",
      surface: "#F8F8F8",
      text: "#202020",
      mutedText: "#707070",
      border: "#DDDDDD",
      heading: "#202020",
      link: "#454545",
    },
    typography: {
      ...baseTypography,
      headingFont: "Arial, Helvetica, sans-serif",
      bodyFont: "Arial, Helvetica, sans-serif",
      headingWeight: 600,
    },
    page: {
      ...basePage,
    },
    components: {
      ...baseComponents,
      tableHeader: "#303030",
      tableStripe: "#F8F8F8",
      calloutBackground: "#F8F8F8",
      calloutBorder: "#BEBEBE",
    },
  },
});

export const DEFAULT_DOCUMENT_THEME_ID =
  DOCUMENT_THEME_IDS.EXECUTIVE_GOLD;

function mergeObjects(base, overrides) {
  return {
    ...base,
    ...(overrides || {}),
  };
}

export function getDocumentTheme(themeId = DEFAULT_DOCUMENT_THEME_ID) {
  return (
    DOCUMENT_THEMES[themeId] ||
    DOCUMENT_THEMES[DEFAULT_DOCUMENT_THEME_ID]
  );
}

export function getDocumentThemeOptions(language = "el") {
  return Object.values(DOCUMENT_THEMES).map((theme) => ({
    id: theme.id,
    label: language === "el" ? theme.nameEl : theme.name,
    description: theme.description,
  }));
}

export function resolveDocumentTheme({
  themeId = DEFAULT_DOCUMENT_THEME_ID,
  branding = {},
  typography = {},
  page = {},
  components = {},
} = {}) {
  const theme = getDocumentTheme(themeId);

  return {
    ...theme,
    colors: mergeObjects(theme.colors, {
      primary: branding.primaryColor,
      secondary: branding.secondaryColor,
      accent: branding.accentColor,
      background: branding.backgroundColor,
      heading: branding.headingColor,
    }),
    typography: mergeObjects(theme.typography, typography),
    page: mergeObjects(theme.page, page),
    components: mergeObjects(theme.components, components),
    branding: {
      logoUrl: branding.logoUrl || "",
      sealUrl: branding.sealUrl || "",
      signatureUrl: branding.signatureUrl || "",
      watermarkUrl: branding.watermarkUrl || "",
      companyName: branding.companyName || "",
      confidentialLabel:
        branding.confidentialLabel || "CONFIDENTIAL",
    },
  };
}

export function createThemeCssVariables(themeConfig) {
  const theme = resolveDocumentTheme(themeConfig);
  const { colors, typography, page, components } = theme;

  return {
    "--doc-primary": colors.primary,
    "--doc-secondary": colors.secondary,
    "--doc-accent": colors.accent,
    "--doc-background": colors.background,
    "--doc-surface": colors.surface,
    "--doc-text": colors.text,
    "--doc-muted-text": colors.mutedText,
    "--doc-border": colors.border,
    "--doc-heading": colors.heading,
    "--doc-link": colors.link,

    "--doc-heading-font": typography.headingFont,
    "--doc-body-font": typography.bodyFont,
    "--doc-heading-weight": String(typography.headingWeight),
    "--doc-body-weight": String(typography.bodyWeight),
    "--doc-title-size": `${typography.titleSize}px`,
    "--doc-h1-size": `${typography.heading1Size}px`,
    "--doc-h2-size": `${typography.heading2Size}px`,
    "--doc-h3-size": `${typography.heading3Size}px`,
    "--doc-body-size": `${typography.bodySize}px`,
    "--doc-small-size": `${typography.smallSize}px`,
    "--doc-line-height": String(typography.lineHeight),
    "--doc-letter-spacing": `${typography.letterSpacing}px`,

    "--doc-margin-top": `${page.marginTop}mm`,
    "--doc-margin-right": `${page.marginRight}mm`,
    "--doc-margin-bottom": `${page.marginBottom}mm`,
    "--doc-margin-left": `${page.marginLeft}mm`,
    "--doc-page-gap": `${page.pageGap}px`,
    "--doc-page-border-width": `${page.borderWidth}px`,
    "--doc-page-border-radius": `${page.borderRadius}px`,

    "--doc-table-header": components.tableHeader,
    "--doc-table-header-text": components.tableHeaderText,
    "--doc-table-stripe": components.tableStripe,
    "--doc-table-border": components.tableBorder,
    "--doc-callout-background": components.calloutBackground,
    "--doc-callout-border": components.calloutBorder,
    "--doc-warning-background": components.warningBackground,
    "--doc-warning-border": components.warningBorder,
    "--doc-signature-line": components.signatureLine,
  };
}

export function applyThemeToElement(element, themeConfig) {
  if (!element) {
    return;
  }

  const variables = createThemeCssVariables(themeConfig);

  Object.entries(variables).forEach(([name, value]) => {
    if (value !== undefined && value !== null) {
      element.style.setProperty(name, String(value));
    }
  });

  const theme = resolveDocumentTheme(themeConfig);
  element.dataset.documentTheme = theme.id;
}

export function serializeDocumentTheme(themeConfig) {
  return JSON.stringify(resolveDocumentTheme(themeConfig));
}

export function parseDocumentTheme(serialized) {
  try {
    return resolveDocumentTheme(JSON.parse(serialized));
  } catch {
    return resolveDocumentTheme();
  }
}

export default {
  ids: DOCUMENT_THEME_IDS,
  themes: DOCUMENT_THEMES,
  defaultThemeId: DEFAULT_DOCUMENT_THEME_ID,
  getTheme: getDocumentTheme,
  getOptions: getDocumentThemeOptions,
  resolve: resolveDocumentTheme,
  createCssVariables: createThemeCssVariables,
  applyToElement: applyThemeToElement,
  serialize: serializeDocumentTheme,
  parse: parseDocumentTheme,
};
