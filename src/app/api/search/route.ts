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
}

interface RedditData {
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
    source: "reddit_wiki" | "reddit_search" | "goodreads" | "bookclubs";
    verified: boolean;
    relevance_score: number;
}

// ─── Fuzzy matching helpers ─────────────────────────────────────────────────

function normalizeTitle(title: string): string {
    return title
        .toLowerCase()
        .replace(/[^a-z0-9\s]/g, "") // remove punctuation
        .replace(/\s+/g, " ")
        .trim();
}

function calculateRelevance(query: string, title: string, author: string): number {
    const normQuery = normalizeTitle(query);
    const normTitle = normalizeTitle(title);
    const normAuthor = normalizeTitle(author);

    // Exact match
    if (normTitle === normQuery) return 100;

    // Title starts with query
    if (normTitle.startsWith(normQuery)) return 90;

    // Query starts with title (user typed more than the title)
    if (normQuery.startsWith(normTitle)) return 85;

    // Title contains query
    if (normTitle.includes(normQuery)) return 75;

    // Query contains title
    if (normQuery.includes(normTitle)) return 70;

    // Author match
    if (normAuthor.includes(normQuery)) return 60;

    // Word-level matching (excluding stop words)
    const stopWords = new Set(["the", "a", "an", "and", "or", "of", "in", "on", "at", "to", "by", "for", "is", "it", "its"]);
    const queryWords = normQuery.split(" ").filter((w) => w.length > 1 && !stopWords.has(w));
    const titleWords = normTitle.split(" ").filter((w) => w.length > 1 && !stopWords.has(w));

    if (queryWords.length === 0) return 0;

    const matchingWords = queryWords.filter((w) =>
        titleWords.some((tw) => tw === w || (w.length >= 4 && (tw.includes(w) || w.includes(tw))))
    );
    const wordScore = (matchingWords.length / queryWords.length) * 50;
    if (wordScore >= 40) return wordScore;

    return 0;
}

// ─── Load data ──────────────────────────────────────────────────────────────

let cachedData: RedditData | null = null;

function loadRedditData(): RedditData | null {
    if (cachedData) return cachedData;

    const dataPath = path.join(process.cwd(), "data", "reddit_books.json");
    try {
        const raw = fs.readFileSync(dataPath, "utf-8");
        cachedData = JSON.parse(raw) as RedditData;
        return cachedData;
    } catch {
        console.error("Failed to load reddit_books.json");
        return null;
    }
}

// ─── Search endpoint ────────────────────────────────────────────────────────

export async function GET(request: NextRequest) {
    const { searchParams } = new URL(request.url);
    const query = searchParams.get("q")?.trim() || "";

    const data = loadRedditData();
    if (!data) {
        return NextResponse.json({ error: "Failed to load book data" }, { status: 500 });
    }

    // Filter out the wiki meta-entry
    const allBooks = data.books.filter(
        (b) => b.title !== "Here is the list of authors previously read."
    );

    let results: SearchResult[];

    if (query.length < 2) {
        // No query: return ALL books (sorted alphabetically by title)
        results = allBooks
            .map((book) => ({
                title: book.title,
                author: book.author,
                category: book.category,
                month: book.month,
                discussion_url: book.discussion_url,
                source: "reddit_wiki" as const,
                verified: true,
                relevance_score: 50,
            }))
            .sort((a, b) => a.title.localeCompare(b.title));
    } else {
        // Query provided: fuzzy search and rank
        results = [];
        for (const book of allBooks) {
            const score = calculateRelevance(query, book.title, book.author);
            if (score > 20) {
                results.push({
                    title: book.title,
                    author: book.author,
                    category: book.category,
                    month: book.month,
                    discussion_url: book.discussion_url,
                    source: "reddit_wiki",
                    verified: true,
                    relevance_score: score,
                });
            }
        }
        results.sort((a, b) => b.relevance_score - a.relevance_score);
    }

    // Generate fallback links
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
        data_freshness: data?.scraped_at || null,
    });
}
