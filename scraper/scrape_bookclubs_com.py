"""
Bookclubs.com Scraper (v3 — Typesense API)
============================================
Uses the Typesense search API that powers bookclubs.com to discover
ALL 2,000+ public book clubs and their currently-reading books.

This is dramatically faster than scraping HTML pages individually.

Usage:
    python scraper/scrape_bookclubs_com.py

Output:
    data/bookclubs_com.json

Stats are printed at the end showing:
  - Total clubs discovered
  - Clubs with an active book
  - Clubs with no current book
"""

import json
import time
from pathlib import Path

import requests

# ─── Configuration ───────────────────────────────────────────────────────────

TYPESENSE_URL = "https://6cry3ex9n0ua5w2qp-1.a1.typesense.net/multi_search"
TYPESENSE_API_KEY = "9FHS0caqtO8vlkcXtR17990pidQDiYgn"
PER_PAGE = 250  # Max out each request for speed
POLITENESS_DELAY = 0.3  # Light delay between API pages

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data"
OUTPUT_FILE = OUTPUT_DIR / "bookclubs_com.json"


# ─── Typesense API ──────────────────────────────────────────────────────────

def fetch_page(page: int) -> dict:
    """Fetch a single page of clubs from the Typesense API."""
    headers = {
        "Content-Type": "application/json",
        "X-TYPESENSE-API-KEY": TYPESENSE_API_KEY,
    }
    payload = {
        "searches": [
            {
                "query_by": "name,about_us,join_a_bookclub_card_description,location_description,tags",
                "query_by_weights": "4,2,2,1,1",
                "per_page": PER_PAGE,
                "collection": "production-jbcs",
                "q": "*",
                "page": page,
            }
        ]
    }

    resp = requests.post(
        TYPESENSE_URL,
        headers=headers,
        json=payload,
        params={"use_cache": "true"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def discover_all_clubs() -> list[dict]:
    """
    Paginate through the entire Typesense index to collect all clubs.
    Returns a list of raw Typesense 'document' objects.
    """
    print("\n" + "=" * 60)
    print("  Fetching all clubs via Typesense API")
    print("=" * 60)

    all_hits: list[dict] = []
    page = 1
    total_found = None

    while True:
        data = fetch_page(page)
        result = data["results"][0]

        if total_found is None:
            total_found = result["found"]
            print(f"  Total clubs in index: {total_found}")

        hits = result.get("hits", [])
        if not hits:
            break

        all_hits.extend(hits)
        print(f"  Page {page}: {len(hits)} clubs (collected: {len(all_hits)}/{total_found})")

        if len(all_hits) >= total_found:
            break

        page += 1
        time.sleep(POLITENESS_DELAY)

    print(f"\n  >> Collected {len(all_hits)} clubs total")
    return all_hits


# ─── Data Extraction ────────────────────────────────────────────────────────

def extract_books(hits: list[dict]) -> tuple[list[dict], dict]:
    """
    Extract currently-reading books from Typesense documents.
    Returns (books_list, stats_dict).
    """
    books = []
    active = 0
    inactive = 0

    for hit in hits:
        doc = hit.get("document", {})
        club_name = doc.get("name", "Unknown Club")
        slug = doc.get("slug", "")
        club_url = f"https://bookclubs.com/join-a-book-club/club/{slug}" if slug else ""
        member_count = doc.get("member_count", 0)

        # Extract currently reading books
        cr_books = doc.get("currently_reading_books", [])
        if cr_books and isinstance(cr_books, list):
            for book_data in cr_books:
                # book_data might be a string (title) or a dict
                if isinstance(book_data, dict):
                    title = book_data.get("title", "")
                    author = book_data.get("author", "")
                elif isinstance(book_data, str):
                    title = book_data
                    author = ""
                else:
                    continue

                if title:
                    books.append({
                        "title": title,
                        "author": author,
                        "category": "Currently Reading",
                        "month": time.strftime("%B %Y"),
                        "discussion_url": club_url,
                        "club_name": club_name,
                        "source_type": "Bookclubs.com",
                        "member_count": member_count,
                    })
            active += 1
        else:
            inactive += 1

    stats = {
        "total_clubs": len(hits),
        "clubs_with_active_book": active,
        "clubs_without_active_book": inactive,
        "total_books": len(books),
    }
    return books, stats


# ─── Output ──────────────────────────────────────────────────────────────────

def save_results(books: list[dict], stats: dict) -> None:
    """Save scraped data to JSON."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    data = {
        "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "bookclubs.com",
        **stats,
        "books": books,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\n  Saved to {OUTPUT_FILE}")


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  Bookclubs.com Scraper v3 (Typesense API)")
    print("=" * 60)

    # Fetch all clubs
    hits = discover_all_clubs()

    # Extract books
    books, stats = extract_books(hits)

    # Save
    save_results(books, stats)

    # Print summary
    print("\n" + "=" * 60)
    print("  SCRAPE COMPLETE — SUMMARY")
    print("=" * 60)
    print(f"  Total clubs discovered:      {stats['total_clubs']}")
    print(f"  Clubs with active book:      {stats['clubs_with_active_book']}")
    print(f"  Clubs with no current book:  {stats['clubs_without_active_book']}")
    print(f"  Total books extracted:       {stats['total_books']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
