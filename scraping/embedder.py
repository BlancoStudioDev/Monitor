#!/usr/bin/env python3
"""
News Article Embedder
=====================
Embeds scraped news articles using BGE-M3 and stores them in a ChromaDB
vector database for cosine-similarity search.

Embedding logic:
  - If only description exists  → embed description
  - If only title exists         → embed title
  - If both exist                → embed "title. description", producing a single vector

Usage:
  python embedder.py                    # Embed all articles
  python embedder.py --query "search"   # Search for similar articles
  python embedder.py --reset            # Wipe the DB and re-embed
"""

import argparse
import glob
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import chromadb
import numpy as np
from FlagEmbedding import BGEM3FlagModel

# ─── Configuration ──────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
DB_DIR = SCRIPT_DIR / "vectordb"
COLLECTION_NAME = "news_articles"
MODEL_NAME = "BAAI/bge-m3"
BATCH_SIZE = 32
MAX_LENGTH = 8192


# ─── JSON loaders ───────────────────────────────────────────────────────────

def _normalise_article(raw: dict, source_file: str) -> dict | None:
    """
    Normalise an article dict coming from *any* scraper into a unified schema:
      { title, link, source, description }
    Returns None if the article has neither title nor description.
    """
    # Determine the scraper source from the file path (e.g. "reuters", "apnews")
    scraper_name = Path(source_file).parent.name

    # --- title ---
    title = (raw.get("title") or "").strip()

    # --- link ---
    link = (raw.get("link") or raw.get("url") or "").strip()

    # --- source / category ---
    source = (
        raw.get("source")
        or raw.get("country")
        or raw.get("category")
        or ""
    ).strip()
    # Always prepend the scraper name so we know where it came from
    source = f"{scraper_name}/{source}" if source else scraper_name

    # --- description ---
    description = (raw.get("description") or "").strip()

    # Skip if we have nothing to embed
    if not title and not description:
        return None

    return {
        "title": title,
        "link": link,
        "source": source,
        "description": description,
    }


def load_articles(json_path: str) -> list[dict]:
    """Load and normalise articles from a single JSON file."""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Two known shapes: list of articles, or { ..., "articles": [...] }
    if isinstance(data, list):
        raw_articles = data
    elif isinstance(data, dict) and "articles" in data:
        raw_articles = data["articles"]
    else:
        print(f"  ⚠  Unknown JSON structure in {json_path}, skipping.")
        return []

    articles = []
    for raw in raw_articles:
        article = _normalise_article(raw, json_path)
        if article is not None:
            articles.append(article)
    return articles


def discover_json_files() -> list[str]:
    """
    Auto-discover every `articles.json` inside subdirectories.
    This makes the embedder future-proof for new scrapers.
    """
    pattern = str(SCRIPT_DIR / "*" / "articles.json")
    paths = sorted(glob.glob(pattern))
    return paths


# ─── Embedding helpers ──────────────────────────────────────────────────────

def build_text_for_embedding(article: dict) -> str:
    """
    Build the text that will be embedded.
    - description only  → description
    - title only        → title
    - both              → "title. description"
    """
    title = article["title"]
    desc = article["description"]

    if title and desc:
        return f"{title}. {desc}"
    return desc or title


def article_id(article: dict) -> str:
    """Deterministic ID based on the link (or title+source as fallback)."""
    key = article["link"] or f"{article['title']}|{article['source']}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


# ─── Main pipeline ──────────────────────────────────────────────────────────

def embed_and_store(reset: bool = False) -> None:
    """Load all articles, embed them with BGE-M3, and upsert into ChromaDB."""

    # 1. Discover JSON files
    json_files = discover_json_files()
    if not json_files:
        print("❌ No articles.json files found in subdirectories.")
        sys.exit(1)

    print(f"📂 Found {len(json_files)} JSON file(s):")
    for p in json_files:
        print(f"   • {p}")

    # 2. Load & normalise all articles
    all_articles: list[dict] = []
    for path in json_files:
        arts = load_articles(path)
        print(f"   ✔ {Path(path).parent.name}: {len(arts)} articles loaded")
        all_articles.extend(arts)

    if not all_articles:
        print("❌ No articles to embed.")
        sys.exit(1)

    print(f"\n📰 Total articles to embed: {len(all_articles)}")

    # 3. Deduplicate by article_id
    seen: dict[str, dict] = {}
    for art in all_articles:
        aid = article_id(art)
        seen[aid] = art
    all_articles = list(seen.values())
    ids = list(seen.keys())
    print(f"   (after dedup: {len(all_articles)})")

    # 4. Initialise the embedding model
    print(f"\n🤖 Loading BGE-M3 model ({MODEL_NAME}) …")
    t0 = time.time()
    model = BGEM3FlagModel(MODEL_NAME, use_fp16=True)
    print(f"   Model loaded in {time.time() - t0:.1f}s")

    # 5. Build texts
    texts = [build_text_for_embedding(a) for a in all_articles]

    # 6. Encode in batches
    print(f"\n🔢 Encoding {len(texts)} texts (batch_size={BATCH_SIZE}) …")
    t0 = time.time()
    output = model.encode(texts, batch_size=BATCH_SIZE, max_length=MAX_LENGTH)
    embeddings = output["dense_vecs"]  # np.ndarray (N, dim)
    print(f"   Encoding done in {time.time() - t0:.1f}s  |  dim={embeddings.shape[1]}")

    # 7. Store in ChromaDB
    print("\n💾 Storing in ChromaDB …")
    client = chromadb.PersistentClient(path=str(DB_DIR))

    if reset:
        # delete if exists
        try:
            client.delete_collection(COLLECTION_NAME)
            print("   🗑  Existing collection deleted.")
        except Exception:
            pass

    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    # Prepare metadata (ChromaDB needs lists of dicts)
    metadatas = [
        {
            "title": a["title"],
            "link": a["link"],
            "source": a["source"],
            "description": a["description"],
        }
        for a in all_articles
    ]

    # Upsert (handles both insert and update)
    # ChromaDB expects lists of plain Python floats
    emb_lists = embeddings.tolist()

    # Upsert in chunks to avoid oversized requests
    CHUNK = 500
    for i in range(0, len(ids), CHUNK):
        collection.upsert(
            ids=ids[i : i + CHUNK],
            embeddings=emb_lists[i : i + CHUNK],
            metadatas=metadatas[i : i + CHUNK],
            documents=texts[i : i + CHUNK],
        )

    print(f"   ✅ {collection.count()} vectors stored in '{COLLECTION_NAME}'.")
    print(f"   📁 DB path: {DB_DIR}")


# ─── Query / search ─────────────────────────────────────────────────────────

def search(query: str, n_results: int = 10) -> None:
    """Search the vector DB by cosine similarity."""

    print(f"\n🔍 Searching for: \"{query}\"")
    print(f"   Loading model …")
    model = BGEM3FlagModel(MODEL_NAME, use_fp16=True)

    output = model.encode([query], max_length=MAX_LENGTH)
    q_vec = output["dense_vecs"].tolist()

    client = chromadb.PersistentClient(path=str(DB_DIR))

    try:
        collection = client.get_collection(COLLECTION_NAME)
    except Exception:
        print("❌ No collection found. Run `python embedder.py` first to embed articles.")
        sys.exit(1)

    results = collection.query(
        query_embeddings=q_vec,
        n_results=n_results,
        include=["metadatas", "distances", "documents"],
    )

    print(f"\n── Top {n_results} results ──────────────────────────────────────")
    for i, (meta, dist, doc) in enumerate(
        zip(results["metadatas"][0], results["distances"][0], results["documents"][0]),
        start=1,
    ):
        similarity = 1 - dist  # cosine distance → similarity
        print(f"\n  {i}. [{similarity:.4f}]  {meta['title']}")
        print(f"     Source : {meta['source']}")
        if meta["description"]:
            print(f"     Desc   : {meta['description'][:120]}…")
        print(f"     Link   : {meta['link']}")


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Embed news articles with BGE-M3 and store in ChromaDB.",
    )
    parser.add_argument(
        "--query", "-q",
        type=str,
        default=None,
        help="Search query for cosine-similarity search.",
    )
    parser.add_argument(
        "--n-results", "-n",
        type=int,
        default=10,
        help="Number of results to return for a query (default: 10).",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete existing collection and re-embed everything.",
    )
    args = parser.parse_args()

    if args.query:
        search(args.query, n_results=args.n_results)
    else:
        embed_and_store(reset=args.reset)


if __name__ == "__main__":
    main()
