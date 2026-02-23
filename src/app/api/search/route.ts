import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";

// ─── Types ──────────────────────────────────────────────────────────────────
interface BookEntry {
    title: string;
    author: string;
    category: string;
    month: string;
    discussion_url: string;
    club_name?: string;
    source_type?: string;
}

interface RedditData {
    scraped_at: string;
    source: string;
    total_books: number;
    books: BookEntry[];
}

interface BookclubsData {
    scraped_at: string;
    source: string;
    total_books: number;
    books: BookEntry[];
}

interface SearchResult {
    title: string;
    author: string;
    category: string;
    month: string;
    discussion_url: string;
    club_name: string;
    source_type: string;
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

    // Build date for the 1st of that month
    const bookDate = new Date(year, monthIndex, 1);

    // Build cutoff: 3 months ago from the 1st of the current month
    const cutoff = new Date(now.getFullYear(), now.getMonth() - 2, 1);

    return bookDate >= cutoff;
}

// ─── Load data ──────────────────────────────────────────────────────────────

let cachedBooks: BookEntry[] | null = null;
let cachedFreshness: string | null = null;

function loadAllBooks(): { books: BookEntry[]; freshness: string | null } {
    if (cachedBooks) return { books: cachedBooks, freshness: cachedFreshness };

    const allBooks: BookEntry[] = [];
    let latestFreshness: string | null = null;

    // Load Reddit data
    const redditPath = path.join(process.cwd(), "data", "reddit_books.json");
    try {
        const raw = fs.readFileSync(redditPath, "utf-8");
        const data: RedditData = JSON.parse(raw);
        for (const book of data.books) {
            if (book.title === "Here is the list of authors previously read.") continue;
            allBooks.push({
                ...book,
                club_name: book.club_name || "r/bookclub",
                source_type: book.source_type || "Reddit",
            });
        }
        latestFreshness = data.scraped_at;
    } catch {
        console.error("Failed to load reddit_books.json");
    }

    // Load Bookclubs.com data
    const bookclubsPath = path.join(process.cwd(), "data", "bookclubs_com.json");
    try {
        const raw = fs.readFileSync(bookclubsPath, "utf-8");
        const data: BookclubsData = JSON.parse(raw);
        for (const book of data.books) {
            allBooks.push({
                ...book,
                club_name: book.club_name || "Unknown Club",
                source_type: book.source_type || "Bookclubs.com",
            });
        }
        if (data.scraped_at && (!latestFreshness || data.scraped_at > latestFreshness)) {
            latestFreshness = data.scraped_at;
        }
    } catch {
        // bookclubs_com.json may not exist yet, that's fine
    }

    cachedBooks = allBooks;
    cachedFreshness = latestFreshness;
    return { books: allBooks, freshness: latestFreshness };
}

// ─── Search endpoint ────────────────────────────────────────────────────────

export async function GET(request: NextRequest) {
    const { searchParams } = new URL(request.url);
    const query = searchParams.get("q")?.trim() || "";
    const activeOnly = searchParams.get("active") === "true";

    let { books: allBooks, freshness } = loadAllBooks();

    // Apply active-only filter (last 3 months)
    if (activeOnly) {
        allBooks = allBooks.filter((b) => isWithinLastThreeMonths(b.month));
    }

    let results: SearchResult[];

    if (query.length < 2) {
        // No query: return ALL books sorted alphabetically
        results = allBooks
            .map((book) => ({
                title: book.title,
                author: book.author,
                category: book.category,
                month: book.month,
                discussion_url: book.discussion_url,
                club_name: book.club_name || "r/bookclub",
                source_type: book.source_type || "Reddit",
                verified: true,
                relevance_score: 50,
            }))
            .sort((a, b) => a.title.localeCompare(b.title));
    } else {
        // Query: fuzzy search across title, author, AND club_name
        results = [];
        for (const book of allBooks) {
            const score = calculateRelevance(query, book.title, book.author, book.club_name || "");
            if (score > 20) {
                results.push({
                    title: book.title,
                    author: book.author,
                    category: book.category,
                    month: book.month,
                    discussion_url: book.discussion_url,
                    club_name: book.club_name || "r/bookclub",
                    source_type: book.source_type || "Reddit",
                    verified: true,
                    relevance_score: score,
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
        total_indexed: allBooks.length,
        results: results.slice(0, 50),
        fallback_links,
        data_freshness: freshness,
    });
}
