from __future__ import annotations

from models import new_id, now_iso
from pydantic import BaseModel, ConfigDict, Field


class CompanyProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=new_id)
    owner_email: str
    company_name: str = "Lumina Corporate Holdings"
    trading_name: str = ""
    legal_form: str = ""
    jurisdiction: str = ""
    registration_number: str = ""
    ein_tax_number: str = ""
    vat_number: str = ""
    registered_office: str = ""
    principal_office: str = ""
    formation_date: str = ""
    status: str = ""
    standing: str = ""
    capital: str = ""
    website: str = ""
    phone: str = ""
    email: str = ""
    corporate_seal: str | None = None
    default_signature: str | None = None
    corporate_logo: str | None = None
    compliance_notes: str = ""
    short_name: str = ""
    lei: str = ""
    mailing_address: str = ""
    beneficial_owners: list[dict] = Field(default_factory=list)
    secretary: list[dict] = Field(default_factory=list)
    document_defaults: dict = Field(default_factory=dict)
    preferred_templates: list[str] = Field(default_factory=list)
    preferred_clauses: list[str] = Field(default_factory=list)
    preferred_signatures: list[str] = Field(default_factory=list)
    preferred_footer: str = ""
    preferred_banking_language: str = ""
    preferred_governing_law: str = ""
    certificates: list[dict] = Field(default_factory=list)
    compliance_status: str = "Pending"
    archived: bool = False
    deleted: bool = False
    members: list[dict] = Field(default_factory=list)
    managers: list[dict] = Field(default_factory=list)
    directors: list[dict] = Field(default_factory=list)
    authorized_signatories: list[dict] = Field(default_factory=list)
    bank_accounts: list[dict] = Field(default_factory=list)
    wallets: list[dict] = Field(default_factory=list)
    logo_media_id: str | None = None
    primary_color: str = "#B9985A"
    secondary_color: str = "#111827"
    accent_color: str = "#E8D8A8"
    font_heading: str = "Georgia"
    font_body: str = "Inter"
    signatures: list[dict] = Field(default_factory=list)
    addresses: list[dict] = Field(default_factory=list)
    contact_information: dict = Field(default_factory=dict)
    legal_information: dict = Field(default_factory=dict)
    branding_system: dict = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class CorporatePerson(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=new_id)
    owner_email: str
    company_profile_id: str | None = None
    full_name: str
    role: str = "Authorized Signatory"
    nationality: str = ""
    passport: str = ""
    government_id: str = ""
    address: str = ""
    email: str = ""
    phone: str = ""
    authority: str = ""
    signature_image: str | None = None
    initials: str = ""
    relationship_to_company: str = ""
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class BankProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=new_id)
    owner_email: str
    company_profile_id: str | None = None
    bank_name: str
    branch: str = ""
    swift: str = ""
    iban: str = ""
    address: str = ""
    compliance_contact: str = ""
    relationship_manager: str = ""
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class ClauseTemplate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=new_id)
    owner_email: str = "system"
    category: str
    title: str
    body: str
    jurisdiction: str = "International"
    tags: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class CompanyVersion(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=new_id)
    company_profile_id: str
    owner_email: str
    version_number: int = 1
    snapshot: dict = Field(default_factory=dict)
    change_note: str = "Company profile update"
    changed_by: str = "owner"
    created_at: str = Field(default_factory=now_iso)


class DocumentFolder(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=new_id)
    owner_email: str
    name: str
    parent_id: str | None = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class DocumentCollection(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=new_id)
    owner_email: str
    name: str
    description: str = ""
    parent_id: str | None = None
    document_ids: list[str] = Field(default_factory=list)
    smart_query: dict = Field(default_factory=dict)
    color: str = "#B9985A"
    icon: str = "collection"
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class DocumentTag(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=new_id)
    owner_email: str
    name: str
    color: str = "#B9985A"
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class CorporateTemplate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    name: str
    category: str
    description: str
    document_type: str
    tags: list[str] = Field(default_factory=list)
    sections: list[dict] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=list)
    premium_features: list[str] = Field(default_factory=list)
    design_schema: dict = Field(default_factory=dict)


class DocumentVersion(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=new_id)
    document_id: str
    owner_email: str
    version_number: int = 1
    title: str
    content_html: str = ""
    content_text: str = ""
    change_note: str = "Initial version"
    metadata: dict = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)


class CorporateDocument(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=new_id)
    owner_email: str
    title: str
    document_type: str = "agreement"
    category: str = "Legal"
    folder_id: str | None = None
    collection_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    country: str = "GR"
    language: str = "el"
    favorite: bool = False
    status: str = "draft"
    template_id: str | None = None
    company_profile_id: str | None = None
    content_html: str = ""
    content_text: str = ""
    searchable_text: str = ""
    metadata: dict = Field(default_factory=dict)
    design: dict = Field(default_factory=dict)
    components: list[dict] = Field(default_factory=list)
    tables: list[dict] = Field(default_factory=list)
    charts: list[dict] = Field(default_factory=list)
    quality_score: dict = Field(default_factory=dict)
    version_number: int = 1
    imported_media_id: str | None = None
    export_media_ids: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    autosaved_at: str | None = None


class DocumentGenerationRequest(BaseModel):
    template_id: str = "premium-agreement"
    title: str
    prompt: str = ""
    creation_mode: str = "template"
    parties: list[str] = Field(default_factory=list)
    jurisdiction: str = "International"
    effective_date: str = "Upon signature"
    fields: dict = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    folder_id: str | None = None
    country: str = "GR"
    language: str = "el"
    company_profile_id: str | None = None


class DocumentAnalysisRequest(BaseModel):
    action: str = "summarize"
    question: str = ""
    comparison_document_id: str | None = None
    required_clauses: list[str] = Field(default_factory=list)


class DocumentOperationRequest(BaseModel):
    operation: str = "improve"
    instruction: str = ""
    target_style: str = "executive"
    language: str = "English"
    source_document_ids: list[str] = Field(default_factory=list)
    preserve_meaning: bool = True


class VersionActionRequest(BaseModel):
    action: str
    name: str | None = None


class DocumentDesignRequest(BaseModel):
    design: dict = Field(default_factory=dict)
    components: list[dict] = Field(default_factory=list)
    tables: list[dict] = Field(default_factory=list)
    charts: list[dict] = Field(default_factory=list)
    cover_style: str = "Corporate"


class PackageBuildRequest(BaseModel):
    package_type: str = "proposal"
    title: str = "Executive Package"
    client: str = "Strategic Client"
    fields: dict = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class DocumentAnalysisResult(BaseModel):
    document_id: str
    action: str
    summary: str
    findings: list[dict] = Field(default_factory=list)
    missing_clauses: list[str] = Field(default_factory=list)
    inconsistencies: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    extracted_information: dict = Field(default_factory=dict)
    classification: dict = Field(default_factory=dict)
    compared_with: str | None = None
    created_at: str = Field(default_factory=now_iso)
