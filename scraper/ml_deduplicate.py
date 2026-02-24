"""
ML Book Deduplication Script (Tier 1)
======================================
Uses Sentence Transformer embeddings + Agglomerative Clustering to
deduplicate 48,000+ scraped book records into unique "Book Clusters"
entirely locally, without any API calls.

Pipeline:
  1. Load raw books from all 3 sources (Reddit, Bookclubs.com, Goodreads)
  2. Pre-group by normalized title+author string (catches exact dupes)
  3. Generate semantic embeddings for each pre-group representative
  4. Cluster embeddings using Agglomerative Clustering (cosine similarity)
  5. Assign priority: A = Currently Reading, B = Previously Read
  6. Output sorted clusters to data/ml_deduplicated.json

Usage:
    python scraper/ml_deduplicate.py

Output:
    data/ml_deduplicated.json
"""

import json
import re
import time
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics.pairwise import cosine_similarity

# ─── Configuration ───────────────────────────────────────────────────────────

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

REDDIT_FILE = DATA_DIR / "reddit_books.json"
BOOKCLUBS_FILE = DATA_DIR / "bookclubs_com.json"
GOODREADS_FILE = DATA_DIR / "goodreads_groups.json"

OUTPUT_FILE = DATA_DIR / "ml_deduplicated.json"

# Embedding model: lightweight, fast on CPU, 384-dimensional vectors
MODEL_NAME = "all-MiniLM-L6-v2"

# Clustering threshold: 1 - cosine_similarity
# Lower = stricter (fewer merges), Higher = looser (more merges)
# 0.25 means books need ≥0.75 cosine similarity to merge
DEFAULT_DISTANCE_THRESHOLD = 0.25


# ─── Text Normalization ─────────────────────────────────────────────────────

def normalize_book_string(title: str, author: str) -> str:
    """
    Clean and normalize a title + author into a comparable lowercase string.
    Strips noise like series info, brackets, extra whitespace, punctuation.
    """
    t = title.strip()
    a = author.strip()

    # Strip surrounding brackets like [ A Thousand Splendid Suns ]
    t = re.sub(r"^\s*\[\s*", "", t)
    t = re.sub(r"\s*\]\s*$", "", t)
    # Remove inline bracketed annotations like [Audiobook]
    t = re.sub(r"\[.*?\]", "", t)

    # Remove parenthetical noise: (Book 1), (Series, #3), etc.
    t = re.sub(r"\(.*?\)", "", t)

    # Remove subtitle fluff after colon
    t = re.sub(r":\s*a novel\b", "", t, flags=re.IGNORECASE)
    t = re.sub(r":\s*a memoir\b", "", t, flags=re.IGNORECASE)
    t = re.sub(r":\s*a thriller\b", "", t, flags=re.IGNORECASE)

    # Handle "Title, The" → "The Title" format
    comma_the = re.match(r"^(.+),\s*(The|A|An)$", t, re.IGNORECASE)
    if comma_the:
        t = f"{comma_the.group(2)} {comma_the.group(1)}"

    # Handle "Title by Author" embedded in the title
    by_match = re.match(r"^(.+?)\s+by\s+(.+)$", t, re.IGNORECASE)
    if by_match and not a:
        t = by_match.group(1)
        a = by_match.group(2)

    # Remove all non-alphanumeric characters except spaces
    t = re.sub(r"[^a-zA-Z0-9\s]", "", t)
    a = re.sub(r"[^a-zA-Z0-9\s]", "", a)

    # Collapse whitespace and lowercase
    t = re.sub(r"\s+", " ", t).strip().lower()
    a = re.sub(r"\s+", " ", a).strip().lower()

    # Combine
    if t and a:
        return f"{t} {a}"
    return t or a


# ─── Data Loading ───────────────────────────────────────────────────────────

def load_all_raw_books(
    reddit_path: Path = REDDIT_FILE,
    bookclubs_path: Path = BOOKCLUBS_FILE,
    goodreads_path: Path = GOODREADS_FILE,
) -> list[dict]:
    """
    Load raw books from all three scraped data sources.
    Returns a unified list of book dicts.
    """
    all_books = []

    # Reddit
    if reddit_path.exists():
        with open(reddit_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for b in data.get("books", []):
            # Skip non-book entries
            if b.get("title", "").startswith("Here is the list"):
                continue
            all_books.append({
                "title": b.get("title", ""),
                "author": b.get("author", ""),
                "category": b.get("category", "Previously Read"),
                "club_name": b.get("club_name", "r/bookclub"),
                "source_type": b.get("source_type", "Reddit"),
                "discussion_url": b.get("discussion_url", ""),
                "month": b.get("month", ""),
            })

    # Bookclubs.com
    if bookclubs_path.exists():
        with open(bookclubs_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for b in data.get("books", []):
            all_books.append({
                "title": b.get("title", ""),
                "author": b.get("author", ""),
                "category": b.get("category", "Currently Reading"),
                "club_name": b.get("club_name", "Unknown Club"),
                "source_type": b.get("source_type", "Bookclubs.com"),
                "discussion_url": b.get("discussion_url", ""),
                "member_count": b.get("member_count", 0),
            })

    # Goodreads Groups
    if goodreads_path.exists():
        with open(goodreads_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for b in data.get("books", []):
            all_books.append({
                "title": b.get("title", ""),
                "author": b.get("author", ""),
                "category": b.get("category", "Previously Read"),
                "club_name": b.get("club_name", ""),
                "source_type": b.get("source_type", "Goodreads"),
                "discussion_url": b.get("discussion_url", ""),
                "member_count": b.get("member_count", 0),
                "book_url": b.get("book_url", ""),
            })

    return all_books


# ─── Pre-Grouping (String-Based) ────────────────────────────────────────────

def pre_group_books(books: list[dict]) -> dict[str, list[dict]]:
    """
    Pre-group books by normalized title+author string.
    This catches exact and near-exact duplicates before the ML step,
    dramatically reducing the number of embeddings we need to compute.
    """
    groups: dict[str, list[dict]] = {}
    for book in books:
        key = normalize_book_string(book["title"], book["author"])
        if not key:
            continue
        if key not in groups:
            groups[key] = []
        groups[key].append(book)
    return groups


# ─── ML Clustering ──────────────────────────────────────────────────────────

def cluster_groups_ml(
    groups: dict[str, list[dict]],
    similarity_threshold: float = 0.75,
) -> list[dict]:
    """
    Use Sentence Transformer embeddings + Agglomerative Clustering to
    merge groups that are semantically similar (fuzzy duplicates).

    Args:
        groups: Dict mapping normalized key → list of book records
        similarity_threshold: Minimum cosine similarity to merge (0.0-1.0)

    Returns:
        List of cluster dicts, each with:
          - representative_title
          - representative_author
          - books: list of all book records in the cluster
    """
    keys = list(groups.keys())

    if len(keys) == 0:
        return []

    if len(keys) == 1:
        books = groups[keys[0]]
        return [{
            "representative_title": books[0]["title"],
            "representative_author": books[0]["author"],
            "books": books,
        }]

    print(f"\n  Loading Sentence Transformer model: {MODEL_NAME}")
    model = SentenceTransformer(MODEL_NAME)

    print(f"  Encoding {len(keys)} unique book strings...")
    t0 = time.time()
    embeddings = model.encode(keys, show_progress_bar=True, batch_size=256)
    elapsed = time.time() - t0
    print(f"  Encoding complete in {elapsed:.1f}s")

    # Convert similarity threshold to distance threshold
    # Agglomerative Clustering uses distance = 1 - similarity
    distance_threshold = 1.0 - similarity_threshold

    print(f"  Clustering with distance threshold: {distance_threshold:.2f}")
    clustering = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=distance_threshold,
        metric="cosine",
        linkage="average",
    )
    labels = clustering.fit_predict(embeddings)

    n_clusters = len(set(labels))
    print(f"  Found {n_clusters} unique clusters from {len(keys)} groups")

    # Assemble clusters
    cluster_map: dict[int, list[str]] = {}
    for key, label in zip(keys, labels):
        if label not in cluster_map:
            cluster_map[label] = []
        cluster_map[label].append(key)

    clusters = []
    for label, cluster_keys in cluster_map.items():
        # Merge all books from all groups in this cluster
        all_books = []
        for k in cluster_keys:
            all_books.extend(groups[k])

        # Pick the title from the group with the most books as the representative
        best_key = max(cluster_keys, key=lambda k: len(groups[k]))
        rep = groups[best_key][0]

        clusters.append({
            "representative_title": rep["title"],
            "representative_author": rep["author"],
            "books": all_books,
        })

    return clusters


# ─── Priority Assignment ────────────────────────────────────────────────────

def assign_priority(cluster: dict) -> dict:
    """
    Assign a priority to a cluster based on read status.

    Priority A: At least one book in the cluster is "Currently Reading"
    Priority B: All books are "Previously Read"

    Also computes:
      - club_count: number of distinct clubs
      - has_currently_reading: boolean flag
    """
    books = cluster["books"]
    has_currently_reading = any(
        b.get("category") == "Currently Reading" for b in books
    )

    # Deduplicate clubs
    clubs = []
    seen_clubs = set()
    for b in books:
        club_key = f"{b.get('club_name', '')}|{b.get('source_type', '')}"
        if club_key not in seen_clubs:
            seen_clubs.add(club_key)
            clubs.append({
                "club_name": b.get("club_name", ""),
                "source_type": b.get("source_type", ""),
                "discussion_url": b.get("discussion_url", ""),
                "category": b.get("category", ""),
                "member_count": b.get("member_count", 0),
                "month": b.get("month", ""),
            })

    return {
        "representative_title": cluster["representative_title"],
        "representative_author": cluster["representative_author"],
        "priority": "A" if has_currently_reading else "B",
        "has_currently_reading": has_currently_reading,
        "club_count": len(clubs),
        "clubs": clubs,
    }


# ─── Output ─────────────────────────────────────────────────────────────────

def save_clusters(clusters: list[dict]) -> None:
    """Save the prioritized clusters to JSON."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Sort: Priority A first, then by club_count descending
    clusters.sort(key=lambda c: (c["priority"], -c["club_count"]))

    priority_a = sum(1 for c in clusters if c["priority"] == "A")
    priority_b = sum(1 for c in clusters if c["priority"] == "B")
    total_records = sum(c["club_count"] for c in clusters)

    data = {
        "deduplicated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_clusters": len(clusters),
        "priority_a_count": priority_a,
        "priority_b_count": priority_b,
        "total_club_interactions": total_records,
        "clusters": clusters,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\n  Saved to {OUTPUT_FILE}")


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  ML Book Deduplication (Tier 1)")
    print("=" * 60)

    # Step 1: Load all raw books
    raw_books = load_all_raw_books()
    print(f"\n  Raw books loaded: {len(raw_books)}")

    reddit_count = sum(1 for b in raw_books if b["source_type"] == "Reddit")
    bookclubs_count = sum(1 for b in raw_books if b["source_type"] == "Bookclubs.com")
    goodreads_count = sum(1 for b in raw_books if b["source_type"] == "Goodreads")
    print(f"    Reddit:       {reddit_count}")
    print(f"    Bookclubs:    {bookclubs_count}")
    print(f"    Goodreads:    {goodreads_count}")

    # Step 2: Pre-group by normalized string
    groups = pre_group_books(raw_books)
    print(f"\n  Pre-grouped into {len(groups)} unique keys")
    print(f"  Compression ratio: {len(raw_books)} → {len(groups)} ({100 * (1 - len(groups)/len(raw_books)):.1f}% reduction)")

    # Step 3: ML Clustering
    clusters = cluster_groups_ml(groups)

    # Step 4: Assign priorities
    prioritized = [assign_priority(c) for c in clusters]

    # Step 5: Save
    save_clusters(prioritized)

    # Summary
    priority_a = [c for c in prioritized if c["priority"] == "A"]
    priority_b = [c for c in prioritized if c["priority"] == "B"]
    multi_club = [c for c in prioritized if c["club_count"] > 1]

    print("\n" + "=" * 60)
    print("  DEDUPLICATION COMPLETE — SUMMARY")
    print("=" * 60)
    print(f"  Raw records ingested:        {len(raw_books)}")
    print(f"  String pre-groups:           {len(groups)}")
    print(f"  Final ML clusters:           {len(prioritized)}")
    print(f"  Priority A (Currently Reading): {len(priority_a)}")
    print(f"  Priority B (Previously Read):   {len(priority_b)}")
    print(f"  Books read by 2+ clubs:      {len(multi_club)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
