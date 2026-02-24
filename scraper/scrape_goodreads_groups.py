"""
Goodreads Groups Scraper
========================
Scrapes the top 100 popular Goodreads groups and their bookshelves
to discover what books each club has read or is currently reading.

Strategy:
  1. Discovery:  Paginate /group/popular?page=1..5  (20 per page = 100 groups)
  2. Deep scrape: For each group, fetch its bookshelf pages:
       - "read"              → full archive of past reads
       - "currently-reading" → what they're reading now
  3. Save everything to data/goodreads_groups.json

Features:
  - Polite delays between requests (configurable)
  - Checkpoint file so the scraper can resume after interruption
  - Progress logging

Usage:
    python scraper/scrape_goodreads_groups.py

Output:
    data/goodreads_groups.json
"""

import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

# ─── Configuration ───────────────────────────────────────────────────────────

BASE_URL = "https://www.goodreads.com"
POPULAR_PAGES = 5          # 5 pages × 20 groups = 100 groups
BOOKS_PER_PAGE = 30        # Goodreads default
POLITENESS_DELAY = 1.5     # seconds between requests (be nice)
REQUEST_TIMEOUT = 30       # seconds

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data"
OUTPUT_FILE = OUTPUT_DIR / "goodreads_groups.json"
CHECKPOINT_FILE = OUTPUT_DIR / ".goodreads_checkpoint.json"

# Mimic a real browser to avoid blocks
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Configure robust session with retries for transient DNS/connection errors
session = requests.Session()
retries = Retry(total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retries)
session.mount('http://', adapter)
session.mount('https://', adapter)
session.headers.update(HEADERS)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def polite_get(url: str) -> requests.Response:
    """GET with polite delay, error handling, and robust retries."""
    for attempt in range(3):
        try:
            time.sleep(POLITENESS_DELAY)
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            if attempt == 2:
                raise
            print(f"      [!] Connection error ({e}), retrying {attempt+1}/3...")
            time.sleep(5)


def extract_group_id(url: str) -> str:
    """Extract the group ID slug from a Goodreads group URL.
    e.g. /group/show/1865-scifi-and-fantasy-book-club → 1865-scifi-and-fantasy-book-club
    """
    match = re.search(r"/group/show/(.+?)(?:\?|$)", url)
    return match.group(1) if match else ""


def parse_member_count(text: str) -> int:
    """Extract member count from text like '42,088 members'."""
    match = re.search(r"([\d,]+)\s*members?", text, re.IGNORECASE)
    if match:
        return int(match.group(1).replace(",", ""))
    return 0


# ─── Checkpoint ──────────────────────────────────────────────────────────────

def load_checkpoint() -> dict:
    """Load checkpoint data if it exists."""
    if CHECKPOINT_FILE.exists():
        with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"completed_groups": [], "books": []}


def save_checkpoint(data: dict) -> None:
    """Save checkpoint for resume capability."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def clear_checkpoint() -> None:
    """Remove checkpoint file after successful completion."""
    if CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()


# ─── Phase 1: Discover Groups ───────────────────────────────────────────────

def discover_popular_groups() -> list[dict]:
    """
    Scrape /group/popular?page=1..5 to collect the top 100 groups.
    Returns list of dicts with: name, url, group_id, member_count, category
    """
    print("\n" + "=" * 60)
    print("  Phase 1: Discovering Popular Groups")
    print("=" * 60)

    groups = []

    for page in range(1, POPULAR_PAGES + 1):
        url = f"{BASE_URL}/group/popular?page={page}"
        print(f"  Fetching page {page}/{POPULAR_PAGES} ... ", end="", flush=True)

        try:
            resp = polite_get(url)
        except requests.RequestException as e:
            print(f"FAILED ({e})")
            continue

        soup = BeautifulSoup(resp.text, "html.parser")

        # Each group entry has an anchor with class "groupName"
        group_links = soup.select("a.groupName")

        page_count = 0
        for link in group_links:
            name = link.get_text(strip=True)
            href = link.get("href", "")
            full_url = urljoin(BASE_URL, href) if href else ""
            group_id = extract_group_id(full_url)

            # Member count: look in the parent container
            parent = link.find_parent()
            member_text = parent.get_text() if parent else ""
            member_count = parse_member_count(member_text)

            # If we couldn't get it from the direct parent, search siblings
            if member_count == 0:
                # Walk up to find the group block and search for member count
                block = link.find_parent("div") or link.find_parent("tr")
                if block:
                    member_count = parse_member_count(block.get_text())

            if name and group_id:
                groups.append({
                    "name": name,
                    "url": full_url,
                    "group_id": group_id,
                    "member_count": member_count,
                })
                page_count += 1

        print(f"found {page_count} groups")

    # Deduplicate by group_id (some groups might appear on multiple pages)
    seen = set()
    unique_groups = []
    for g in groups:
        if g["group_id"] not in seen:
            seen.add(g["group_id"])
            unique_groups.append(g)

    print(f"\n  >> Discovered {len(unique_groups)} unique groups")
    return unique_groups


# ─── Phase 2: Scrape Group Bookshelves ───────────────────────────────────────

def scrape_bookshelf(group_id: str, shelf: str = "read") -> list[dict]:
    """
    Scrape ALL pages of a group's bookshelf.
    Returns list of dicts with: title, author, book_url, shelf

    Goodreads bookshelf HTML structure (verified via browser inspection):
      - Table: <table id="groupBooks" class="tableList">
      - Rows:  <tr id="groupBook{id}">
      - Title: td:nth-child(2) a[href*="/book/show/"]
      - Author: td:nth-child(3) a[href*="/author/show/"]  (name in "Last, First" format)
      - Pagination: a.next_page
    """
    books = []
    page = 1

    while True:
        url = (
            f"{BASE_URL}/group/bookshelf/{group_id}"
            f"?shelf={shelf}&per_page={BOOKS_PER_PAGE}&page={page}&view=main"
        )

        try:
            resp = polite_get(url)
        except requests.RequestException as e:
            print(f"      [!] Bookshelf page {page} failed: {e}")
            break

        soup = BeautifulSoup(resp.text, "html.parser")

        # Primary selector: rows with id starting with "groupBook"
        rows = soup.select("tr[id^='groupBook']")

        # Fallback: try table.tableList rows (skip header)
        if not rows:
            table = soup.select_one("table#groupBooks") or soup.select_one("table.tableList")
            if table:
                all_rows = table.select("tr")
                # Skip header row (the first row without a groupBook id)
                rows = [r for r in all_rows if r.get("id", "").startswith("groupBook")]
                if not rows:
                    # Last resort: skip first row (header) and take the rest
                    rows = all_rows[1:] if len(all_rows) > 1 else []

        if not rows:
            break  # No books found, stop paginating

        for row in rows:
            tds = row.select("td")

            # Title: look for link to /book/show/ in the 2nd td, or anywhere
            title = ""
            book_url = ""
            title_link = None

            if len(tds) >= 2:
                title_link = tds[1].select_one("a[href*='/book/show/']")
            if not title_link:
                title_link = row.select_one("a[href*='/book/show/']")

            if title_link:
                title = title_link.get_text(strip=True)
                book_url = urljoin(BASE_URL, title_link.get("href", ""))

            if not title:
                continue

            # Author: look for link to /author/show/ in the 3rd td, or anywhere
            author = ""
            author_link = None

            if len(tds) >= 3:
                author_link = tds[2].select_one("a[href*='/author/show/']")
            if not author_link:
                author_link = row.select_one("a[href*='/author/show/']")

            if author_link:
                author_name = author_link.get_text(strip=True)
                # Goodreads shows "Last, First" — flip to "First Last"
                if "," in author_name:
                    parts = author_name.split(",", 1)
                    author = f"{parts[1].strip()} {parts[0].strip()}"
                else:
                    author = author_name

            books.append({
                "title": title,
                "author": author,
                "book_url": book_url,
                "shelf": shelf,
            })

        # Check for next page
        next_link = soup.select_one("a.next_page")
        if not next_link:
            break

        page += 1

    return books


def scrape_group_books(group: dict, checkpoint: dict) -> list[dict]:
    """
    Scrape both 'read' and 'currently-reading' shelves for a group.
    Returns list of book dicts ready for output.
    """
    group_id = group["group_id"]
    group_name = group["name"]
    group_url = group["url"]
    member_count = group["member_count"]

    all_books = []

    for shelf in ["currently-reading", "read"]:
        shelf_label = "Currently Reading" if shelf == "currently-reading" else "Previously Read"
        print(f"    Shelf: {shelf_label} ... ", end="", flush=True)

        raw_books = scrape_bookshelf(group_id, shelf)
        print(f"{len(raw_books)} books")

        for book in raw_books:
            all_books.append({
                "title": book["title"],
                "author": book["author"],
                "category": shelf_label,
                "discussion_url": group_url,
                "book_url": book.get("book_url", ""),
                "club_name": group_name,
                "source_type": "Goodreads",
                "member_count": member_count,
            })

    return all_books


# ─── Output ──────────────────────────────────────────────────────────────────

def save_results(books: list[dict], groups: list[dict]) -> None:
    """Save scraped data to JSON."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Compute stats
    clubs_with_books = len(set(b["club_name"] for b in books))
    currently_reading = sum(1 for b in books if b["category"] == "Currently Reading")
    previously_read = sum(1 for b in books if b["category"] == "Previously Read")

    data = {
        "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "goodreads_groups",
        "total_groups_scraped": len(groups),
        "groups_with_books": clubs_with_books,
        "total_books": len(books),
        "currently_reading": currently_reading,
        "previously_read": previously_read,
        "books": books,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\n  Saved to {OUTPUT_FILE}")


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  Goodreads Groups Scraper")
    print("  Target: Top 100 Popular Groups")
    print("=" * 60)

    # Load checkpoint
    checkpoint = load_checkpoint()
    completed = set(checkpoint.get("completed_groups", []))
    existing_books = checkpoint.get("books", [])

    if completed:
        print(f"\n  Resuming from checkpoint: {len(completed)} groups already done")
        print(f"  Books collected so far: {len(existing_books)}")

    # Phase 1: Discover groups
    groups = discover_popular_groups()

    if not groups:
        print("\n  [!] No groups discovered. Exiting.")
        return

    # Phase 2: Deep scrape each group's bookshelf
    print("\n" + "=" * 60)
    print("  Phase 2: Scraping Group Bookshelves")
    print("=" * 60)

    all_books = list(existing_books)  # Start with checkpoint data
    remaining = [g for g in groups if g["group_id"] not in completed]
    total = len(groups)
    done = len(completed)

    for i, group in enumerate(remaining, start=done + 1):
        print(f"\n  [{i}/{total}] {group['name']}")
        print(f"    Members: {group['member_count']:,}")

        try:
            books = scrape_group_books(group, checkpoint)
            all_books.extend(books)

            # Update checkpoint
            completed.add(group["group_id"])
            save_checkpoint({
                "completed_groups": list(completed),
                "books": all_books,
            })

        except KeyboardInterrupt:
            print("\n\n  [!] Interrupted! Progress saved to checkpoint.")
            save_checkpoint({
                "completed_groups": list(completed),
                "books": all_books,
            })
            return

        except Exception as e:
            print(f"    [!] Error scraping group: {e}")
            # Save checkpoint and continue with next group
            save_checkpoint({
                "completed_groups": list(completed),
                "books": all_books,
            })
            continue

    # Save final results
    save_results(all_books, groups)

    # Clear checkpoint on successful completion
    clear_checkpoint()

    # Print summary
    currently_reading = sum(1 for b in all_books if b["category"] == "Currently Reading")
    previously_read = sum(1 for b in all_books if b["category"] == "Previously Read")
    unique_titles = len(set(b["title"].lower() for b in all_books))

    print("\n" + "=" * 60)
    print("  SCRAPE COMPLETE — SUMMARY")
    print("=" * 60)
    print(f"  Groups scraped:              {len(groups)}")
    print(f"  Total books extracted:       {len(all_books)}")
    print(f"  Unique titles (approx):      {unique_titles}")
    print(f"  Currently reading:           {currently_reading}")
    print(f"  Previously read:             {previously_read}")
    print("=" * 60)


if __name__ == "__main__":
    main()
