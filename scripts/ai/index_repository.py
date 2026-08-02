from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from urllib import error, request

ROOT = Path(__file__).resolve().parents[2]
QDRANT = os.getenv("QDRANT_URL", "http://127.0.0.1:6333")
OLLAMA = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
MODEL = os.getenv("LUMINA_EMBED_MODEL", "nomic-embed-text")
COLLECTION = "lumina_repository"

ALLOWED = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".json",
    ".md",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".cfg",
    ".ps1",
    ".bat",
}

SKIP = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "build",
    "dist",
    "backups",
    "_local_models",
    "_tools",
    ".lumina-runtime",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "coverage",
    "htmlcov",
    "runtime",
    "playable_release_evidence",
}


def request_json(
    url: str,
    payload: dict | None = None,
    *,
    method: str | None = None,
    timeout: int = 300,
) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=data,
        method=method or ("POST" if data is not None else "GET"),
        headers={"Content-Type": "application/json"},
    )

    with request.urlopen(req, timeout=timeout) as response:
        body = response.read().decode("utf-8")
        return json.loads(body) if body else {}


def request_with_retry(
    url: str,
    payload: dict | None = None,
    *,
    method: str | None = None,
    attempts: int = 5,
) -> dict:
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            return request_json(url, payload, method=method)
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            last_error = RuntimeError(f"HTTP {exc.code} from {url}: {detail}")
        except Exception as exc:
            last_error = exc

        if attempt < attempts:
            time.sleep(attempt * 2)

    raise RuntimeError(str(last_error))


def embed(text: str) -> list[float]:
    clean = text.strip()

    if not clean:
        clean = "empty"

    response = request_with_retry(
        f"{OLLAMA}/api/embed",
        {
            "model": MODEL,
            "input": clean,
            "truncate": True,
        },
    )

    embeddings = response.get("embeddings")

    if not embeddings or not embeddings[0]:
        raise RuntimeError(f"No embedding returned for model {MODEL}")

    return embeddings[0]


def chunks(text: str, size: int = 1800, overlap: int = 150):
    normalized = text.replace("\x00", "").strip()

    if not normalized:
        return

    start = 0
    step = size - overlap

    while start < len(normalized):
        chunk = normalized[start : start + size].strip()

        if chunk:
            yield chunk

        start += step


def repository_files():
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue

        if path.suffix.lower() not in ALLOWED:
            continue

        if any(part in SKIP for part in path.parts):
            continue

        try:
            if path.stat().st_size > 750_000:
                continue
        except OSError:
            continue

        yield path


def recreate_collection(vector_size: int) -> None:
    try:
        request_json(
            f"{QDRANT}/collections/{COLLECTION}",
            method="DELETE",
        )
    except error.HTTPError as exc:
        if exc.code != 404:
            raise

    request_with_retry(
        f"{QDRANT}/collections/{COLLECTION}",
        {
            "vectors": {
                "size": vector_size,
                "distance": "Cosine",
            }
        },
        method="PUT",
    )


def upload_points(points: list[dict]) -> None:
    if not points:
        return

    request_with_retry(
        f"{QDRANT}/collections/{COLLECTION}/points?wait=true",
        {"points": points},
        method="PUT",
    )


def main() -> None:
    print("Checking Ollama embedding model...")
    sample = embed("LUMINA repository memory initialization")

    print(f"Embedding dimensions: {len(sample)}")
    print("Creating Qdrant collection...")
    recreate_collection(len(sample))

    paths = list(repository_files())
    total_files = len(paths)
    indexed_files = 0
    indexed_chunks = 0
    skipped_chunks = 0
    points: list[dict] = []

    print(f"Repository files selected: {total_files}")

    for file_number, path in enumerate(paths, start=1):
        relative_path = path.relative_to(ROOT).as_posix()

        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            print(f"SKIP FILE: {relative_path}: {exc}")
            continue

        file_had_chunk = False

        for chunk_number, chunk in enumerate(chunks(text) or []):
            try:
                vector = embed(chunk)
            except Exception as exc:
                skipped_chunks += 1
                print(f"SKIP CHUNK: {relative_path}:{chunk_number}: {exc}")
                continue

            digest = hashlib.sha256(f"{relative_path}:{chunk_number}".encode()).digest()[:8]

            point_id = int.from_bytes(digest, "big") & ((1 << 63) - 1)

            points.append(
                {
                    "id": point_id,
                    "vector": vector,
                    "payload": {
                        "path": relative_path,
                        "chunk": chunk_number,
                        "text": chunk,
                    },
                }
            )

            indexed_chunks += 1
            file_had_chunk = True

            if len(points) >= 16:
                upload_points(points)
                points.clear()

        if file_had_chunk:
            indexed_files += 1

        if file_number % 25 == 0 or file_number == total_files:
            print(f"Progress: {file_number}/{total_files} files | {indexed_chunks} chunks")

    upload_points(points)

    print("Repository index complete")
    print(f"Indexed files: {indexed_files}")
    print(f"Indexed chunks: {indexed_chunks}")
    print(f"Skipped chunks: {skipped_chunks}")


if __name__ == "__main__":
    main()
