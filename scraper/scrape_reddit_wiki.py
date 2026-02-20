"""
Reddit r/bookclub Wiki Scraper
================================
Fetches the "Previous Selections" wiki page from r/bookclub and extracts
every book title, author, and discussion link into a structured JSON file.

Usage:
    python scraper/scrape_reddit_wiki.py

Output:
    data/reddit_books.json
"""

import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ─── Configuration ───────────────────────────────────────────────────────────
WIKI_URL = "https://www.reddit.com/r/bookclub/wiki/previous/"
USER_AGENT = "BookmateScraper/1.0 (educational project)"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data"
OUTPUT_FILE = OUTPUT_DIR / "reddit_books.json"
REQUEST_TIMEOUT = 30

# ─── Helpers ─────────────────────────────────────────────────────────────────

def fetch_wiki_html(url: str) -> str:
    """Fetch the wiki page HTML from Reddit."""
    headers = {"User-Agent": USER_AGENT}
    print(f"[*] Fetching {url} ...")
    resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    print(f"[+] Received {len(resp.text):,} bytes")
    return resp.text


def parse_books(html: str) -> list[dict]:
    """
    Parse the wiki HTML and extract book entries.

    The wiki is structured as:
        <h1>Month Year</h1>
        Category: <a href="schedule_link">Book Title</a> by Author
        Category: <a href="schedule_link">Book Title</a> by Author
        ...

    We extract: title, author, discussion_url, month, category
    """
    soup = BeautifulSoup(html, "lxml")

    # Find the wiki content area
    wiki_body = soup.find("div", class_="md wiki")
    if not wiki_body:
        # Fallback: try to find any content area
        wiki_body = soup.find("div", {"data-testid": "wiki-content"})
    if not wiki_body:
        # Last resort: use the whole body
        wiki_body = soup.body or soup

    books = []
    current_month = "Unknown"

    # Walk through all elements in document order
    for element in wiki_body.descendants:
        # Check for month headers (h1, h2, h3 tags)
        if element.name in ("h1", "h2", "h3"):
            header_text = element.get_text(strip=True)
            # Skip non-month headers like "Previous Selections" or "r/bookclub"
            if header_text.lower() in ("previous selections", "r/bookclub"):
                continue
            current_month = header_text

        # Check for lines with links (book entries)
        if element.name == "p" or (element.name is None and element.parent and element.parent.name == "p"):
            continue  # We handle <p> tags at the parent level

    # Alternative: parse line by line from the text content + links
    # This is more robust for Reddit's wiki format
    books = _parse_wiki_lines(wiki_body)

    return books


def _parse_wiki_lines(wiki_body) -> list[dict]:
    """
    Parse wiki content by iterating through paragraphs and extracting links.
    Each book entry typically looks like:
        Category: [Book Title](url) by Author Name
    """
    books = []
    current_month = "Unknown"
    seen_urls = set()

    # Iterate through all direct children and text nodes
    for element in wiki_body.find_all(["h1", "h2", "h3", "p", "br"]):
        if element.name in ("h1", "h2", "h3"):
            header_text = element.get_text(strip=True)
            if header_text.lower() in ("previous selections", "r/bookclub", ""):
                continue
            current_month = header_text
            continue

        if element.name == "p":
            # Each <p> can contain multiple lines separated by <br>
            # Get all text chunks and links
            lines = _split_element_by_br(element)
            for line_parts in lines:
                entry = _parse_book_line(line_parts, current_month)
                if entry and entry["discussion_url"] not in seen_urls:
                    seen_urls.add(entry["discussion_url"])
                    books.append(entry)

    return books


def _split_element_by_br(element) -> list[list]:
    """Split a <p> element's children by <br> tags into separate logical lines."""
    lines = []
    current_line = []

    for child in element.children:
        if child.name == "br":
            if current_line:
                lines.append(current_line)
            current_line = []
        else:
            current_line.append(child)

    if current_line:
        lines.append(current_line)

    # If the element has no <br> tags, treat the whole thing as one line
    if not lines:
        lines = [list(element.children)]

    return lines


def _parse_book_line(parts: list, month: str) -> dict | None:
    """
    Parse a single line of the wiki to extract book information.
    Expected format: "Category: [Book Title](url) by Author"
    """
    # Reconstruct the text of this line
    full_text = ""
    link_url = None
    link_text = None

    for part in parts:
        if hasattr(part, "name") and part.name == "a":
            link_url = part.get("href", "")
            link_text = part.get_text(strip=True)
            full_text += link_text
        elif hasattr(part, "get_text"):
            full_text += part.get_text()
        else:
            full_text += str(part)

    full_text = full_text.strip()

    # Skip empty lines or lines without links
    if not link_url or not link_text:
        return None

    # Skip non-Reddit links (e.g., Amazon, Goodreads)
    if "reddit.com" not in link_url and not link_url.startswith("/r/"):
        return None

    # Normalize the URL
    if link_url.startswith("/r/"):
        link_url = f"https://www.reddit.com{link_url}"

    # Extract category (text before the colon)
    category = ""
    colon_match = re.match(r"^([^:]+):\s*", full_text)
    if colon_match:
        category = colon_match.group(1).strip()

    # Extract author (text after "by")
    author = ""
    by_match = re.search(r"\bby\s+(.+)$", full_text, re.IGNORECASE)
    if by_match:
        author = by_match.group(1).strip()
        # Clean trailing text like "(schedule will be linked later)"
        author = re.sub(r"\s*\(.*?\)\s*$", "", author).strip()

    return {
        "title": link_text,
        "author": author,
        "category": category,
        "month": month,
        "discussion_url": link_url,
    }


def save_to_json(books: list[dict], output_path: Path) -> None:
    """Save extracted books to a JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "source": WIKI_URL,
                "total_books": len(books),
                "books": books,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )

    print(f"[+] Saved {len(books)} books to {output_path}")


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    try:
        html = fetch_wiki_html(WIKI_URL)
        books = parse_books(html)

        if not books:
            print("[!] Warning: No books were extracted. The wiki format may have changed.")
            print("[!] Trying alternate parsing...")
            # Fallback: use regex on raw HTML
            books = _regex_fallback(html)

        save_to_json(books, OUTPUT_FILE)

        # Print summary
        print(f"\n{'='*60}")
        print(f"  Scrape Complete!")
        print(f"  Total books found: {len(books)}")
        if books:
            print(f"  Date range: {books[-1]['month']} → {books[0]['month']}")
            print(f"  Sample: \"{books[0]['title']}\" by {books[0]['author']}")
        print(f"{'='*60}")

    except requests.RequestException as e:
        print(f"[!] Network error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[!] Unexpected error: {e}", file=sys.stderr)
        raise


def _regex_fallback(html: str) -> list[dict]:
    """
    Last-resort parser: use regex to find all Reddit discussion links
    in the wiki HTML along with their surrounding text.
    """
    print("[*] Using regex fallback parser...")
    books = []
    seen = set()

    # Pattern: [text](reddit_url)  — markdown-style links
    md_pattern = re.compile(
        r'\[([^\]]+)\]\((https?://(?:www\.)?reddit\.com/r/bookclub/comments/[^\)]+)\)'
    )

    # Pattern: <a href="reddit_url">text</a>  — HTML links
    html_pattern = re.compile(
        r'<a[^>]+href="(https?://(?:www\.)?reddit\.com/r/bookclub/comments/[^"]+)"[^>]*>([^<]+)</a>'
    )

    for match in md_pattern.finditer(html):
        title, url = match.group(1), match.group(2)
        if url not in seen:
            seen.add(url)
            books.append({
                "title": title.strip(),
                "author": "",
                "category": "",
                "month": "",
                "discussion_url": url,
            })

    for match in html_pattern.finditer(html):
        url, title = match.group(1), match.group(2)
        if url not in seen:
            seen.add(url)
            books.append({
                "title": title.strip(),
                "author": "",
                "category": "",
                "month": "",
                "discussion_url": url,
            })

    return books


if __name__ == "__main__":
    main()
