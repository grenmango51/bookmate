"""
Tests for scraper/enrich_books.py
=================================
Covers:
  1. Priority scoring algorithm  (currently-reading first, then by popularity)
  2. Budget slicing              (only top-N clusters get API calls)
  3. Async API batch fetching    (mocked aiohttp, semaphore rate-limiting)
  4. Fallback / no-API path      (books beyond quota keep raw title/author)
  5. Final merge by Google Books ID
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# ── We import from the module under test ────────────────────────────────────
# The functions will be created/refactored in enrich_books.py
from scraper.enrich_books import (
    compute_priority_score,
    sort_clusters_by_priority,
    slice_budget,
    build_cluster_from_books,
    fetch_single,
    fetch_batch,
    enrich_pipeline,
    clean_for_search,
    normalize_key,
    DAILY_API_QUOTA,
)


# ═══════════════════════════════════════════════════════════════════════════════
#  Helpers: tiny book / cluster factories
# ═══════════════════════════════════════════════════════════════════════════════

def _book(title="Test Book", author="Test Author", category="Previously Read",
          source_type="Goodreads", member_count=0, club_name="Club A",
          discussion_url="https://example.com", month="January 2026"):
    return {
        "title": title,
        "author": author,
        "category": category,
        "month": month,
        "discussion_url": discussion_url,
        "club_name": club_name,
        "source_type": source_type,
        "member_count": member_count,
    }


def _cluster(books):
    """Wrap a list of raw book dicts into a cluster dict."""
    key = normalize_key(books[0]["title"], books[0]["author"])
    return build_cluster_from_books(key, books)


# ═══════════════════════════════════════════════════════════════════════════════
#  1. Priority Scoring
# ═══════════════════════════════════════════════════════════════════════════════

class TestPriorityScoring:

    def test_currently_reading_gets_highest_priority(self):
        """Any book marked 'Currently Reading' should rank above all others."""
        cr_cluster = _cluster([
            _book(title="Hot Book", category="Currently Reading", member_count=5),
        ])
        popular_cluster = _cluster([
            _book(title="Popular Book", category="Previously Read", member_count=50_000),
        ])
        score_cr = compute_priority_score(cr_cluster)
        score_pop = compute_priority_score(popular_cluster)
        assert score_cr > score_pop, (
            "Currently-Reading must beat any Previously-Read popularity"
        )

    def test_currently_reading_from_any_platform(self):
        """'Currently Reading' from Reddit, Goodreads, or Bookclubs all count."""
        for src in ("Reddit", "Goodreads", "Bookclubs.com"):
            cluster = _cluster([
                _book(category="Currently Reading", source_type=src, member_count=1),
            ])
            score = compute_priority_score(cluster)
            assert score >= 1_000_000, f"Currently-Reading from {src} must score high"

    def test_popularity_by_total_member_count(self):
        """Among non-CR books, higher total member_count → higher score."""
        big = _cluster([
            _book(title="Big", category="Previously Read", member_count=30_000),
        ])
        small = _cluster([
            _book(title="Small", category="Previously Read", member_count=100),
        ])
        assert compute_priority_score(big) > compute_priority_score(small)

    def test_popularity_by_club_appearances(self):
        """A book appearing in more clubs should rank higher (duplicate clubs)."""
        multi = _cluster([
            _book(title="Multi", category="Previously Read",
                  member_count=100, club_name="Club A"),
            _book(title="Multi", category="Previously Read",
                  member_count=200, club_name="Club B"),
            _book(title="Multi", category="Previously Read",
                  member_count=150, club_name="Club C"),
        ])
        single = _cluster([
            _book(title="Single", category="Previously Read",
                  member_count=400, club_name="Only Club"),
        ])
        # multi total = 450 members + 3 clubs bonus
        # single total = 400 members + 1 club bonus
        assert compute_priority_score(multi) > compute_priority_score(single)

    def test_mixed_cluster_with_one_cr_still_high(self):
        """If even ONE book in the cluster is 'Currently Reading', score is top-tier."""
        mixed = _cluster([
            _book(title="Book X", category="Currently Reading", member_count=10),
            _book(title="Book X", category="Previously Read", member_count=5_000),
        ])
        pure_popular = _cluster([
            _book(title="Mega Popular", category="Previously Read", member_count=50_000),
        ])
        assert compute_priority_score(mixed) > compute_priority_score(pure_popular)

    def test_reddit_currently_reading_detected(self):
        """Reddit books from the current/previous month should be treated as CR."""
        # Reddit uses month-based categories like "BIPOC Author", not "Currently Reading".
        # But if the month is current/recent AND category != "Previously Read",
        # the reddit scraper now sets category="Currently Reading" for Feb 2026 books.
        reddit_cr = _cluster([
            _book(title="Reddit Book", category="Currently Reading",
                  source_type="Reddit", member_count=0,
                  month="February 2026"),
        ])
        score = compute_priority_score(reddit_cr)
        assert score >= 1_000_000


# ═══════════════════════════════════════════════════════════════════════════════
#  2. Sort & Budget Slicing
# ═══════════════════════════════════════════════════════════════════════════════

class TestSortAndBudget:

    def test_sort_clusters_by_priority_descending(self):
        clusters = [
            _cluster([_book(title="Low", category="Previously Read", member_count=10)]),
            _cluster([_book(title="CR", category="Currently Reading", member_count=5)]),
            _cluster([_book(title="Mid", category="Previously Read", member_count=5_000)]),
        ]
        sorted_c = sort_clusters_by_priority(clusters)
        titles = [c["representative_title"] for c in sorted_c]
        assert titles[0] == "CR", "Currently-Reading must be first"
        assert titles[1] == "Mid", "High popularity second"
        assert titles[2] == "Low", "Low popularity last"

    def test_slice_budget_respects_quota(self):
        """Only top `quota` clusters should be in the 'to_fetch' list."""
        clusters = [
            _cluster([_book(title=f"Book {i}", category="Previously Read",
                            member_count=1000 - i)])
            for i in range(20)
        ]
        to_fetch, remainder = slice_budget(clusters, quota=5)
        assert len(to_fetch) == 5
        assert len(remainder) == 15

    def test_slice_budget_all_fit(self):
        """If fewer clusters than quota, all go to fetch, none to remainder."""
        clusters = [
            _cluster([_book(title="A")]),
            _cluster([_book(title="B")]),
        ]
        to_fetch, remainder = slice_budget(clusters, quota=1000)
        assert len(to_fetch) == 2
        assert len(remainder) == 0

    def test_slice_budget_preserves_order(self):
        """The budget slicer should keep the priority order intact."""
        clusters = sort_clusters_by_priority([
            _cluster([_book(title="Low", member_count=1)]),
            _cluster([_book(title="High", member_count=9999)]),
            _cluster([_book(title="CR", category="Currently Reading")]),
        ])
        to_fetch, remainder = slice_budget(clusters, quota=2)
        titles = [c["representative_title"] for c in to_fetch]
        assert titles == ["CR", "High"]
        remainder_titles = [c["representative_title"] for c in remainder]
        assert remainder_titles == ["Low"]


# ═══════════════════════════════════════════════════════════════════════════════
#  3. Async Batch Fetching (mocked network)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAsyncBatchFetching:

    @pytest.fixture
    def mock_api_response(self):
        """A factory that produces fake Google Books API JSON responses."""
        def _make(title="Canonical Title", author="Canonical Author", gid="gid_001"):
            return {
                "totalItems": 1,
                "items": [{
                    "id": gid,
                    "volumeInfo": {
                        "title": title,
                        "authors": [author],
                        "categories": ["Fiction"],
                        "pageCount": 320,
                        "publishedDate": "2020-01-01",
                        "imageLinks": {"thumbnail": "https://img.example.com/thumb.jpg"},
                        "description": "A great book about testing.",
                    },
                }],
            }
        return _make

    @pytest.mark.asyncio
    async def test_fetch_single_success(self, mock_api_response):
        """fetch_single should parse a valid API response correctly."""
        fake_resp = AsyncMock()
        fake_resp.status = 200
        fake_resp.json = AsyncMock(return_value=mock_api_response(
            title="1984", author="George Orwell", gid="abc123"
        ))
        fake_resp.__aenter__ = AsyncMock(return_value=fake_resp)
        fake_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=fake_resp)

        sem = asyncio.Semaphore(5)
        result = await fetch_single(mock_session, "1984 George Orwell", "test_key", sem, cache={})

        assert result is not None
        assert result["canonical_title"] == "1984"
        assert result["canonical_author"] == "George Orwell"
        assert result["google_books_id"] == "abc123"

    @pytest.mark.asyncio
    async def test_fetch_single_uses_cache(self, mock_api_response):
        """If the key is already in cache, no HTTP request should be made."""
        cached_data = {
            "google_books_id": "cached_id",
            "canonical_title": "Cached Title",
            "canonical_author": "Cached Author",
            "categories": [],
            "page_count": 100,
            "published_date": "",
            "thumbnail": "",
            "description": "",
        }
        mock_session = AsyncMock()
        sem = asyncio.Semaphore(5)

        result = await fetch_single(
            mock_session, "anything", "cached_key", sem,
            cache={"cached_key": cached_data}
        )

        assert result == cached_data
        mock_session.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_single_api_error_returns_none(self):
        """On API error (non-200), fetch_single should return None."""
        fake_resp = AsyncMock()
        fake_resp.status = 500
        fake_resp.__aenter__ = AsyncMock(return_value=fake_resp)
        fake_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=fake_resp)

        sem = asyncio.Semaphore(5)
        result = await fetch_single(mock_session, "query", "key", sem, cache={})

        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_batch_concurrency(self, mock_api_response):
        """fetch_batch should process all clusters and respect concurrency."""
        clusters = [
            _cluster([_book(title=f"Book {i}", author=f"Author {i}")])
            for i in range(10)
        ]

        async def mock_fetch(session, query, key, sem, cache):
            return {
                "google_books_id": f"gid_{key[:8]}",
                "canonical_title": query.split()[0],
                "canonical_author": "Author",
                "categories": ["Fiction"],
                "page_count": 200,
                "published_date": "2021",
                "thumbnail": "",
                "description": "",
            }

        with patch("scraper.enrich_books.fetch_single", side_effect=mock_fetch):
            results = await fetch_batch(clusters, cache={}, max_concurrent=3)

        assert len(results) == 10
        for r in results:
            assert "google_books_id" in r["api_result"]

    @pytest.mark.asyncio
    async def test_fetch_batch_populates_cache(self, mock_api_response):
        """After a batch fetch, cache should contain the looked-up keys."""
        clusters = [
            _cluster([_book(title="CacheMe", author="Author")]),
        ]
        cache = {}

        async def mock_fetch(session, query, key, sem, cache):
            result = {
                "google_books_id": "gid_cache",
                "canonical_title": "CacheMe",
                "canonical_author": "Author",
                "categories": [],
                "page_count": 100,
                "published_date": "",
                "thumbnail": "",
                "description": "",
            }
            cache[key] = result
            return result

        with patch("scraper.enrich_books.fetch_single", side_effect=mock_fetch):
            await fetch_batch(clusters, cache=cache, max_concurrent=5)

        assert len(cache) > 0


# ═══════════════════════════════════════════════════════════════════════════════
#  4. Full Pipeline: Remainder books get raw fallback
# ═══════════════════════════════════════════════════════════════════════════════

class TestFullPipeline:

    def test_remainder_books_have_raw_title_author(self):
        """Books beyond the API quota must still appear with raw title/author."""
        # Create more clusters than the quota
        all_clusters = [
            _cluster([_book(title=f"Book {i}", author=f"Author {i}",
                            category="Previously Read", member_count=100 - i)])
            for i in range(15)
        ]

        sorted_c = sort_clusters_by_priority(all_clusters)
        to_fetch, remainder = slice_budget(sorted_c, quota=5)

        assert len(remainder) == 10

        # Each remainder cluster should have the raw title/author
        for c in remainder:
            assert c["representative_title"] != ""
            assert c["representative_author"] is not None

    def test_currently_reading_always_within_budget(self):
        """Even with a tiny quota, all CR books should fit in to_fetch."""
        cr_books = [
            _cluster([_book(title=f"CR Book {i}", category="Currently Reading")])
            for i in range(3)
        ]
        other_books = [
            _cluster([_book(title=f"Other {i}", category="Previously Read",
                            member_count=99999)])
            for i in range(100)
        ]
        all_clusters = sort_clusters_by_priority(cr_books + other_books)
        to_fetch, _ = slice_budget(all_clusters, quota=10)

        cr_in_fetch = [c for c in to_fetch if c["is_currently_reading"]]
        assert len(cr_in_fetch) == 3, "All 3 CR books must be in the fetch list"


# ═══════════════════════════════════════════════════════════════════════════════
#  5. Edge Cases & Utilities
# ═══════════════════════════════════════════════════════════════════════════════

class TestUtilities:

    def test_clean_for_search_removes_brackets(self):
        assert "1984" in clean_for_search("[1984]", "")

    def test_clean_for_search_extracts_embedded_author(self):
        q = clean_for_search("1984 by George Orwell", "")
        assert "1984" in q
        assert "George Orwell" in q

    def test_normalize_key_is_stable(self):
        k1 = normalize_key("The Great Gatsby", "F. Scott Fitzgerald")
        k2 = normalize_key("  The  Great  Gatsby  ", "F. Scott Fitzgerald")
        assert k1 == k2

    def test_cluster_build_aggregates_member_count(self):
        cluster = _cluster([
            _book(member_count=100, club_name="A"),
            _book(member_count=200, club_name="B"),
        ])
        assert cluster["total_member_count"] == 300
        assert cluster["num_clubs"] == 2
