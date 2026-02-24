"""
Tests for the ML Deduplication Script
======================================
TDD approach: We write these tests FIRST to define the expected behaviour
of the deduplication pipeline before implementing it.

Tests cover:
  1. Text normalization (cleaning messy book titles)
  2. Clustering logic (grouping duplicates, separating unrelated books)
  3. Priority tagging (Currently Reading vs Previously Read)
  4. Edge cases (empty strings, missing authors, unicode)

Run with:
    python -m pytest tests/test_ml_deduplicate.py -v
"""

import sys
from pathlib import Path

# Ensure the scraper package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest


# ─── Test 1: Text Normalization ─────────────────────────────────────────────

class TestNormalizeBookString:
    """Test the function that cleans a title+author into a comparable string."""

    def test_basic_cleaning(self):
        from scraper.ml_deduplicate import normalize_book_string
        result = normalize_book_string("  Dune  ", "  Frank Herbert  ")
        assert result == "dune frank herbert"

    def test_removes_series_info_in_parens(self):
        from scraper.ml_deduplicate import normalize_book_string
        result = normalize_book_string("Jaws (Jaws, #1)", "Peter Benchley")
        assert "jaws" in result
        assert "#1" not in result

    def test_removes_brackets(self):
        from scraper.ml_deduplicate import normalize_book_string
        result = normalize_book_string("[ A Thousand Splendid Suns ]", "Khaled Hosseini")
        assert result.startswith("a thousand")
        assert "[" not in result and "]" not in result

    def test_handles_empty_author(self):
        from scraper.ml_deduplicate import normalize_book_string
        result = normalize_book_string("Dune", "")
        assert result == "dune"

    def test_handles_empty_title(self):
        from scraper.ml_deduplicate import normalize_book_string
        result = normalize_book_string("", "Frank Herbert")
        assert result == "frank herbert"

    def test_unicode_characters(self):
        from scraper.ml_deduplicate import normalize_book_string
        result = normalize_book_string("Vampires of El Norte", "Isabel Cañas")
        assert "vampires" in result
        assert "isabel" in result

    def test_subtitle_after_colon(self):
        from scraper.ml_deduplicate import normalize_book_string
        result = normalize_book_string("Slewfoot: A Tale of Bewitchery", "Brom")
        assert "slewfoot" in result

    def test_the_prefix_handling(self):
        """'The Hobbit' and 'Hobbit, The' should normalize similarly."""
        from scraper.ml_deduplicate import normalize_book_string
        r1 = normalize_book_string("The Hobbit", "J.R.R. Tolkien")
        r2 = normalize_book_string("Hobbit, The", "J.R.R. Tolkien")
        # Both should contain "hobbit" and "tolkien"
        assert "hobbit" in r1 and "tolkien" in r1
        assert "hobbit" in r2 and "tolkien" in r2


# ─── Test 2: Data Loading ───────────────────────────────────────────────────

class TestLoadAllRawBooks:
    """Test that raw books are loaded correctly from all three sources."""

    def test_loads_goodreads_format(self, tmp_path):
        import json
        from scraper.ml_deduplicate import load_all_raw_books

        # Create a minimal Goodreads JSON
        gr_data = {
            "books": [
                {
                    "title": "Dune",
                    "author": "Frank Herbert",
                    "category": "Currently Reading",
                    "club_name": "Sci-Fi Club",
                    "source_type": "Goodreads",
                    "discussion_url": "https://example.com",
                    "member_count": 5000,
                }
            ]
        }
        gr_file = tmp_path / "goodreads_groups.json"
        gr_file.write_text(json.dumps(gr_data), encoding="utf-8")

        books = load_all_raw_books(
            reddit_path=tmp_path / "nonexistent.json",
            bookclubs_path=tmp_path / "nonexistent2.json",
            goodreads_path=gr_file,
        )
        assert len(books) == 1
        assert books[0]["title"] == "Dune"
        assert books[0]["source_type"] == "Goodreads"
        assert books[0]["category"] == "Currently Reading"

    def test_loads_multiple_sources(self, tmp_path):
        import json
        from scraper.ml_deduplicate import load_all_raw_books

        reddit_data = {
            "books": [
                {
                    "title": "1984",
                    "author": "George Orwell",
                    "category": "Previously Read",
                    "club_name": "r/bookclub",
                    "source_type": "Reddit",
                    "discussion_url": "",
                    "month": "January 2025",
                }
            ]
        }
        gr_data = {
            "books": [
                {
                    "title": "Dune",
                    "author": "Frank Herbert",
                    "category": "Currently Reading",
                    "club_name": "Sci-Fi Club",
                    "source_type": "Goodreads",
                    "discussion_url": "",
                    "member_count": 5000,
                }
            ]
        }
        (tmp_path / "reddit_books.json").write_text(json.dumps(reddit_data), encoding="utf-8")
        (tmp_path / "goodreads_groups.json").write_text(json.dumps(gr_data), encoding="utf-8")

        books = load_all_raw_books(
            reddit_path=tmp_path / "reddit_books.json",
            bookclubs_path=tmp_path / "nonexistent.json",
            goodreads_path=tmp_path / "goodreads_groups.json",
        )
        assert len(books) == 2
        sources = {b["source_type"] for b in books}
        assert sources == {"Reddit", "Goodreads"}


# ─── Test 3: Pre-Grouping (String-Based Dedup) ──────────────────────────────

class TestPreGroup:
    """Test that exact/near-exact duplicates are grouped before ML step."""

    def test_exact_duplicates_merge(self):
        from scraper.ml_deduplicate import pre_group_books
        books = [
            {"title": "Dune", "author": "Frank Herbert", "category": "Currently Reading",
             "club_name": "Club A", "source_type": "Goodreads", "discussion_url": ""},
            {"title": "Dune", "author": "Frank Herbert", "category": "Previously Read",
             "club_name": "Club B", "source_type": "Reddit", "discussion_url": ""},
        ]
        groups = pre_group_books(books)
        # Same book → same group
        assert len(groups) == 1
        key = list(groups.keys())[0]
        assert len(groups[key]) == 2

    def test_different_books_stay_separate(self):
        from scraper.ml_deduplicate import pre_group_books
        books = [
            {"title": "Dune", "author": "Frank Herbert", "category": "Currently Reading",
             "club_name": "Club A", "source_type": "Goodreads", "discussion_url": ""},
            {"title": "1984", "author": "George Orwell", "category": "Previously Read",
             "club_name": "Club B", "source_type": "Reddit", "discussion_url": ""},
        ]
        groups = pre_group_books(books)
        assert len(groups) == 2

    def test_case_insensitive_merge(self):
        from scraper.ml_deduplicate import pre_group_books
        books = [
            {"title": "DUNE", "author": "FRANK HERBERT", "category": "Currently Reading",
             "club_name": "Club A", "source_type": "Goodreads", "discussion_url": ""},
            {"title": "dune", "author": "frank herbert", "category": "Previously Read",
             "club_name": "Club B", "source_type": "Reddit", "discussion_url": ""},
        ]
        groups = pre_group_books(books)
        assert len(groups) == 1

    def test_series_info_ignored_in_grouping(self):
        from scraper.ml_deduplicate import pre_group_books
        books = [
            {"title": "Jaws (Jaws, #1)", "author": "Peter Benchley", "category": "Previously Read",
             "club_name": "Club A", "source_type": "Goodreads", "discussion_url": ""},
            {"title": "Jaws", "author": "Peter Benchley", "category": "Previously Read",
             "club_name": "Club B", "source_type": "Reddit", "discussion_url": ""},
        ]
        groups = pre_group_books(books)
        assert len(groups) == 1


# ─── Test 4: ML Clustering ──────────────────────────────────────────────────

class TestMLClustering:
    """Test the semantic clustering merges fuzzy duplicates."""

    def test_cluster_merges_fuzzy_titles(self):
        """Titles that are semantically similar should cluster together."""
        from scraper.ml_deduplicate import cluster_groups_ml

        # Simulate pre-grouped data where string normalization wasn't enough
        groups = {
            "harry potter sorcerers stone j k rowling": [
                {"title": "Harry Potter and the Sorcerer's Stone", "author": "J.K. Rowling",
                 "category": "Previously Read", "club_name": "Club A",
                 "source_type": "Reddit", "discussion_url": ""},
            ],
            "harry potter philosophers stone j k rowling": [
                {"title": "Harry Potter and the Philosopher's Stone", "author": "J.K. Rowling",
                 "category": "Previously Read", "club_name": "Club B",
                 "source_type": "Goodreads", "discussion_url": ""},
            ],
            "dune frank herbert": [
                {"title": "Dune", "author": "Frank Herbert",
                 "category": "Currently Reading", "club_name": "Club C",
                 "source_type": "Goodreads", "discussion_url": ""},
            ],
        }
        clusters = cluster_groups_ml(groups, similarity_threshold=0.75)

        # Harry Potter variants should be merged into one cluster
        # Dune should remain separate
        # So we expect 2 clusters total
        assert len(clusters) == 2

        # Find the Harry Potter cluster (the one with 2 books)
        hp_cluster = [c for c in clusters if len(c["books"]) == 2]
        assert len(hp_cluster) == 1
        assert "harry potter" in hp_cluster[0]["representative_title"].lower()

    def test_unrelated_books_stay_separate(self):
        """Completely different books should NOT be merged."""
        from scraper.ml_deduplicate import cluster_groups_ml

        groups = {
            "dune frank herbert": [
                {"title": "Dune", "author": "Frank Herbert",
                 "category": "Currently Reading", "club_name": "Club A",
                 "source_type": "Goodreads", "discussion_url": ""},
            ],
            "pride and prejudice jane austen": [
                {"title": "Pride and Prejudice", "author": "Jane Austen",
                 "category": "Previously Read", "club_name": "Club B",
                 "source_type": "Reddit", "discussion_url": ""},
            ],
        }
        clusters = cluster_groups_ml(groups, similarity_threshold=0.75)
        assert len(clusters) == 2


# ─── Test 5: Priority Assignment ────────────────────────────────────────────

class TestPriorityAssignment:
    """Test that Currently Reading books get highest priority."""

    def test_currently_reading_gets_priority_a(self):
        from scraper.ml_deduplicate import assign_priority
        cluster = {
            "representative_title": "Dune",
            "representative_author": "Frank Herbert",
            "books": [
                {"title": "Dune", "author": "Frank Herbert",
                 "category": "Currently Reading", "club_name": "Club A",
                 "source_type": "Goodreads", "discussion_url": "", "member_count": 5000},
            ],
        }
        result = assign_priority(cluster)
        assert result["priority"] == "A"

    def test_previously_read_gets_priority_b(self):
        from scraper.ml_deduplicate import assign_priority
        cluster = {
            "representative_title": "Dune",
            "representative_author": "Frank Herbert",
            "books": [
                {"title": "Dune", "author": "Frank Herbert",
                 "category": "Previously Read", "club_name": "Club A",
                 "source_type": "Goodreads", "discussion_url": "", "member_count": 5000},
            ],
        }
        result = assign_priority(cluster)
        assert result["priority"] == "B"

    def test_mixed_categories_get_priority_a(self):
        """If ANY book in the cluster is Currently Reading, the whole cluster is Priority A."""
        from scraper.ml_deduplicate import assign_priority
        cluster = {
            "representative_title": "Dune",
            "representative_author": "Frank Herbert",
            "books": [
                {"title": "Dune", "author": "Frank Herbert",
                 "category": "Previously Read", "club_name": "Club A",
                 "source_type": "Reddit", "discussion_url": ""},
                {"title": "Dune", "author": "Frank Herbert",
                 "category": "Currently Reading", "club_name": "Club B",
                 "source_type": "Goodreads", "discussion_url": "", "member_count": 5000},
            ],
        }
        result = assign_priority(cluster)
        assert result["priority"] == "A"

    def test_priority_sort_order(self):
        """Priority A books should sort before Priority B."""
        from scraper.ml_deduplicate import assign_priority
        cluster_a = {
            "representative_title": "Dune",
            "representative_author": "Frank Herbert",
            "books": [
                {"title": "Dune", "author": "Frank Herbert",
                 "category": "Currently Reading", "club_name": "Club A",
                 "source_type": "Goodreads", "discussion_url": "", "member_count": 100},
            ],
        }
        cluster_b = {
            "representative_title": "1984",
            "representative_author": "George Orwell",
            "books": [
                {"title": "1984", "author": "George Orwell",
                 "category": "Previously Read", "club_name": "Club B",
                 "source_type": "Reddit", "discussion_url": ""},
                {"title": "1984", "author": "George Orwell",
                 "category": "Previously Read", "club_name": "Club C",
                 "source_type": "Reddit", "discussion_url": ""},
                {"title": "1984", "author": "George Orwell",
                 "category": "Previously Read", "club_name": "Club D",
                 "source_type": "Reddit", "discussion_url": ""},
            ],
        }
        result_a = assign_priority(cluster_a)
        result_b = assign_priority(cluster_b)

        # A should come before B even though B has more clubs
        all_results = sorted([result_b, result_a], key=lambda x: (x["priority"], -x["club_count"]))
        assert all_results[0]["representative_title"] == "Dune"


# ─── Test 6: Output Format ──────────────────────────────────────────────────

class TestOutputFormat:
    """Test that the final output has the correct schema."""

    def test_cluster_output_has_required_fields(self):
        from scraper.ml_deduplicate import assign_priority
        cluster = {
            "representative_title": "Dune",
            "representative_author": "Frank Herbert",
            "books": [
                {"title": "Dune", "author": "Frank Herbert",
                 "category": "Currently Reading", "club_name": "Club A",
                 "source_type": "Goodreads", "discussion_url": "https://example.com",
                 "member_count": 5000},
            ],
        }
        result = assign_priority(cluster)

        # Required fields for downstream enrich_books.py
        assert "representative_title" in result
        assert "representative_author" in result
        assert "priority" in result
        assert "club_count" in result
        assert "clubs" in result
        assert "has_currently_reading" in result
        assert isinstance(result["clubs"], list)
        assert len(result["clubs"]) == 1
