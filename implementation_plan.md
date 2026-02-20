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

### [Backend/Scraper]

#### [NEW] [scraper/scrape_reddit_wiki.py](file:///d:/Hoai%20Anh/Aalto/Hobbies/Bookmate/scraper/scrape_reddit_wiki.py)

* **Function**: Scrapes the Reddit Wiki and populates `Books` table.
* **Key Logic**: Parses the "Month Year - Book Title - Link" format from the wiki.

#### [NEW] [scraper/main.py](file:///d:/Hoai%20Anh/Aalto/Hobbies/Bookmate/scraper/main.py)

* Orchestrator for scrapers.

### [Frontend]

#### [NEW] [app/page.tsx](file:///d:/Hoai%20Anh/Aalto/Hobbies/Bookmate/app/page.tsx)

* Main search UI.

#### [NEW] [app/api/search/route.ts](file:///d:/Hoai%20Anh/Aalto/Hobbies/Bookmate/app/api/search/route.ts)

* API handler that checks DB first, then (optional) live search.

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
