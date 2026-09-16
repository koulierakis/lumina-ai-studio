from __future__ import annotations

import asyncio

import server


class PreferenceCollection:
    def __init__(self):
        self.document = None

    async def find_one(self, query, projection=None):
        del projection
        if self.document and self.document.get("owner_email") == query.get("owner_email"):
            return dict(self.document)
        return None

    async def update_one(self, query, update):
        assert self.document and self.document.get("owner_email") == query.get("owner_email")
        self.document.update(update["$set"])

    async def insert_one(self, document):
        self.document = dict(document)


def test_save_preferences_updates_or_inserts_without_collection_upsert(monkeypatch):
    collection = PreferenceCollection()
    monkeypatch.setattr(server, "preferences_coll", collection)

    first = asyncio.run(server.save_preferences({"theme": "system"}, owner="owner@example.com"))
    second = asyncio.run(server.save_preferences({"dashboard_compact": True}, owner="owner@example.com"))

    assert first["theme"] == "system"
    assert second["theme"] == "system"
    assert second["dashboard_compact"] is True
    assert second["owner_email"] == "owner@example.com"
