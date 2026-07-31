from models import VideoBrandKit, VideoProject, VideoTemplate
from server import _generate_video_template_from_brief, _normalize_video_project_state


def test_video_project_model_supports_professional_management_fields():
    project = VideoProject(
        owner_email="owner@example.com",
        name="Campaign",
        resolution="4K",
        tags=["hotel"],
        favorite=True,
        collection_ids=["collection-1"],
        state=_normalize_video_project_state({}),
    )

    assert project.resolution == "4K"
    assert project.favorite is True
    assert project.state["tracks"][0]["id"] == "video-1"
    assert project.state["export"]["codec"] == "h264"


def test_ai_template_generation_builds_complete_workflow():
    template = _generate_video_template_from_brief("Create a luxury hotel advertisement", {"colors": ["#111111"]})

    assert "generate-storyboard" in template["workflow"]
    assert "export-social-pack" in template["workflow"]
    assert template["intro"]["typography"] == "elegant serif reveal"
    assert template["musicStyle"].startswith("cinematic")


def test_video_template_and_brand_kit_models_are_persistable():
    template = VideoTemplate(
        owner_email="owner@example.com",
        name="Luxury Hotel",
        scope="company",
        brief="Luxury hotel",
        template={"workflow": ["apply-branding"]},
        favorite=True,
    )
    brand = VideoBrandKit(owner_email="owner@example.com", name="LUMINA Hotels", colors=["#D4AF37"], fonts=["Inter"])

    assert template.scope == "company"
    assert template.favorite is True
    assert brand.colors == ["#D4AF37"]
    assert brand.animations
