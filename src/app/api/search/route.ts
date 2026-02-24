import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";

// ─── Types ──────────────────────────────────────────────────────────────────

interface ClubInteraction {
    club_name: string;
    source_type: string;
    discussion_url: string;
    month: string;
    original_title: string;
}

interface EnrichedBook {
    google_books_id?: string;
    canonical_title: string;
    canonical_author: string;
    categories: string[];
    page_count: number | null;
    published_date: string;
    thumbnail: string;
    description: string;
    clubs: ClubInteraction[];
}

interface EnrichedData {
    enriched_at: string;
    stats: {
        total_unique_books: number;
        total_club_interactions: number;
        books_with_genre: number;
        books_read_by_multiple_clubs: number;
        all_genres: string[];
    };
    books: EnrichedBook[];
}

interface SearchResult {
    title: string;
    author: string;
    categories: string[];
    page_count: number | null;
    thumbnail: string;
    clubs: {
        club_name: string;
        source_type: string;
        discussion_url: string;
        month: string;
    }[];
    verified: boolean;
    relevance_score: number;
}

// ─── Fuzzy matching helpers ─────────────────────────────────────────────────

function normalize(text: string): string {
    return text
        .toLowerCase()
        .replace(/[^a-z0-9\s]/g, "")
        .replace(/\s+/g, " ")
        .trim();
}

function calculateRelevance(query: string, title: string, author: string, clubName: string): number {
    const normQuery = normalize(query);
    const normTitle = normalize(title);
    const normAuthor = normalize(author);
    const normClub = normalize(clubName);

    // Exact title match
    if (normTitle === normQuery) return 100;

    // Title starts with query
    if (normTitle.startsWith(normQuery)) return 90;

    // Query starts with title
    if (normQuery.startsWith(normTitle)) return 85;

    // Title contains query
    if (normTitle.includes(normQuery)) return 75;

    // Query contains title
    if (normQuery.includes(normTitle)) return 70;

    // Author match
    if (normAuthor.includes(normQuery)) return 60;

    // Club name match
    if (normClub.includes(normQuery)) return 55;
    if (normQuery.includes(normClub) && normClub.length > 2) return 50;

    // Word-level matching (excluding stop words)
    const stopWords = new Set(["the", "a", "an", "and", "or", "of", "in", "on", "at", "to", "by", "for", "is", "it", "its"]);
    const queryWords = normQuery.split(" ").filter((w) => w.length > 1 && !stopWords.has(w));
    const allWords = [...normTitle.split(" "), ...normAuthor.split(" "), ...normClub.split(" ")]
        .filter((w) => w.length > 1 && !stopWords.has(w));

    if (queryWords.length === 0) return 0;

    const matchingWords = queryWords.filter((w) =>
        allWords.some((tw) => tw === w || (w.length >= 4 && (tw.includes(w) || w.includes(tw))))
    );
    const wordScore = (matchingWords.length / queryWords.length) * 50;
    if (wordScore >= 40) return wordScore;

    return 0;
}

// ─── Active filter helper ───────────────────────────────────────────────────

const MONTH_NAMES = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
];

function isWithinLastThreeMonths(monthStr: string): boolean {
    if (!monthStr || monthStr === "Unknown") return false;

    const now = new Date();
    const parts = monthStr.trim().toLowerCase().split(/\s+/);
    if (parts.length < 2) return false;

    const monthIndex = MONTH_NAMES.indexOf(parts[0]);
    const year = parseInt(parts[1], 10);
    if (monthIndex === -1 || isNaN(year)) return false;

    const bookDate = new Date(year, monthIndex, 1);
    const cutoff = new Date(now.getFullYear(), now.getMonth() - 2, 1);

    return bookDate >= cutoff;
}

// ─── Load data ──────────────────────────────────────────────────────────────

let cachedData: EnrichedData | null = null; // Forces dev reload 2

function loadEnrichedBooks(): EnrichedData {
    if (cachedData) return cachedData;

    const filePath = path.join(process.cwd(), "data", "enriched_books.json");
    try {
        const raw = fs.readFileSync(filePath, "utf-8");
        cachedData = JSON.parse(raw) as EnrichedData;
        return cachedData;
    } catch {
        // Fallback: return empty data
        console.error("Failed to load enriched_books.json");
        return {
            enriched_at: "",
            stats: {
                total_unique_books: 0,
                total_club_interactions: 0,
                books_with_genre: 0,
                books_read_by_multiple_clubs: 0,
                all_genres: [],
            },
            books: [],
        };
    }
}

// ─── Search endpoint ────────────────────────────────────────────────────────

export async function GET(request: NextRequest) {
    const { searchParams } = new URL(request.url);
    const query = searchParams.get("q")?.trim() || "";
    const activeOnly = searchParams.get("active") === "true";
    const genreFilter = searchParams.get("genre")?.trim() || "";

    const data = loadEnrichedBooks();
    let books = data.books;

    // Apply active-only filter: keep books where at least one club is active
    if (activeOnly) {
        books = books.filter((b) =>
            b.clubs.some((c) => isWithinLastThreeMonths(c.month))
        );
    }

    // Apply genre filter
    if (genreFilter) {
        const normGenre = genreFilter.toLowerCase();
        books = books.filter((b) =>
            b.categories.some((cat) => cat.toLowerCase().includes(normGenre))
        );
    }

    let results: SearchResult[];

    if (query.length < 2) {
        // No query: return all books sorted alphabetically
        results = books.map((book) => ({
            title: book.canonical_title,
            author: book.canonical_author,
            categories: book.categories,
            page_count: book.page_count,
            thumbnail: book.thumbnail,
            clubs: book.clubs.map((c) => ({
                club_name: c.club_name,
                source_type: c.source_type,
                discussion_url: c.discussion_url,
                month: c.month,
            })),
            verified: true,
            relevance_score: 50,
        }));
    } else {
        // Query: fuzzy search across title, author, and all club names
        results = [];
        for (const book of books) {
            let maxScore = calculateRelevance(
                query,
                book.canonical_title,
                book.canonical_author,
                ""
            );

            // Also check if query matches any club name
            for (const c of book.clubs) {
                const clubScore = calculateRelevance(query, "", "", c.club_name);
                maxScore = Math.max(maxScore, clubScore);
            }

            if (maxScore > 20) {
                results.push({
                    title: book.canonical_title,
                    author: book.canonical_author,
                    categories: book.categories,
                    page_count: book.page_count,
                    thumbnail: book.thumbnail,
                    clubs: book.clubs.map((c) => ({
                        club_name: c.club_name,
                        source_type: c.source_type,
                        discussion_url: c.discussion_url,
                        month: c.month,
                    })),
                    verified: true,
                    relevance_score: maxScore,
                });
            }
        }
        results.sort((a, b) => b.relevance_score - a.relevance_score);
    }

    // Fallback links
    const encodedQuery = encodeURIComponent(query || "book club");
    const fallback_links = {
        reddit_search: `https://www.reddit.com/r/bookclub/search/?q=${encodedQuery}&restrict_sr=1`,
        goodreads: `https://www.goodreads.com/search?q=${encodedQuery}`,
        bookclubs: `https://bookclubs.com/join-a-book-club/search/?query=${encodedQuery}`,
    };

    return NextResponse.json({
        query,
        total_results: results.length,
        total_indexed: data.stats.total_unique_books,
        all_genres: data.stats.all_genres,
        results: results.slice(0, 50),
        fallback_links,
        data_freshness: data.enriched_at,
    });
}
