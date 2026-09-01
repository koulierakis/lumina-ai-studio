from __future__ import annotations

import asyncio
import importlib

from persistence import SQLitePersistenceProvider


document_router = importlib.import_module("document_studio.router")


def run(coro):
    return asyncio.run(coro)


async def _load_versions(document_id: str, owner: str) -> list[dict]:
    return [
        item
        async for item in document_router.versions_coll.find(
            {"document_id": document_id, "owner_email": owner}, {"_id": 0}
        ).sort("version_number", 1)
    ]


def test_greek_document_save_reopen_edit_and_version_round_trip(tmp_path):
    provider = SQLitePersistenceProvider(tmp_path / "greek-document-roundtrip.db")
    run(provider.initialize())
    document_router.configure_document_studio_router(provider, None, None)
    owner = "owner@example.com"

    initial_text = (
        "Επωνυμία: ΕΜΠΟΡΙΚΗ ΕΛΛΑΔΟΣ ΙΚΕ\n"
        "Αριθμός ΓΕΜΗ: 123456789000\n"
        "Έδρα: Ασκληπιού 10, Τρίκαλα"
    )
    created = run(
        document_router.create_document(
            {
                "title": "Εταιρική Δήλωση",
                "document_type": "declaration",
                "category": "Corporate Registry",
                "country": "GR",
                "language": "el",
                "content_text": initial_text,
                "content_html": (
                    "<article><h1>Εταιρική Δήλωση</h1>"
                    "<p>Επωνυμία: ΕΜΠΟΡΙΚΗ ΕΛΛΑΔΟΣ ΙΚΕ</p>"
                    "<p>Αριθμός ΓΕΜΗ: 123456789000</p>"
                    "<p>Έδρα: Ασκληπιού 10, Τρίκαλα</p></article>"
                ),
            },
            owner,
        )
    )

    reopened = run(document_router.get_document(created.id, owner))
    assert reopened.title == "Εταιρική Δήλωση"
    assert reopened.language == "el"
    assert "ΕΜΠΟΡΙΚΗ ΕΛΛΑΔΟΣ ΙΚΕ" in reopened.content_text
    assert "Τρίκαλα" in reopened.content_html
    assert reopened.version_number == 1

    updated_text = initial_text + "\nΔιαχειριστής: ΙΩΑΝΝΗΣ ΚΟΥΛΙΕΡΑΚΗΣ"
    updated = run(
        document_router.update_document(
            created.id,
            {
                "expected_version": reopened.version_number,
                "content_text": updated_text,
                "content_html": reopened.content_html.replace(
                    "</article>",
                    "<p>Διαχειριστής: ΙΩΑΝΝΗΣ ΚΟΥΛΙΕΡΑΚΗΣ</p></article>",
                ),
                "change_note": "Προσθήκη διαχειριστή",
            },
            owner,
        )
    )
    assert updated.version_number == 2

    reopened_again = run(document_router.get_document(created.id, owner))
    assert reopened_again.version_number == 2
    assert "ΙΩΑΝΝΗΣ ΚΟΥΛΙΕΡΑΚΗΣ" in reopened_again.content_text
    assert "ΙΩΑΝΝΗΣ ΚΟΥΛΙΕΡΑΚΗΣ" in reopened_again.searchable_text

    versions = run(_load_versions(created.id, owner))
    assert [item["version_number"] for item in versions] == [1, 2]
    assert "ΕΜΠΟΡΙΚΗ ΕΛΛΑΔΟΣ ΙΚΕ" in versions[0]["content_text"]
    assert "ΙΩΑΝΝΗΣ ΚΟΥΛΙΕΡΑΚΗΣ" in versions[1]["content_text"]
