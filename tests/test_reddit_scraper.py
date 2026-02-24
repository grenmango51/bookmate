import pytest
from datetime import datetime
from scraper.scrape_reddit_wiki import categorize_by_month

def test_categorize_by_month():
    # Keep current time fixed to Feb 2026 for testing
    now = datetime(2026, 2, 24)

    # Current month
    assert categorize_by_month("February 2026", current_time=now) == "Currently Reading"
    
    # Preceding month
    assert categorize_by_month("January 2026", current_time=now) == "Currently Reading"
    
    # Older month
    assert categorize_by_month("December 2025", current_time=now) == "Previously Read"
    assert categorize_by_month("February 2025", current_time=now) == "Previously Read"
    
    # Unknown/Malformed month names
    assert categorize_by_month("Unknown String", current_time=now) == "Previously Read"
    assert categorize_by_month("Summer 2026", current_time=now) == "Previously Read"
    assert categorize_by_month("", current_time=now) == "Previously Read"

    # Future months
    assert categorize_by_month("March 2026", current_time=now) == "Previously Read"
