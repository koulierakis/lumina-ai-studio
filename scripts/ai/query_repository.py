from __future__ import annotations

import argparse
import os

from lumina_http import request_json

QDRANT = os.getenv("QDRANT_URL", "http://127.0.0.1:6333")
OLLAMA = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
MODEL = os.getenv("LUMINA_EMBED_MODEL", "nomic-embed-text")
COLLECTION = os.getenv("LUMINA_QDRANT_COLLECTION", "lumina_repository")


def embed(text: str) -> list[float]:
    response = request_json(f"{OLLAMA}/api/embeddings", {"model": MODEL, "prompt": text})
    vector = response.get("embedding")
    if not vector:
        raise RuntimeError(f"Ollama returned no embedding for model {MODEL}")
    return vector


def search(vector: list[float], limit: int) -> list[dict]:
    payload = {"vector": vector, "limit": limit, "with_payload": True, "with_vector": False}
    try:
        response = request_json(f"{QDRANT}/collections/{COLLECTION}/points/search", payload)
        return response.get("result", [])
    except RuntimeError:
        response = request_json(
            f"{QDRANT}/collections/{COLLECTION}/points/query",
            {"query": vector, "limit": limit, "with_payload": True, "with_vector": False},
        )
        result = response.get("result", {})
        return result.get("points", result if isinstance(result, list) else [])


def main() -> None:
    parser = argparse.ArgumentParser(description="Search the indexed LUMINA repository")
    parser.add_argument("query", nargs="+", help="Question or semantic code search")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--full", action="store_true", help="Print full chunks")
    args = parser.parse_args()

    question = " ".join(args.query)
    results = search(embed(question), args.limit)
    if not results:
        raise SystemExit(
            "No indexed repository results found. Run: .\\scripts\\lumina-dev.ps1 index"
        )

    for position, result in enumerate(results, start=1):
        payload = result.get("payload") or {}
        path = payload.get("path", "unknown")
        chunk = payload.get("chunk", "?")
        score = float(result.get("score", 0.0))
        text = str(payload.get("text", "")).strip()
        if not args.full and len(text) > 900:
            text = text[:900].rstrip() + "\n..."
        print(f"\n[{position}] score={score:.4f} path={path} chunk={chunk}\n{'-' * 80}\n{text}")


if __name__ == "__main__":
    main()
