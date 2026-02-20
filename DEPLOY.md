# Deploying Bookmate to Vercel

## Prerequisites

- A [GitHub](https://github.com) account
- A [Vercel](https://vercel.com) account (free tier works)
- Your code pushed to a GitHub repository

## Step 1: Push to GitHub

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/bookmate.git
git push -u origin main
```

## Step 2: Deploy on Vercel

1. Go to [vercel.com/new](https://vercel.com/new)
2. Click **Import Git Repository**
3. Select your `bookmate` repository
4. Vercel auto-detects Next.js — leave defaults
5. Click **Deploy**

## Step 3: Custom Domain (Optional)

1. In Vercel dashboard, go to **Settings > Domains**
2. Add your custom domain
3. Update DNS records as instructed

## Environment Variables

Currently, Bookmate uses a local JSON file (`data/reddit_books.json`) for search data, so no environment variables are required for the basic deployment.

If you later add a PostgreSQL database, set:

| Variable | Description |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |

## Updating the Data

To refresh the book data:

```bash
cd scraper
python scrape_reddit_wiki.py
```

Then commit and push the updated `data/reddit_books.json`. Vercel will auto-redeploy.

## Notes

- The `data/reddit_books.json` file is bundled with the deployment
- The search API runs as a serverless function on Vercel
- Free tier supports ~100K requests/month
