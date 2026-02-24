"""
Book Enrichment & Deduplication Script — Tier 2: Prioritized API Fetching
=========================================================================
Post-processes locally deduplicated "Book Clusters" by looking up each
cluster on the Google Books API to get canonical metadata.

Because the free API quota is strictly limited to **1,000 calls / day**,
this script prioritises:

  1. Books marked "Currently Reading" on *any* platform.
  2. The most popular books (by total member count across clubs).

Books beyond the quota are emitted with their raw title / author only.

Usage:
    python -m scraper.enrich_books          # standard run
    python -m scraper.enrich_books --quota 500  # override quota

Input:
    data/reddit_books.json
    data/bookclubs_com.json
    data/goodreads_groups.json

Output:
    data/enriched_books.json
"""

from __future__ import annotations

import asyncio
import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

# Third-party — install with: pip install aiohttp python-dotenv
import aiohttp
import os
from dotenv import load_dotenv

# ─── Configuration ───────────────────────────────────────────────────────────

# Load .env variables
load_dotenv(Path(__file__).resolve().parent / ".env")
API_KEY = os.getenv("GOOGLE_BOOKS_API_KEY")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
REDDIT_FILE = DATA_DIR / "reddit_books.json"
BOOKCLUBS_FILE = DATA_DIR / "bookclubs_com.json"
GOODREADS_FILE = DATA_DIR / "goodreads_groups.json"
OUTPUT_FILE = DATA_DIR / "enriched_books.json"
CACHE_FILE = DATA_DIR / ".google_books_cache.json"

GOOGLE_BOOKS_API = "https://www.googleapis.com/books/v1/volumes"
DAILY_API_QUOTA = 1_000
MAX_CONCURRENT = 1
PER_REQUEST_DELAY = 0.66  # ~1.5 requests/sec (90/min), riding close to the 100/min quota
REQUEST_TIMEOUT = 15

# Priority scoring constants
CURRENTLY_READING_BONUS = 1_000_000  # guarantees CR books always rank first
CLUB_APPEARANCE_BONUS = 500          # per additional club reading the same book


# ─── Text Cleaning Helpers ──────────────────────────────────────────────────

def clean_for_search(title: str, author: str) -> str:
    """Build a clean search query from a messy title + author."""
    t = title

    # Remove brackets like [ A Thousand Splendid Suns ]
    t = re.sub(r"^\[?\s*", "", t)
    t = re.sub(r"\s*\]?\s*$", "", t)

    # Remove duplicate title patterns like "Title ] [ TITLE"
    if "] [" in t or "] [" in t:
        t = t.split("]")[0].strip(" [")

    # Remove parenthetical noise: (Book 1), (The Series, 1), (100 Baking...)
    t = re.sub(r"\(.*?\)", "", t)

    # Remove common subtitle fluff after colon
    subtitle_fluff = [
        r":\s*a novel\b",
        r":\s*a memoir\b",
        r":\s*a thriller\b",
        r":\s*a.*?book club pick\b",
        r":\s*an? .*?best book\b",
        r":\s*read with jenna\b",
    ]
    for pattern in subtitle_fluff:
        t = re.sub(pattern, "", t, flags=re.IGNORECASE)

    # If title embeds author like "1984 by George Orwell", extract it
    by_match = re.match(r"^(.+?)\s+by\s+(.+)$", t, re.IGNORECASE)
    if by_match and not author:
        t = by_match.group(1)
        author = by_match.group(2)

    # Clean up
    t = t.strip(" .:;,-–—")
    t = re.sub(r"\s+", " ", t).strip()

    # Build query
    query = t
    if author:
        first_author = author.split(" and ")[0].split(",")[0].strip()
        query = f"{t} {first_author}"

    return query


def normalize_key(title: str, author: str) -> str:
    """Create a grouping key from raw title + author for pre-grouping."""
    t = clean_for_search(title, author).lower()
    t = re.sub(r"[^a-z0-9\s]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


# ─── Cluster Construction ──────────────────────────────────────────────────

def build_cluster_from_books(key: str, books: list[dict]) -> dict:
    """
    Build a cluster dict from a list of raw book records that share a
    normalized key.  The cluster carries aggregate stats used for priority
    scoring.
    """
    is_cr = any(
        b.get("category", "").lower() == "currently reading"
        for b in books
    )
    total_members = sum(b.get("member_count", 0) for b in books)
    num_clubs = len({b.get("club_name", "") for b in books})

    rep = books[0]
    return {
        "key": key,
        "representative_title": rep.get("title", ""),
        "representative_author": rep.get("author", ""),
        "is_currently_reading": is_cr,
        "total_member_count": total_members,
        "num_clubs": num_clubs,
        "books": books,
    }


# ─── Priority Scoring ──────────────────────────────────────────────────────

def compute_priority_score(cluster: dict) -> int:
    """
    Compute a numeric priority score for a cluster.

    Currently-Reading clusters get a massive bonus so they always land
    inside the API budget.  Among non-CR clusters the score is driven by
    total member count + a small bonus per additional club.
    """
    score = 0
    if cluster["is_currently_reading"]:
        score += CURRENTLY_READING_BONUS
    score += cluster["total_member_count"]
    score += cluster["num_clubs"] * CLUB_APPEARANCE_BONUS
    return score


def sort_clusters_by_priority(clusters: list[dict]) -> list[dict]:
    """Return clusters sorted descending by priority score."""
    return sorted(clusters, key=compute_priority_score, reverse=True)


def slice_budget(
    sorted_clusters: list[dict],
    quota: int = DAILY_API_QUOTA,
) -> tuple[list[dict], list[dict]]:
    """
    Split a priority-sorted cluster list into:
      - ``to_fetch``:  the top *quota* clusters that will hit the API
      - ``remainder``: everything else – these keep raw title / author
    """
    to_fetch = sorted_clusters[:quota]
    remainder = sorted_clusters[quota:]
    return to_fetch, remainder


# ─── Google Books – single async lookup ─────────────────────────────────────

async def fetch_single(
    session: aiohttp.ClientSession,
    query: str,
    key: str,
    sem: asyncio.Semaphore,
    cache: dict,
) -> dict | None:
    """
    Look up *one* query on the Google Books API.

    * Uses a semaphore for concurrency limiting.
    * Checks the in-memory cache first; populates it on success.
    * Returns the parsed volume-info dict, or ``None`` on failure.
    """
    # ── cache hit ──
    if key in cache:
        return cache[key]

    # ── rate-limited API call ──
    async with sem:
        await asyncio.sleep(PER_REQUEST_DELAY)
        try:
            params = {"q": query, "maxResults": 1, "printType": "books"}
            if API_KEY:
                params["key"] = API_KEY

            async with session.get(
                GOOGLE_BOOKS_API,
                params=params,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                if resp.status != 200:
                    data = await resp.text()
                    print(f"    [!] HTTP {resp.status} for: {query} -> {data}")
                    return None

                data = await resp.json()

                if not data.get("items"):
                    cache[key] = None
                    return None

                vol = data["items"][0]["volumeInfo"]
                result = {
                    "google_books_id": data["items"][0].get("id", ""),
                    "canonical_title": vol.get("title", ""),
                    "canonical_author": ", ".join(vol.get("authors", [])),
                    "categories": vol.get("categories", []),
                    "page_count": vol.get("pageCount"),
                    "published_date": vol.get("publishedDate", ""),
                    "thumbnail": vol.get("imageLinks", {}).get("thumbnail", ""),
                    "description": (vol.get("description", "") or "")[:300],
                }
                cache[key] = result
                return result

        except Exception as e:
            print(f"    [!] API error for '{query}': {e}")
            return None


# ─── Google Books – batch async fetching ────────────────────────────────────

async def fetch_batch(
    clusters: list[dict],
    cache: dict,
    max_concurrent: int = MAX_CONCURRENT,
) -> list[dict]:
    """
    Fetch Google Books metadata for a list of clusters concurrently.

    Returns a list of dicts ``{ "cluster": …, "api_result": … }``
    where ``api_result`` may be ``None`` on failure.
    """
    sem = asyncio.Semaphore(max_concurrent)
    results: list[dict] = []

    async with aiohttp.ClientSession() as session:
        tasks = []
        for cluster in clusters:
            query = clean_for_search(
                cluster["representative_title"],
                cluster["representative_author"],
            )
            key = cluster["key"]

            async def _do(q=query, k=key, c=cluster):
                api_res = await fetch_single(session, q, k, sem, cache)
                return {"cluster": c, "api_result": api_res}

            tasks.append(_do())

        results = await asyncio.gather(*tasks, return_exceptions=False)

    return list(results)


ML_FILE = DATA_DIR / "ml_deduplicated.json"

# ─── Data Loading (From Tier 1) ─────────────────────────────────────────────

def load_ml_clusters() -> list[dict]:
    """Load pre-computed ML deduplicated clusters from Tier 1."""
    if not ML_FILE.exists():
        print(f"[!] Critical Error: {ML_FILE} not found. Run ML deduplication first.")
        sys.exit(1)
        
    with open(ML_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    clusters = []
    for c in data.get("clusters", []):
        t = c["representative_title"]
        a = c["representative_author"]
        key = normalize_key(t, a)
        
        total_members = sum(club.get("member_count", 0) for club in c.get("clubs", []))
        
        # Reconstruct exactly what enrich_books expects for downstream processing
        books = []
        for club in c.get("clubs", []):
            books.append({
                "title": t, 
                "author": a,
                "club_name": club.get("club_name", ""),
                "source_type": club.get("source_type", ""),
                "discussion_url": club.get("discussion_url", ""),
                "month": club.get("month", ""),
            })

        clusters.append({
            "key": key,
            "representative_title": t,
            "representative_author": a,
            "is_currently_reading": c["has_currently_reading"],
            "total_member_count": total_members,
            "num_clubs": c["club_count"],
            "books": books,
        })
    return clusters


# ─── Cache Management ──────────────────────────────────────────────────────

def load_cache() -> dict:
    """Load persistent cache of previous API lookups."""
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_cache(cache: dict) -> None:
    """Save cache to disk."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


# ─── Enriched Output Assembly ──────────────────────────────────────────────

def assemble_enriched(
    fetched: list[dict],
    remainder: list[dict],
) -> list[dict]:
    """
    Merge API-enriched clusters and raw remainder clusters into a single
    deduplicated list grouped by Google Books ID (or raw key for remainder).
    """
    enriched_by_gid: dict[str, dict] = {}
    no_match: list[dict] = []

    # ── Process API-fetched clusters ──
    for item in fetched:
        cluster = item["cluster"]
        gb = item["api_result"]
        books = cluster["books"]

        if not gb or not gb.get("google_books_id"):
            # API returned nothing → treat like a remainder cluster
            no_match.append(_make_raw_entry(cluster))
            continue

        gid = gb["google_books_id"]
        if gid not in enriched_by_gid:
            enriched_by_gid[gid] = {
                "google_books_id": gid,
                "canonical_title": gb["canonical_title"],
                "canonical_author": gb["canonical_author"],
                "categories": gb["categories"],
                "page_count": gb["page_count"],
                "published_date": gb["published_date"],
                "thumbnail": gb["thumbnail"],
                "description": gb["description"],
                "clubs": [],
            }

        for b in books:
            enriched_by_gid[gid]["clubs"].append(_club_entry(b))

    # ── Process remainder clusters (no API call) ──
    for cluster in remainder:
        no_match.append(_make_raw_entry(cluster))

    # ── Final merge by canonical title|author ──
    final_merged: dict[str, dict] = {}
    for entry in list(enriched_by_gid.values()) + no_match:
        norm_title = re.sub(r"[^a-z0-9\s]", "", entry["canonical_title"].lower()).strip()
        norm_author = re.sub(r"[^a-z0-9\s]", "", entry["canonical_author"].lower()).strip()
        merge_key = f"{norm_title}|{norm_author}"

        if merge_key not in final_merged:
            final_merged[merge_key] = entry
        else:
            final_merged[merge_key]["clubs"].extend(entry["clubs"])
            existing = final_merged[merge_key]
            if not existing.get("categories") and entry.get("categories"):
                existing["categories"] = entry["categories"]
            if not existing.get("page_count") and entry.get("page_count"):
                existing["page_count"] = entry["page_count"]
            if not existing.get("thumbnail") and entry.get("thumbnail"):
                existing["thumbnail"] = entry["thumbnail"]

    all_enriched = list(final_merged.values())

    # Sort clubs within each entry: Reddit first, then alphabetically
    for entry in all_enriched:
        entry["clubs"].sort(
            key=lambda c: (0 if c["source_type"] == "Reddit" else 1, c["club_name"])
        )

    return all_enriched


def _club_entry(book: dict) -> dict:
    return {
        "club_name": book.get("club_name", ""),
        "source_type": book.get("source_type", ""),
        "discussion_url": book.get("discussion_url", ""),
        "month": book.get("month", ""),
        "original_title": book.get("title", ""),
    }


def _make_raw_entry(cluster: dict) -> dict:
    """Build an enriched-format entry with raw data only (no API metadata)."""
    return {
        "canonical_title": cluster["representative_title"],
        "canonical_author": cluster["representative_author"],
        "categories": [],
        "page_count": None,
        "published_date": "",
        "thumbnail": "",
        "description": "",
        "clubs": [_club_entry(b) for b in cluster["books"]],
    }


# ─── Save Output ───────────────────────────────────────────────────────────

def save_enriched(enriched: list[dict]) -> None:
    """Save the enriched, deduplicated data to JSON."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    total_clubs = sum(len(e["clubs"]) for e in enriched)
    with_genre = sum(1 for e in enriched if e.get("categories"))
    multi_club = sum(1 for e in enriched if len(e["clubs"]) > 1)

    all_genres: set[str] = set()
    for e in enriched:
        for cat in e.get("categories", []):
            all_genres.add(cat)

    output = {
        "enriched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "stats": {
            "total_unique_books": len(enriched),
            "total_club_interactions": total_clubs,
            "books_with_genre": with_genre,
            "books_read_by_multiple_clubs": multi_club,
            "all_genres": sorted(all_genres),
        },
        "books": sorted(enriched, key=lambda e: e["canonical_title"].lower()),
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n  Saved to {OUTPUT_FILE}")


# ─── Full Pipeline (async entry-point) ──────────────────────────────────────

async def enrich_pipeline(quota: int = DAILY_API_QUOTA) -> list[dict]:
    """
    End-to-end enrichment pipeline (async).

    1. Load raw books from all sources
    2. Tier 1 local deduplication → clusters
    3. Priority sort
    4. Slice budget (top *quota* get API calls)
    5. Async batch fetch for top clusters
    6. Assemble enriched output (API + remainder)
    7. Save
    """
    print("=" * 60)
    print("  Book Enrichment — Tier 2: Prioritised API Fetching")
    print("=" * 60)

    # Step 1 & 2: Load ML deduplicated clusters from Tier 1
    clusters = load_ml_clusters()
    print(f"\n  Loaded {len(clusters)} Tier 1 ML clusters")

    # Step 3: Priority sort
    sorted_clusters = sort_clusters_by_priority(clusters)

    cr_count = sum(1 for c in sorted_clusters if c["is_currently_reading"])
    print(f"  Currently-Reading clusters: {cr_count}")

    # Step 4: Budget slice
    cache = load_cache()
    cache_hits = sum(1 for c in sorted_clusters[:quota] if c["key"] in cache)
    print(f"  Cache has {len(cache)} previous lookups ({cache_hits} would be hits)")

    to_fetch, remainder = slice_budget(sorted_clusters, quota=quota)
    print(f"  API budget: {quota}  →  fetching {len(to_fetch)}, skipping {len(remainder)}")

    # Step 5: Async batch fetch
    print(f"\n  Fetching {len(to_fetch)} clusters from Google Books API "
          f"({MAX_CONCURRENT} concurrent, {PER_REQUEST_DELAY}s delay)...")
    fetched = await fetch_batch(to_fetch, cache=cache, max_concurrent=MAX_CONCURRENT)

    api_calls = sum(
        1 for item in fetched
        if item["cluster"]["key"] not in cache or cache.get(item["cluster"]["key"]) is None
    )
    print(f"  API calls made: ~{api_calls}   (rest were cache hits)")

    # Save cache periodically
    save_cache(cache)

    # Step 6: Assemble
    enriched = assemble_enriched(fetched, remainder)

    # Step 7: Save
    save_enriched(enriched)

    # Summary
    total_clubs = sum(len(e["clubs"]) for e in enriched)
    with_genre = sum(1 for e in enriched if e.get("categories"))
    multi_club = sum(1 for e in enriched if len(e["clubs"]) > 1)

    total_raw_books = sum(len(c["books"]) for c in clusters)
    print("\n" + "=" * 60)
    print("  ENRICHMENT COMPLETE — SUMMARY")
    print("=" * 60)
    print(f"  Raw books ingested (via ML): {total_raw_books}")
    print(f"  Unique clusters:             {len(clusters)}")
    print(f"  Currently-Reading clusters:  {cr_count}")
    print(f"  API quota used:              {len(to_fetch)}")
    print(f"  Skipped (raw fallback):      {len(remainder)}")
    print(f"  Final unique books:          {len(enriched)}")
    print(f"  Books with genre data:       {with_genre}")
    print(f"  Books read by 2+ clubs:      {multi_club}")
    print(f"  Total club interactions:     {total_clubs}")
    print("=" * 60)

    return enriched


# ─── CLI entry-point ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Enrich book clusters via Google Books API")
    parser.add_argument(
        "--quota", type=int, default=DAILY_API_QUOTA,
        help=f"Max API calls per run (default: {DAILY_API_QUOTA})",
    )
    args = parser.parse_args()

    asyncio.run(enrich_pipeline(quota=args.quota))


if __name__ == "__main__":
    main()
