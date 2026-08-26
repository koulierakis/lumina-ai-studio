from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / ".lumina-runtime" / "database" / "lumina.db"
DEFAULT_STORAGE = ROOT / "backend" / "storage"


def rows(conn: sqlite3.Connection, table: str) -> list[dict]:
    try:
        records = conn.execute(f"SELECT data_json FROM {table}").fetchall()
    except sqlite3.OperationalError:
        return []
    return [json.loads(record[0]) for record in records]


def diagnose(db_path: Path, storage_root: Path) -> dict:
    if not db_path.exists():
        return {"ok": False, "database": str(db_path), "error": "database_not_found", "packs": []}

    with sqlite3.connect(str(db_path)) as conn:
        packs = rows(conn, "identity_packs")
        media = rows(conn, "media")

    media_by_id = {str(item.get("id")): item for item in media if item.get("id")}
    reports = []
    missing_media = 0
    missing_files = 0

    for pack in packs:
        photo_ids = [str(value) for value in pack.get("photo_ids") or []]
        photos = []
        for photo_id in photo_ids:
            asset = media_by_id.get(photo_id)
            if not asset:
                missing_media += 1
                photos.append({"photo_id": photo_id, "media_record": False, "file_exists": False})
                continue
            filename = str(asset.get("filename") or "")
            path = storage_root / "references" / filename
            exists = bool(filename) and path.is_file()
            if not exists:
                missing_files += 1
            photos.append({
                "photo_id": photo_id,
                "media_record": True,
                "filename": filename,
                "file_exists": exists,
                "mime_type": asset.get("mime_type"),
            })
        reports.append({
            "id": pack.get("id"),
            "name": pack.get("name"),
            "photo_count": len(photo_ids),
            "primary_photo_id": pack.get("primary_photo_id"),
            "photos": photos,
        })

    return {
        "ok": missing_media == 0 and missing_files == 0,
        "database": str(db_path),
        "storage_root": str(storage_root),
        "pack_count": len(packs),
        "reference_count": sum(item["photo_count"] for item in reports),
        "missing_media_records": missing_media,
        "missing_reference_files": missing_files,
        "packs": reports,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only LUMINA Identity Pack integrity diagnostic")
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--storage", type=Path, default=Path(os.environ.get("STORAGE_DIR", DEFAULT_STORAGE)))
    args = parser.parse_args()
    report = diagnose(args.database.expanduser().resolve(), args.storage.expanduser().resolve())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report.get("ok") else 1)


if __name__ == "__main__":
    main()
