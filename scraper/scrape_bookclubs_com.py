"""
Bookclubs.com Scraper
=====================
Scrapes public book club pages on bookclubs.com to extract:
  - Club name
  - Currently reading book (title + author)

Usage:
    python scraper/scrape_bookclubs_com.py

Output:
    data/bookclubs_com.json
"""

import json
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ─── Configuration ───────────────────────────────────────────────────────────

BASE_URL = "https://bookclubs.com"
USER_AGENT = "BookmateScraper/1.0 (educational project)"
REQUEST_TIMEOUT = 30

# Add club slugs here to scrape more clubs
CLUB_SLUGS = [
    "shelf-scout",
]

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data"
OUTPUT_FILE = OUTPUT_DIR / "bookclubs_com.json"


# ─── Helpers ─────────────────────────────────────────────────────────────────

def fetch_page(url: str) -> str:
    """Fetch an HTML page."""
    headers = {"User-Agent": USER_AGENT}
    print(f"  [*] Fetching {url}")
    resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.text


def scrape_club(slug: str) -> dict | None:
    """
    Scrape a single club page to extract the club name
    and currently reading book.
    """
    club_url = f"{BASE_URL}/join-a-book-club/club/{slug}"

    try:
        html = fetch_page(club_url)
    except requests.RequestException as e:
        print(f"  [!] Failed to fetch club '{slug}': {e}")
        return None

    soup = BeautifulSoup(html, "html.parser")

    # ── Club Name ─────────────────────────────────
    h1 = soup.find("h1")
    club_name = h1.text.strip() if h1 else slug.replace("-", " ").title()

    # ── Currently Reading ─────────────────────────
    cr_div = soup.find("div", class_="current-reading")
    if not cr_div:
        print(f"  [!] No 'currently reading' section found for {club_name}")
        return {
            "club_name": club_name,
            "club_url": club_url,
            "source_type": "Bookclubs.com",
            "currently_reading": None,
        }

    book_link = cr_div.find("a")
    if not book_link or not book_link.get("href"):
        print(f"  [!] No book link found in currently reading for {club_name}")
        return {
            "club_name": club_name,
            "club_url": club_url,
            "source_type": "Bookclubs.com",
            "currently_reading": None,
        }

    book_path = book_link["href"]  # e.g. /books/the-generals-wife-1057442
    book_url = f"{BASE_URL}{book_path}"

    # ── Fetch the book page for exact title + author ──
    book_title, book_author = _fetch_book_details(book_url, book_path)

    return {
        "club_name": club_name,
        "club_url": club_url,
        "source_type": "Bookclubs.com",
        "currently_reading": {
            "title": book_title,
            "author": book_author,
            "book_url": book_url,
        },
    }


def _fetch_book_details(book_url: str, book_path: str) -> tuple[str, str]:
    """
    Fetch the book's own page on bookclubs.com to get the exact title and author.
    Falls back to parsing the URL slug if the page fetch fails.
    """
    # Fallback: parse from slug
    slug = book_path.split("/")[-1]
    slug_clean = re.sub(r"-\d+$", "", slug)
    fallback_title = slug_clean.replace("-", " ").title()

    try:
        html = fetch_page(book_url)
    except requests.RequestException:
        return fallback_title, ""

    soup = BeautifulSoup(html, "html.parser")

    # Title from <h1>
    h1 = soup.find("h1")
    title = h1.text.strip() if h1 else fallback_title

    # Author from <p> "By Author Name" or <span> inside author container
    author = ""
    by_p = soup.find("p", string=re.compile(r"^By\s+", re.IGNORECASE))
    if by_p:
        author = re.sub(r"^By\s+", "", by_p.text.strip(), flags=re.IGNORECASE)
    else:
        # Try <span> or <a> near the title
        for el in soup.find_all(["span", "a"]):
            parent_text = el.parent.text if el.parent else ""
            if "By " in parent_text and el.text.strip() and el.text.strip() != title:
                candidate = el.text.strip()
                if len(candidate) > 2 and len(candidate) < 60:
                    author = candidate
                    break

    return title, author


# ─── Output ──────────────────────────────────────────────────────────────────

def save_results(clubs: list[dict]) -> None:
    """Save scraped club data to JSON."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Build a flat list of books for the unified data format
    books = []
    for club in clubs:
        if club.get("currently_reading"):
            cr = club["currently_reading"]
            books.append({
                "title": cr["title"],
                "author": cr["author"],
                "category": "Currently Reading",
                "month": time.strftime("%B %Y"),
                "discussion_url": club["club_url"],
                "club_name": club["club_name"],
                "source_type": club["source_type"],
            })

    data = {
        "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "bookclubs.com",
        "total_clubs": len(clubs),
        "total_books": len(books),
        "clubs": clubs,
        "books": books,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\n[+] Saved {len(books)} books from {len(clubs)} clubs to {OUTPUT_FILE}")


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    print("=" * 50)
    print("  Bookclubs.com Scraper")
    print("=" * 50)

    clubs = []
    for slug in CLUB_SLUGS:
        print(f"\n[*] Scraping club: {slug}")
        result = scrape_club(slug)
        if result:
            clubs.append(result)
            cr = result.get("currently_reading")
            if cr:
                print(f"  [+] {result['club_name']} → \"{cr['title']}\" by {cr['author']}")
            else:
                print(f"  [+] {result['club_name']} → No current book")
        time.sleep(1)  # Be polite between requests

    save_results(clubs)

    print(f"\n{'=' * 50}")
    print(f"  Scrape Complete!")
    print(f"  Clubs scraped: {len(clubs)}")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
