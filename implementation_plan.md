# Implementation Plan - Book Club Finder (Merged)

This project aims to create a web application where users can search for a book and find book clubs that are reading or have discussed that book. It prioritizes Reddit's r/bookclub archive while supporting other sources.

## Goal Description

Build a "Book Club Finder" web application that:

1. **Prioritizes Reddit:** Instantly checks `r/bookclub`'s "Previous Books" archive for matches.
2. **Aggregates Sources:** If not found in the archive, searches Reddit, Goodreads, and Bookclubs.com.
3. **Visualizes Data:** Displays results in a premium "Bento-box" style UI.
4. **Tracks Interest:** Analytics to track popular searches.

## User Review Required
>
> [!IMPORTANT]
> **Scraping Policy**: We will use polite scraping. The Reddit Wiki will be scraped periodically to build a local "fast lookup" database.
> **Tech Stack (Hybrid Pro)**:
>
> * **Frontend (Next.js)**: Best for high-performance, beautiful web UIs.
> * **Data Engine (Python)**: The industry standard for scraping and data analysis. "Smarter" handling of text processing.
> * **Database (PostgreSQL)**: Robust, scalable storage.

## Proposed Architecture

### 1. Database Schema (PostgreSQL)

* `Books`: Title, Author, ISBN, CoverImage, **RedditWikiLink** (Nullable - direct link if found in archive).
* `BookClubs`: Name, SourceURL, Platform (e.g., Reddit, Goodreads).
* `Discussions`: Link to specific discussion, Date, BookID, ClubID.
* `AnalyticsEvents`: EventType (Pageview, Search), Term, Timestamp.

### 2. Scraping Engine (Python)

Scripts to run periodically or on-demand:

* **[PRIORITY] Reddit Wiki Scraper**: Fetches `https://www.reddit.com/r/bookclub/wiki/previous/` to populate the `Books` table with verified discussion links.
* **On-Demand Fallback**:
  * **Reddit**: Search `r/bookclub` and `r/books`.
  * **Goodreads**: Search Groups/Discussions.
  * **Bookclubs.com**: Search active clubs.

### 3. Web Application (Next.js + Tailwind CSS)

#### Design System

* **Theme**: Dark Mode default (Deep Black/Charcoal).
* **Accent**: Neon Lime/Electric Green.
* **Layout**: "Bento-box" grid for results.
* **Typography**: Bold sans-serif (Inter/Outfit).
* **Shapes**: **SHARP corners** (0px border-radius). Strict rectangular aesthetics.
* **Iconography**: Minimalist SVG icons (Lucide React). **ABSOLUTELY NO EMOJIS**.

#### Animation Stack (The "Cool" Factor)

* **Smooth Scrolling**: `@studio-freight/lenis` for that premium, weighty scroll feel.
* **Scroll Triggers**: `GSAP` + `ScrollTrigger` for pinning and reveal effects.
* **Text Effects**: `Splitting.js` or `GSAP SplitText` for staggering character reveals on scroll.
* **Parallax**: Slight vertical parallax on images/cards using GSAP.

#### Frontend Architecture

* **Search Logic**:
    1. User types query.
    2. Check local DB (populated by Wiki Scraper).
    3. If match -> Show "verified" Reddit discussion card (highlighted/premium style).
    4. If no match -> Trigger on-demand search (or show "Search on X" links) and display fallback results.

### 4. Analytics

* Log searches to identify high-demand books that aren't yet in the database.

## Proposed Changes

### [NEW] `scraper/enrich_books.py`

A new script that acts as a post-processing step after scraping Reddit and Bookclubs:

1. It reads the raw JSON files (`reddit_books.json`, `bookclubs_com.json`).
2. It extracts every unique `(title, author)` pair (using basic string cleaning first).
3. For each unique pair, it calls the free **Google Books API** to retrieve canonical data.
4. It extracts:
   * **Canonical Title & Author** (To perfectly merge variants like "1984" and "1984 by George Orwell")
   * **Categories/Genres** (e.g., "Fiction", "Science Fiction", "Thriller")
   * **Page Count & Published Year** (Bonus metadata for filtering later)
5. It saves a new file `data/enriched_books.json` containing the deduplicated books grouped by canonical Google Books metadata, with an array of their associated clubs.

### [MODIFY] `src/app/api/search/route.ts`

Update the API to load `enriched_books.json` instead of the raw scraper files. Because the books are already perfectly grouped and enriched by the Python script, the Next.js API can be incredibly fast and simpler—it just needs to filter the pre-grouped data.

### [MODIFY] `src/app/page.tsx`

Update the frontend to display the new metadata (Genres, Page Count) next to the books, and potentially use the empty category pills container to filter by these newly extracted genres.

## Verification Plan

### Automated Tests

* **Wiki Parser Test**: Feed sample Wiki HTML, verify extracted Title/URL.
* **API Test**: Mock DB response, verify JSON output prioritizes Wiki result.

### Manual Verification

1. **Wiki Scrape**: Run `scrape_reddit_wiki.py`, check DB for entries like "Pride and Prejudice".
2. **Search Flow**:
    * Search "Pride and Prejudice" -> Expect immediate "Found in Archive" result.
    * Search "Unknown Book" -> Expect fallback search options/results.

## Deployment & Feedback Plan

### 1. Feedback Mechanism

We will add a "Give Feedback" link to the footer of the application.

* **Types**: Simple `mailto` link or external Form (e.g., Google Forms, Tally).
* **Location**: Footer of `src/app/page.tsx`.

### 2. Deployment (Vercel)

We will create a `DEPLOY.md` guide to help you put this on the internet using Vercel, which is the best platform for Next.js.

#### [NEW] [DEPLOY.md](file:///d:/Hoai%20Anh/Aalto/Hobbies/Bookmate/DEPLOY.md)

* Step-by-step guide to deploying on Vercel.
* Instructions for setting up environment variables.

#### [MODIFY] [src/app/page.tsx](file:///d:/Hoai%20Anh/Aalto/Hobbies/Bookmate/src/app/page.tsx)

* Add "Give Feedback" link in the footer.

---

## Phase 2: Book Details and Retention Improvements

The goal is to increase user retention by preventing immediate off-site redirects. Instead of linking off-site from the homepage, we will create an internal "Book Details" page where users can choose their next action: joining a book discussion or visiting Wikipedia for more context.

### Proposed Architecture Changes

#### [MODIFY] src/app/api/search/route.ts

- Update the `SearchResult` interface to include a `slug: string` property.
* Add a generated slug to search results: `const slug = normalize(book.canonical_title + " " + book.canonical_author).replace(/\s+/g, "-")`.

#### [NEW] src/app/api/book/[slug]/route.ts

- Create a new API route to fetch a single book by its slug parameter from `enriched_books.json`.
* Return the full `EnrichedBook` data or a 404 response.

#### [MODIFY] src/app/page.tsx

- Update the local `SearchResult` interface to include `slug: string`.
* Change the `app-book-row` link to point to `/book/${book.slug}` instead of the external URL.
* Remove `target="_blank"` to perform internal client-side navigation.

#### [NEW] src/app/book/[slug]/page.tsx

- Create the "Book Details" Next.js page.
* Fetch the book data from `/api/book/[slug]`.
* Display a visually rich layout containing: Book Cover, Title, Author, Description, Categories, and Page count.
* Add two primary Call-to-Action (CTA) buttons:
  1. **Enter Book Discussion**: Points to `book.clubs[0].discussion_url`.
  2. **Read on Wikipedia**: Points to `https://en.wikipedia.org/wiki/Special:Search?search=${encodeURIComponent(book.canonical_title + ' book')}`.

#### [MODIFY] src/app/globals.css

- Add styles for the new Book Details page, ensuring the aesthetic matches the sleek and responsive layout of the homepage.
