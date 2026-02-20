"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import {
  Search, ArrowUpRight, CheckCircle2, Calendar,
  BookOpen, MessageSquare, X, Filter
} from "lucide-react";

// ─── Types ──────────────────────────────────────────────────────────────────
interface SearchResult {
  title: string;
  author: string;
  category: string;
  month: string;
  discussion_url: string;
  source: string;
  verified: boolean;
  relevance_score: number;
}

interface SearchResponse {
  query: string;
  total_results: number;
  total_indexed: number;
  results: SearchResult[];
  fallback_links: {
    reddit_search: string;
    goodreads: string;
    bookclubs: string;
  };
  data_freshness: string | null;
}

// ─── SVG Icons ──────────────────────────────────────────────────────────────

function RedditIcon({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0zm5.01 4.744c.688 0 1.25.561 1.25 1.249a1.25 1.25 0 0 1-2.498.056l-2.597-.547-.8 3.747c1.824.07 3.48.632 4.674 1.488.308-.309.73-.491 1.207-.491.968 0 1.754.786 1.754 1.754 0 .716-.435 1.333-1.01 1.614a3.111 3.111 0 0 1 .042.52c0 2.694-3.13 4.87-7.004 4.87-3.874 0-7.004-2.176-7.004-4.87 0-.183.015-.366.043-.534A1.748 1.748 0 0 1 4.028 12c0-.968.786-1.754 1.754-1.754.463 0 .898.196 1.207.49 1.207-.883 2.878-1.43 4.744-1.487l.885-4.182a.342.342 0 0 1 .14-.197.35.35 0 0 1 .238-.042l2.906.617a1.214 1.214 0 0 1 1.108-.701zM9.25 12C8.561 12 8 12.562 8 13.25c0 .687.561 1.248 1.25 1.248.687 0 1.248-.561 1.248-1.249 0-.688-.561-1.249-1.249-1.249zm5.5 0c-.687 0-1.248.561-1.248 1.25 0 .687.561 1.248 1.249 1.248.688 0 1.249-.561 1.249-1.249 0-.687-.562-1.249-1.25-1.249zm-5.466 3.99a.327.327 0 0 0-.231.094.33.33 0 0 0 0 .463c.842.842 2.484.913 2.961.913.477 0 2.105-.056 2.961-.913a.361.361 0 0 0 .029-.463.33.33 0 0 0-.464 0c-.547.533-1.684.73-2.512.73-.828 0-1.979-.196-2.512-.73a.326.326 0 0 0-.232-.095z" />
    </svg>
  );
}

// ─── Category helpers ───────────────────────────────────────────────────────

function normalizeCategory(cat: string): string {
  if (!cat) return "";
  if (cat.startsWith("Read the World")) return "Read the World";
  if (cat.startsWith("Any")) return "Any";
  if (cat.startsWith("Horror")) return "Horror";
  if (cat.startsWith("Discovery Read")) return "Discovery Read";
  if (cat.includes("LGBTQ")) return "LGBTQ+";
  if (cat === "Sci Fi") return "Sci-Fi";
  if (cat === "Nonfiction" || cat === "Quarterly Non-Fiction") return "Non-Fiction";
  if (cat.startsWith("Author Profile")) return "Author Profile";
  if (cat.includes("Big") && cat.includes("Read")) return "Big Read";
  return cat;
}

function getTopCategories(results: SearchResult[]): string[] {
  const counts: Record<string, number> = {};
  for (const r of results) {
    const cat = normalizeCategory(r.category);
    if (cat) counts[cat] = (counts[cat] || 0) + 1;
  }
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 12)
    .map(([cat]) => cat);
}

// ─── Component ──────────────────────────────────────────────────────────────

export default function Home() {
  const [query, setQuery] = useState("");
  const [allResults, setAllResults] = useState<SearchResult[]>([]);
  const [filteredResults, setFilteredResults] = useState<SearchResult[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [totalIndexed, setTotalIndexed] = useState(0);
  const [dataFreshness, setDataFreshness] = useState<string | null>(null);
  const [fallbackLinks, setFallbackLinks] = useState<SearchResponse["fallback_links"] | null>(null);
  const [activeCategory, setActiveCategory] = useState<string | null>(null);
  const [visibleCount, setVisibleCount] = useState(40);
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Load all books on mount
  useEffect(() => {
    async function loadAll() {
      try {
        const res = await fetch("/api/search");
        const data: SearchResponse = await res.json();
        setAllResults(data.results);
        setFilteredResults(data.results);
        setTotalIndexed(data.total_indexed);
        setDataFreshness(data.data_freshness);
        setFallbackLinks(data.fallback_links);
      } catch (err) {
        console.error("Failed to load books:", err);
      } finally {
        setIsLoading(false);
      }
    }
    loadAll();
  }, []);

  // Recompute filtered results when query or category changes
  const applyFilters = useCallback((searchResults: SearchResult[], category: string | null) => {
    if (!category) {
      setFilteredResults(searchResults);
    } else {
      setFilteredResults(searchResults.filter(r => normalizeCategory(r.category) === category));
    }
    setVisibleCount(40);
  }, []);

  // Search
  const performSearch = useCallback(async (searchQuery: string) => {
    if (searchQuery.trim().length < 2) {
      applyFilters(allResults, activeCategory);
      return;
    }
    try {
      const res = await fetch(`/api/search?q=${encodeURIComponent(searchQuery)}`);
      const data: SearchResponse = await res.json();
      setFallbackLinks(data.fallback_links);
      applyFilters(data.results, activeCategory);
    } catch (err) {
      console.error("Search failed:", err);
    }
  }, [allResults, activeCategory, applyFilters]);

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    setQuery(value);
    if (debounceTimer.current) clearTimeout(debounceTimer.current);
    debounceTimer.current = setTimeout(() => performSearch(value), 300);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      if (debounceTimer.current) clearTimeout(debounceTimer.current);
      performSearch(query);
    }
  };

  const clearSearch = () => {
    setQuery("");
    applyFilters(allResults, activeCategory);
    inputRef.current?.focus();
  };

  const toggleCategory = (cat: string) => {
    const newCat = activeCategory === cat ? null : cat;
    setActiveCategory(newCat);
    // Re-run current search with new category
    if (query.trim().length >= 2) {
      fetch(`/api/search?q=${encodeURIComponent(query)}`)
        .then(res => res.json())
        .then((data: SearchResponse) => applyFilters(data.results, newCat));
    } else {
      applyFilters(allResults, newCat);
    }
  };

  const categories = getTopCategories(allResults);
  const visibleResults = filteredResults.slice(0, visibleCount);
  const hasMore = visibleCount < filteredResults.length;

  useEffect(() => { inputRef.current?.focus(); }, []);

  return (
    <div className="app-root">
      {/* ═══ STICKY HEADER ═══ */}
      <header className="app-header">
        <div className="app-header-top">
          <div className="app-brand">
            <span className="app-logo">BOOKMATE</span>
            <span className="app-badge">
              <span className="app-badge-dot" />
              {isLoading ? "..." : totalIndexed} books indexed
            </span>
          </div>

          <div className="app-search-wrap">
            <Search size={16} className="app-search-icon" />
            <input
              ref={inputRef}
              id="search-input"
              type="text"
              className="app-search-input"
              placeholder="Filter by title or author..."
              value={query}
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
              autoComplete="off"
            />
            {query && (
              <button className="app-search-clear" onClick={clearSearch} aria-label="Clear">
                <X size={14} />
              </button>
            )}
          </div>
        </div>

        {categories.length > 0 && (
          <div className="app-categories">
            <Filter size={13} style={{ color: "var(--text-muted)", flexShrink: 0, marginTop: 1 }} />
            <div className="app-category-scroll">
              {categories.map(cat => (
                <button
                  key={cat}
                  className={`app-cat-pill${activeCategory === cat ? " active" : ""}`}
                  onClick={() => toggleCategory(cat)}
                >
                  {cat}
                </button>
              ))}
            </div>
          </div>
        )}
      </header>

      {/* ═══ CONTENT ═══ */}
      <main className="app-main">
        {/* Results Count Bar */}
        <div className="app-results-bar">
          <span className="app-results-count">{filteredResults.length}</span>
          <span className="app-results-label">
            {query ? "matches" : "books"}
            {activeCategory && <> in <strong>{activeCategory}</strong></>}
          </span>
        </div>

        {/* Loading */}
        {isLoading && (
          <div className="app-skeleton-list">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="app-skeleton-item" />
            ))}
          </div>
        )}

        {/* Book List */}
        {!isLoading && visibleResults.length > 0 && (
          <div className="app-book-list">
            {visibleResults.map((book, i) => (
              <a
                key={`${book.title}-${i}`}
                href={book.discussion_url}
                target="_blank"
                rel="noopener noreferrer"
                className={`app-book-row${book.verified ? " verified" : ""}`}
              >
                <div className="app-book-info">
                  <div className="app-book-title-row">
                    <span className="app-book-title">{book.title}</span>
                    {book.verified && <CheckCircle2 size={12} className="app-book-check" />}
                  </div>
                  <div className="app-book-meta">
                    {book.author && <span className="app-book-author">{book.author}</span>}
                    {book.category && (
                      <>
                        <span className="app-book-sep" />
                        <span className="app-book-cat">{book.category}</span>
                      </>
                    )}
                    {book.month && (
                      <>
                        <span className="app-book-sep" />
                        <span className="app-book-date">
                          <Calendar size={11} />
                          {book.month}
                        </span>
                      </>
                    )}
                  </div>
                </div>
                <span className="app-book-arrow">
                  <ArrowUpRight size={14} />
                </span>
              </a>
            ))}

            {hasMore && (
              <button className="app-load-more" onClick={() => setVisibleCount(v => v + 40)}>
                Show more ({filteredResults.length - visibleCount} remaining)
              </button>
            )}
          </div>
        )}

        {/* No Results */}
        {!isLoading && query && filteredResults.length === 0 && (
          <div className="app-no-results">
            <BookOpen size={36} style={{ opacity: 0.15 }} />
            <h3>No matches found</h3>
            <p>&ldquo;{query}&rdquo; wasn&apos;t in the r/bookclub archive. Try these platforms:</p>
            {fallbackLinks && (
              <div className="app-fallback-row">
                <a href={fallbackLinks.reddit_search} target="_blank" rel="noopener noreferrer" className="app-fallback-btn reddit">
                  <RedditIcon size={14} /> Reddit <ArrowUpRight size={12} />
                </a>
                <a href={fallbackLinks.goodreads} target="_blank" rel="noopener noreferrer" className="app-fallback-btn goodreads">
                  <BookOpen size={14} /> Goodreads <ArrowUpRight size={12} />
                </a>
              </div>
            )}
          </div>
        )}
      </main>

      {/* ═══ FOOTER ═══ */}
      <footer className="app-footer">
        <p>
          Data from{" "}
          <a href="https://www.reddit.com/r/bookclub/wiki/previous/" target="_blank" rel="noopener noreferrer">
            r/bookclub wiki
          </a>
          {dataFreshness && <span> · Updated {new Date(dataFreshness).toLocaleDateString()}</span>}
        </p>
        <a href="mailto:greenmangono1@gmail.com?subject=Bookmate%20Feedback" className="app-feedback">
          <MessageSquare size={12} /> Give Feedback
        </a>
      </footer>
    </div>
  );
}
