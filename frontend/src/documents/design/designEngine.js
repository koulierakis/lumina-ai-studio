
import {
  DEFAULT_DOCUMENT_THEME_ID,
  getDocumentTheme,
  resolveDocumentTheme,
  createThemeCssVariables,
} from "./themeEngine";

import {
  DEFAULT_TYPOGRAPHY_PRESET_ID,
  resolveTypography,
  createTypographyCssVariables,
  createTypographyClassMap,
} from "./typographyEngine";

import {
  DEFAULT_LAYOUT_PRESET_ID,
  resolveLayout,
  createLayoutCssVariables,
  layoutToPageStyle,
  calculateContentArea,
  createPrintCss,
  paginateBlocks,
} from "./layoutEngine";

import {
  createComponent,
  normalizeComponent,
  validateComponent,
  getComponentDefaultStyle,
} from "./componentsEngine";

export const DESIGN_ENGINE_VERSION = "1.0.0";

export const DOCUMENT_PROFILE_IDS = Object.freeze({
  WYOMING_LLC: "wyoming-llc",
  GREEK_IKE: "greek-ike",
  BANK_OF_CYPRUS: "bank-of-cyprus",
  CORPORATE_GENERAL: "corporate-general",
});

export const DOCUMENT_PROFILES = Object.freeze({
  [DOCUMENT_PROFILE_IDS.WYOMING_LLC]: {
    id: DOCUMENT_PROFILE_IDS.WYOMING_LLC,
    name: "Wyoming LLC",
    nameEl: "Wyoming LLC",
    themeId: "executive-gold",
    typographyPresetId: "legal",
    layoutPresetId: "legal",
    defaultLanguage: "en",
    defaultCountry: "US",
    confidentiality: "CONFIDENTIAL",
  },

  [DOCUMENT_PROFILE_IDS.GREEK_IKE]: {
    id: DOCUMENT_PROFILE_IDS.GREEK_IKE,
    name: "Greek IKE",
    nameEl: "Ελληνική ΙΚΕ",
    themeId: "corporate-white",
    typographyPresetId: "corporate",
    layoutPresetId: "corporate",
    defaultLanguage: "el",
    defaultCountry: "GR",
    confidentiality: "ΕΜΠΙΣΤΕΥΤΙΚΟ",
  },

  [DOCUMENT_PROFILE_IDS.BANK_OF_CYPRUS]: {
    id: DOCUMENT_PROFILE_IDS.BANK_OF_CYPRUS,
    name: "Bank of Cyprus",
    nameEl: "Τράπεζα Κύπρου",
    themeId: "banking-blue",
    typographyPresetId: "banking",
    layoutPresetId: "banking",
    defaultLanguage: "en",
    defaultCountry: "CY",
    confidentiality:
      "CONFIDENTIAL - BANKING / KYC / COMPLIANCE REVIEW",
  },

  [DOCUMENT_PROFILE_IDS.CORPORATE_GENERAL]: {
    id: DOCUMENT_PROFILE_IDS.CORPORATE_GENERAL,
    name: "Corporate General",
    nameEl: "Γενικό Εταιρικό",
    themeId: DEFAULT_DOCUMENT_THEME_ID,
    typographyPresetId:
      DEFAULT_TYPOGRAPHY_PRESET_ID,
    layoutPresetId:
      DEFAULT_LAYOUT_PRESET_ID,
    defaultLanguage: "el",
    defaultCountry: "GR",
    confidentiality: "ΕΜΠΙΣΤΕΥΤΙΚΟ",
  },
});

export function getDocumentProfile(
  profileId = DOCUMENT_PROFILE_IDS.CORPORATE_GENERAL
) {
  return (
    DOCUMENT_PROFILES[profileId] ||
    DOCUMENT_PROFILES[
      DOCUMENT_PROFILE_IDS.CORPORATE_GENERAL
    ]
  );
}

export function getDocumentProfileOptions(
  language = "el"
) {
  return Object.values(DOCUMENT_PROFILES).map(
    (profile) => ({
      id: profile.id,
      label:
        language === "el"
          ? profile.nameEl
          : profile.name,
      themeId: profile.themeId,
      typographyPresetId:
        profile.typographyPresetId,
      layoutPresetId:
        profile.layoutPresetId,
    })
  );
}

export function createDesignConfiguration({
  profileId =
    DOCUMENT_PROFILE_IDS.CORPORATE_GENERAL,

  themeId,
  typographyPresetId,
  layoutPresetId,

  branding = {},
  typography = {},
  layout = {},
  components = {},

  language,
  country,
  metadata = {},
} = {}) {
  const profile = getDocumentProfile(profileId);

  const resolvedThemeId =
    themeId ||
    profile.themeId ||
    DEFAULT_DOCUMENT_THEME_ID;

  const resolvedTypographyPresetId =
    typographyPresetId ||
    profile.typographyPresetId ||
    DEFAULT_TYPOGRAPHY_PRESET_ID;

  const resolvedLayoutPresetId =
    layoutPresetId ||
    profile.layoutPresetId ||
    DEFAULT_LAYOUT_PRESET_ID;

  const resolvedTheme = resolveDocumentTheme({
    themeId: resolvedThemeId,
    branding: {
      confidentialLabel:
        branding.confidentialLabel ||
        profile.confidentiality,
      ...branding,
    },
    typography:
      typography.themeOverrides || {},
    page:
      layout.themePageOverrides || {},
    components,
  });

  const resolvedTypography =
    resolveTypography({
      presetId:
        resolvedTypographyPresetId,
      ...typography,
    });

  const resolvedLayout = resolveLayout({
    presetId: resolvedLayoutPresetId,
    ...layout,
  });

  return {
    version: DESIGN_ENGINE_VERSION,

    profile: {
      ...profile,
    },

    language:
      language ||
      profile.defaultLanguage ||
      "el",

    country:
      country ||
      profile.defaultCountry ||
      "GR",

    theme: resolvedTheme,
    typography: resolvedTypography,
    layout: resolvedLayout,

    branding: {
      companyName:
        branding.companyName || "",
      legalName:
        branding.legalName || "",
      logoUrl:
        branding.logoUrl || "",
      sealUrl:
        branding.sealUrl || "",
      signatureUrl:
        branding.signatureUrl || "",
      watermarkUrl:
        branding.watermarkUrl || "",
      primaryColor:
        branding.primaryColor || "",
      secondaryColor:
        branding.secondaryColor || "",
      accentColor:
        branding.accentColor || "",
      confidentialLabel:
        branding.confidentialLabel ||
        profile.confidentiality,
    },

    metadata: {
      createdAt:
        metadata.createdAt ||
        new Date().toISOString(),
      updatedAt:
        new Date().toISOString(),
      version:
        metadata.version || "1.0",
      status:
        metadata.status || "draft",
      ...metadata,
    },
  };
}

export function resolveDesignConfiguration(
  configuration = {}
) {
  return createDesignConfiguration({
    profileId:
      configuration.profile?.id ||
      configuration.profileId,

    themeId:
      configuration.theme?.id ||
      configuration.themeId,

    typographyPresetId:
      configuration.typography?.id ||
      configuration.typographyPresetId,

    layoutPresetId:
      configuration.layout?.id ||
      configuration.layoutPresetId,

    branding:
      configuration.branding || {},

    typography:
      configuration.typography || {},

    layout:
      configuration.layout || {},

    components:
      configuration.theme?.components ||
      configuration.components ||
      {},

    language:
      configuration.language,

    country:
      configuration.country,

    metadata:
      configuration.metadata || {},
  });
}

export function createDesignCssVariables(
  configuration = {}
) {
  const config =
    resolveDesignConfiguration(configuration);

  return {
    ...createThemeCssVariables({
      themeId: config.theme.id,
      branding: config.branding,
      typography:
        config.theme.typography,
      page:
        config.theme.page,
      components:
        config.theme.components,
    }),

    ...createTypographyCssVariables({
      presetId:
        config.typography.id,
      headingFont:
        config.typography.headingFont,
      bodyFont:
        config.typography.bodyFont,
      styles:
        config.typography.styles,
    }),

    ...createLayoutCssVariables({
      presetId:
        config.layout.id,
      page:
        config.layout.page,
      header:
        config.layout.header,
      footer:
        config.layout.footer,
      cover:
        config.layout.cover,
      numbering:
        config.layout.numbering,
      print:
        config.layout.print,
    }),
  };
}

export function createDesignStyleSheet(
  configuration = {}
) {
  const config =
    resolveDesignConfiguration(configuration);

  const variables =
    createDesignCssVariables(config);

  const variableText = Object.entries(
    variables
  )
    .map(
      ([name, value]) =>
        `  ${name}: ${value};`
    )
    .join("\n");

  const printCss = createPrintCss({
    presetId:
      config.layout.id,
    page:
      config.layout.page,
    header:
      config.layout.header,
    footer:
      config.layout.footer,
    cover:
      config.layout.cover,
    numbering:
      config.layout.numbering,
    print:
      config.layout.print,
  });

  return `
:root {
${variableText}
}

.lumina-document {
  font-family: var(--doc-body-font);
  font-size: var(--doc-body-size);
  line-height: var(--doc-line-height);
  color: var(--doc-text);
  background: var(--doc-background);
}

.lumina-document-page {
  width: var(--doc-page-width);
  min-height: var(--doc-page-height);
  padding:
    var(--doc-margin-top)
    var(--doc-margin-right)
    var(--doc-margin-bottom)
    var(--doc-margin-left);
  box-sizing: border-box;
  position: relative;
  overflow: hidden;
  background: var(--doc-background);
  color: var(--doc-text);
  box-shadow:
    0 18px 55px rgba(0, 0, 0, 0.16);
}

.lumina-document h1,
.lumina-document h2,
.lumina-document h3,
.lumina-document h4 {
  font-family: var(--doc-heading-font);
  color: var(--doc-heading);
}

.lumina-document h1 {
  font-size: var(--doc-h1-size);
}

.lumina-document h2 {
  font-size: var(--doc-h2-size);
}

.lumina-document h3 {
  font-size: var(--doc-h3-size);
}

.lumina-document table {
  width: 100%;
  border-collapse: collapse;
}

.lumina-document th {
  background: var(--doc-table-header);
  color: var(--doc-table-header-text);
  border:
    1px solid var(--doc-table-border);
}

.lumina-document td {
  border:
    1px solid var(--doc-table-border);
}

.lumina-document tbody tr:nth-child(even) {
  background: var(--doc-table-stripe);
}

.lumina-document-callout {
  background:
    var(--doc-callout-background);
  border-left:
    4px solid var(--doc-callout-border);
}

.lumina-document-warning {
  background:
    var(--doc-warning-background);
  border-left:
    4px solid var(--doc-warning-border);
}

${printCss}
`;
}

export function applyDesignToElement(
  element,
  configuration = {}
) {
  if (!element) {
    return null;
  }

  const config =
    resolveDesignConfiguration(configuration);

  const variables =
    createDesignCssVariables(config);

  const pageStyle =
    layoutToPageStyle({
      presetId:
        config.layout.id,
      page:
        config.layout.page,
      header:
        config.layout.header,
      footer:
        config.layout.footer,
      cover:
        config.layout.cover,
      numbering:
        config.layout.numbering,
      print:
        config.layout.print,
    });

  Object.entries(variables).forEach(
    ([name, value]) => {
      if (
        value !== undefined &&
        value !== null
      ) {
        element.style.setProperty(
          name,
          String(value)
        );
      }
    }
  );

  Object.entries(pageStyle).forEach(
    ([name, value]) => {
      element.style[name] = value;
    }
  );

  element.classList.add(
    "lumina-document",
    "lumina-document-page"
  );

  element.dataset.designProfile =
    config.profile.id;

  element.dataset.documentTheme =
    config.theme.id;

  element.dataset.typographyPreset =
    config.typography.id;

  element.dataset.layoutPreset =
    config.layout.id;

  return config;
}

export function createStyledComponent(
  componentDefinition,
  configuration = {}
) {
  const config =
    resolveDesignConfiguration(configuration);

  const component = normalizeComponent(
    componentDefinition?.type
      ? componentDefinition
      : createComponent(
          componentDefinition
        )
  );

  const validation =
    validateComponent(component);

  if (!validation.valid) {
    return {
      component,
      style: {},
      validation,
    };
  }

  return {
    component,
    style:
      getComponentDefaultStyle(
        component,
        config.theme
      ),
    typography:
      createTypographyClassMap({
        presetId:
          config.typography.id,
        headingFont:
          config.typography.headingFont,
        bodyFont:
          config.typography.bodyFont,
        styles:
          config.typography.styles,
      }),
    validation,
  };
}

export function composeDocument({
  id,
  title = "",
  subtitle = "",
  profileId =
    DOCUMENT_PROFILE_IDS.CORPORATE_GENERAL,
  configuration = {},
  components = [],
  metadata = {},
} = {}) {
  const design =
    createDesignConfiguration({
      profileId,
      ...configuration,
      metadata: {
        ...configuration.metadata,
        ...metadata,
      },
    });

  const normalizedComponents =
    components.map((component) =>
      createStyledComponent(
        component,
        design
      )
    );

  const invalidComponents =
    normalizedComponents.filter(
      (entry) =>
        !entry.validation.valid
    );

  return {
    id:
      id ||
      `document-${Date.now()}`,

    title,
    subtitle,

    profileId:
      design.profile.id,

    design,

    components:
      normalizedComponents.map(
        (entry) => entry.component
      ),

    componentStyles:
      normalizedComponents.map(
        (entry) => ({
          id: entry.component.id,
          style: entry.style,
          typography:
            entry.typography,
        })
      ),

    valid:
      invalidComponents.length === 0,

    errors:
      invalidComponents.flatMap(
        (entry) =>
          entry.validation.errors.map(
            (error) => ({
              componentId:
                entry.component.id,
              error,
            })
          )
      ),

    metadata: {
      createdAt:
        metadata.createdAt ||
        new Date().toISOString(),
      updatedAt:
        new Date().toISOString(),
      version:
        metadata.version || "1.0",
      status:
        metadata.status || "draft",
      ...metadata,
    },
  };
}

export function paginateDocument(
  document,
  {
    maxHeight,
    measureBlock,
  } = {}
) {
  if (!document) {
    return [];
  }

  const contentArea =
    calculateContentArea({
      presetId:
        document.design?.layout?.id,
      page:
        document.design?.layout?.page,
      header:
        document.design?.layout?.header,
      footer:
        document.design?.layout?.footer,
      cover:
        document.design?.layout?.cover,
      numbering:
        document.design?.layout?.numbering,
      print:
        document.design?.layout?.print,
    });

  const resolvedMaxHeight =
    maxHeight ||
    contentArea.contentHeightMm * 3.78;

  return paginateBlocks({
    blocks:
      document.components || [],
    maxHeight:
      resolvedMaxHeight,
    measureBlock,
  });
}

export function updateDocumentDesign(
  document,
  updates = {}
) {
  if (!document) {
    return null;
  }

  const design =
    createDesignConfiguration({
      profileId:
        updates.profileId ||
        document.profileId ||
        document.design?.profile?.id,

      themeId:
        updates.themeId ||
        document.design?.theme?.id,

      typographyPresetId:
        updates.typographyPresetId ||
        document.design?.typography?.id,

      layoutPresetId:
        updates.layoutPresetId ||
        document.design?.layout?.id,

      branding: {
        ...(document.design?.branding || {}),
        ...(updates.branding || {}),
      },

      typography: {
        ...(document.design?.typography || {}),
        ...(updates.typography || {}),
      },

      layout: {
        ...(document.design?.layout || {}),
        ...(updates.layout || {}),
      },

      language:
        updates.language ||
        document.design?.language,

      country:
        updates.country ||
        document.design?.country,

      metadata: {
        ...(document.design?.metadata || {}),
        ...(updates.metadata || {}),
        updatedAt:
          new Date().toISOString(),
      },
    });

  return composeDocument({
    ...document,
    profileId:
      design.profile.id,
    configuration: design,
    components:
      document.components || [],
    metadata: {
      ...(document.metadata || {}),
      updatedAt:
        new Date().toISOString(),
    },
  });
}

export function validateDocumentDesign(
  document
) {
  const errors = [];
  const warnings = [];

  if (!document) {
    return {
      valid: false,
      errors: [
        "Document is required.",
      ],
      warnings,
    };
  }

  if (!document.title) {
    warnings.push(
      "Document title is empty."
    );
  }

  if (!document.design) {
    errors.push(
      "Document design configuration is missing."
    );
  }

  if (
    !Array.isArray(
      document.components
    )
  ) {
    errors.push(
      "Document components must be an array."
    );
  } else {
    document.components.forEach(
      (component) => {
        const result =
          validateComponent(component);

        result.errors.forEach(
          (error) => {
            errors.push(
              `${component.id}: ${error}`
            );
          }
        );
      }
    );
  }

  return {
    valid: errors.length === 0,
    errors,
    warnings,
  };
}

export function serializeDocumentDesign(
  document
) {
  return JSON.stringify(document);
}

export function parseDocumentDesign(
  serialized
) {
  try {
    const document =
      JSON.parse(serialized);

    return composeDocument({
      ...document,
      configuration:
        document.design || {},
      components:
        document.components || [],
    });
  } catch {
    return null;
  }
}

export default {
  version:
    DESIGN_ENGINE_VERSION,

  profileIds:
    DOCUMENT_PROFILE_IDS,

  profiles:
    DOCUMENT_PROFILES,

  getProfile:
    getDocumentProfile,

  getProfileOptions:
    getDocumentProfileOptions,

  createConfiguration:
    createDesignConfiguration,

  resolveConfiguration:
    resolveDesignConfiguration,

  createCssVariables:
    createDesignCssVariables,

  createStyleSheet:
    createDesignStyleSheet,

  applyToElement:
    applyDesignToElement,

  createStyledComponent,

  composeDocument,

  paginateDocument,

  updateDocumentDesign,

  validateDocumentDesign,

  serialize:
    serializeDocumentDesign,

  parse:
    parseDocumentDesign,
};
