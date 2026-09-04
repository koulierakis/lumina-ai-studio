from __future__ import annotations

from models import AiEditJob, GalleryItem, MediaAsset, PhotoBatchJob, PhotoCollection
from server import AI_TOOL_PROMPTS, _clean_tags


def test_photo_studio_ai_catalog_covers_professional_workflows():
    required = {
        'generate', 'remove_bg', 'replace_bg', 'remove_object', 'replace_object',
        'inpaint', 'outpaint', 'expand', 'upscale', 'restore', 'face_restore',
        'identity_preserve', 'style_transfer', 'change_clothes', 'color_correct',
        'relight', 'hdr', 'skin_cleanup', 'portrait_enhance', 'watermark_remove_legal',
        'perspective_correct',
    }

    assert required.issubset(AI_TOOL_PROMPTS.keys())


def test_photo_models_preserve_metadata_tags_collections_and_references():
    media = MediaAsset(owner_email='owner@example.com', filename='a.png', tags=['portrait'], collection_ids=['c1'], metadata={'camera': 'Lumina'})
    gallery = GalleryItem(owner_email='owner@example.com', media_id=media.id, tags=media.tags, collection_ids=media.collection_ids)
    job = AiEditJob(owner_email='owner@example.com', source_media_id=media.id, reference_media_ids=['r1', 'r2'], export_options={'format': 'image/webp'})
    collection = PhotoCollection(owner_email='owner@example.com', name='Client Selects', media_ids=[media.id])
    batch = PhotoBatchJob(owner_email='owner@example.com', source_media_ids=[media.id], operations={'favorite': True})

    assert media.metadata['camera'] == 'Lumina'
    assert gallery.collection_ids == ['c1']
    assert job.reference_media_ids == ['r1', 'r2']
    assert collection.media_ids == [media.id]
    assert batch.operations['favorite'] is True


def test_photo_tag_cleanup_is_search_safe():
    assert _clean_tags([' Portrait ', '', 'CLIENT', 'portrait']) == ['portrait', 'client']


def test_ai_edit_has_atomic_cancel_before_persistence_guard():
    from pathlib import Path
    import server

    source = Path(server.__file__).read_text(encoding="utf-8")
    assert '"status": "finalizing"' in source
    assert 'if not finalize.modified_count:' in source
    assert 'current.get("status") == "canceled"' in source
    assert source.index('if not finalize.modified_count:') < source.index('save_bytes(result.data, result.mime_type, kind="generated")')
