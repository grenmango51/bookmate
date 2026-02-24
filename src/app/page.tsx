"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import {
  Search, ArrowUpRight, CheckCircle2, Calendar,
  BookOpen, MessageSquare, X, Users, Zap
} from "lucide-react";

// ─── Types ──────────────────────────────────────────────────────────────────
interface ClubInteraction {
  club_name: string;
  source_type: string;
  discussion_url: string;
  month: string;
}

interface SearchResult {
  title: string;
  author: string;
  categories: string[];
  page_count: number | null;
  thumbnail: string;
  clubs: ClubInteraction[];
  verified: boolean;
  relevance_score: number;
}

interface SearchResponse {
  query: string;
  total_results: number;
  total_indexed: number;
  all_genres: string[];
  results: SearchResult[];
  fallback_links: {
    reddit_search: string;
    goodreads: string;
    bookclubs: string;
  };
  data_freshness: string | null;
}

// ─── SVG Icons ──────────────────────────────────────────────────────────────

function RedditIcon({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0zm5.01 4.744c.688 0 1.25.561 1.25 1.249a1.25 1.25 0 0 1-2.498.056l-2.597-.547-.8 3.747c1.824.07 3.48.632 4.674 1.488.308-.309.73-.491 1.207-.491.968 0 1.754.786 1.754 1.754 0 .716-.435 1.333-1.01 1.614a3.111 3.111 0 0 1 .042.52c0 2.694-3.13 4.87-7.004 4.87-3.874 0-7.004-2.176-7.004-4.87 0-.183.015-.366.043-.534A1.748 1.748 0 0 1 4.028 12c0-.968.786-1.754 1.754-1.754.463 0 .898.196 1.207.49 1.207-.883 2.878-1.43 4.744-1.487l.885-4.182a.342.342 0 0 1 .14-.197.35.35 0 0 1 .238-.042l2.906.617a1.214 1.214 0 0 1 1.108-.701zM9.25 12C8.561 12 8 12.562 8 13.25c0 .687.561 1.248 1.25 1.248.687 0 1.248-.561 1.248-1.249 0-.688-.561-1.249-1.249-1.249zm5.5 0c-.687 0-1.248.561-1.248 1.25 0 .687.561 1.248 1.249 1.248.688 0 1.249-.561 1.249-1.249 0-.687-.562-1.249-1.25-1.249zm-5.466 3.99a.327.327 0 0 0-.231.094.33.33 0 0 0 0 .463c.842.842 2.484.913 2.961.913.477 0 2.105-.056 2.961-.913a.361.361 0 0 0 .029-.463.33.33 0 0 0-.464 0c-.547.533-1.684.73-2.512.73-.828 0-1.979-.196-2.512-.73a.326.326 0 0 0-.232-.095z" />
    </svg>
  );
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
  const [visibleCount, setVisibleCount] = useState(40);
  const [activeOnly, setActiveOnly] = useState(false);
  const [allGenres, setAllGenres] = useState<string[]>([]);
  const [selectedGenre, setSelectedGenre] = useState("");
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Fetch books from API
  const fetchBooks = useCallback(async (searchQuery: string, active: boolean, genre: string) => {
    setVisibleCount(40);
    const params = new URLSearchParams();
    if (searchQuery.trim().length >= 2) params.set("q", searchQuery);
    if (active) params.set("active", "true");
    if (genre) params.set("genre", genre);
    const qs = params.toString() ? `?${params.toString()}` : "";

    try {
      const res = await fetch(`/api/search${qs}`);
      const data: SearchResponse = await res.json();
      setAllResults(data.results);
      setFilteredResults(data.results);
      setTotalIndexed(data.total_indexed);
      setDataFreshness(data.data_freshness);
      setFallbackLinks(data.fallback_links);
      if (data.all_genres && data.all_genres.length > 0) {
        setAllGenres(data.all_genres);
      }
    } catch (err) {
      console.error("Fetch failed:", err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Load on mount
  useEffect(() => { fetchBooks("", false, ""); }, [fetchBooks]);

  // Re-fetch when activeOnly or genre toggles
  useEffect(() => { fetchBooks(query, activeOnly, selectedGenre); }, [activeOnly, selectedGenre]); // eslint-disable-line react-hooks/exhaustive-deps

  // Search
  const performSearch = useCallback(async (searchQuery: string) => {
    fetchBooks(searchQuery, activeOnly, selectedGenre);
  }, [activeOnly, selectedGenre, fetchBooks]);

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
    fetchBooks("", activeOnly, selectedGenre);
    inputRef.current?.focus();
  };

  const toggleActive = () => setActiveOnly((prev) => !prev);

  const selectGenre = (genre: string) => {
    setSelectedGenre(prev => prev === genre ? "" : genre);
  };

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
              placeholder="Filter by book, author, or club name..."
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

          {/* Active Now toggle */}
          <button
            className={`app-active-toggle ${activeOnly ? "active" : ""}`}
            onClick={toggleActive}
            aria-label="Toggle active books"
            title={activeOnly ? "Showing books from last 3 months" : "Show only active books"}
          >
            <Zap size={13} />
            <span>Active</span>
          </button>
        </div>

        {/* Genre filter pills */}
        <div className="app-categories" id="category-filters">
          {allGenres.slice(0, 12).map((genre) => (
            <button
              key={genre}
              className={`app-category-pill ${selectedGenre === genre ? "active" : ""}`}
              onClick={() => selectGenre(genre)}
            >
              {genre}
            </button>
          ))}
          {selectedGenre && (
            <button
              className="app-category-pill clear"
              onClick={() => setSelectedGenre("")}
            >
              <X size={11} /> Clear
            </button>
          )}
        </div>
      </header>

      {/* ═══ CONTENT ═══ */}
      <main className="app-main">
        {/* Results Count Bar */}
        <div className="app-results-bar">
          <span className="app-results-count">{filteredResults.length}</span>
          <span className="app-results-label">
            {query ? "matches" : "books"}
            {selectedGenre && ` in ${selectedGenre}`}
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
                href={book.clubs && book.clubs.length > 0 ? book.clubs[0].discussion_url : "#"}
                target="_blank"
                rel="noopener noreferrer"
                className="app-book-row"
              >
                <div className="app-book-info">
                  <div className="app-book-title-row">
                    <span className="app-book-title">{book.title}</span>
                    {book.verified && <CheckCircle2 size={12} className="app-book-check" />}
                  </div>
                  <div className="app-book-meta">
                    {book.author && <span className="app-book-author">{book.author}</span>}
                    {book.author && book.clubs?.length > 0 && <span className="app-book-sep" />}

                    {book.clubs?.length === 1 && (
                      <span className={`app-book-club ${book.clubs[0].source_type === "Reddit" ? "reddit" : "bookclubs"}`}>
                        {book.clubs[0].source_type === "Reddit" ? <RedditIcon size={11} /> : <Users size={11} />}
                        {book.clubs[0].club_name}
                      </span>
                    )}

                    {book.clubs?.length > 1 && (
                      <span
                        className="app-book-club bookclubs multi"
                        title={`Read by:\n${book.clubs.map(c => `• ${c.club_name}`).join('\n')}`}
                      >
                        <Users size={11} />
                        Read by {book.clubs.length} clubs
                      </span>
                    )}

                    {book.categories?.length > 0 && (
                      <>
                        <span className="app-book-sep" />
                        <span className="app-book-genre">
                          {book.categories[0]}
                        </span>
                      </>
                    )}

                    {book.clubs?.length === 1 && book.clubs[0].month && book.clubs[0].month !== "Unknown" && (
                      <>
                        <span className="app-book-sep" />
                        <span className="app-book-date">
                          <Calendar size={11} />
                          {book.clubs[0].month}
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
            <p>&ldquo;{query}&rdquo; wasn&apos;t found in our indexed book clubs. Try these platforms:</p>
            {fallbackLinks && (
              <div className="app-fallback-row">
                <a href={fallbackLinks.reddit_search} target="_blank" rel="noopener noreferrer" className="app-fallback-btn reddit">
                  <RedditIcon /> Reddit <ArrowUpRight size={12} />
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
          Data sourced from{" "}
          <a href="https://www.reddit.com/r/bookclub/wiki/previous/" target="_blank" rel="noopener noreferrer">
            Reddit
          </a>
          {" and "}
          <a href="https://bookclubs.com" target="_blank" rel="noopener noreferrer">
            public book clubs
          </a>
          {dataFreshness && <span> · Updated {new Date(dataFreshness).toLocaleDateString()}</span>}
        </p>
        <a href="mailto:feedback@bookmate.app?subject=Bookmate Feedback" className="app-feedback">
          <MessageSquare size={12} /> Give Feedback
        </a>
      </footer>
    </div>
  );
}
