# SF Apartment Hunt

Automated apartment monitoring system for San Francisco. Scrapes Craigslist and Zillow every 12 hours for 4–6 bedroom apartments under $10k/month across ten target neighborhoods. Deduplicates across sources, scores listings 0–100, deploys a static dashboard to GitHub Pages, and emails the group when new listings appear.

**Live Dashboard**: [senduri919.github.io/apartment-hunt](https://senduri919.github.io/apartment-hunt)

## Search Criteria

| Parameter | Value |
|-----------|-------|
| Bedrooms | 4–6 |
| Bathrooms | 1+ minimum, 2+ preferred |
| Max Price | $10,000/month |
| Move-in | By October 31, 2026 |
| Neighborhoods | Mission District, Hayes Valley, NoPa, Financial District, Nob Hill, SoMa, Noe Valley, Potrero Hill, Mission Dolores, Dolores Heights |

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                   GitHub Actions Cron                     │
│                  (every 12h + manual)                     │
└────────────────────────┬─────────────────────────────────┘
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
   ┌────────────┐ ┌────────────┐ ┌────────────┐
   │ Craigslist │ │   Zillow   │ │   Zumper   │
   │  (RSS +    │ │  (Apify    │ │  (Apify    │
   │   scrape)  │ │  scraper)  │ │  scraper)  │
   └─────┬──────┘ └─────┬──────┘ └─────┬──────┘
         │              │              │
         └──────────────┼──────────────┘
                        ▼
              ┌──────────────────┐
              │    Processor     │
              │  • Deduplicate   │
              │  • Merge sources │
              │  • Extract feat. │
              │  • Score 0–100   │
              └────────┬─────────┘
                       │
              ┌────────┼────────┐
              ▼        ▼        ▼
        ┌──────────┐ ┌────┐ ┌──────────┐
        │  Static  │ │JSON│ │  Email   │
        │   Site   │ │data│ │  Notifs  │
        │ (Pages)  │ │    │ │ (Resend) │
        └──────────┘ └────┘ └──────────┘
```

### Pipeline Steps

1. **Collect** — Each enabled collector scrapes its source for listings matching the search criteria. Craigslist uses its RSS feed with HTML fallback for enrichment. Zillow and Zumper run Apify actors that scrape the respective sites and return structured JSON.

2. **Process** — Raw listings are deduplicated against existing data using a combination of exact ID matching and fuzzy address matching (>85% similarity + same price/beds). When a listing appears on multiple sources, the higher-priority source wins (Zillow > Zumper > Craigslist) but missing fields are backfilled from the lower-priority source. Listings not seen in the current run are marked inactive.

3. **Extract Features** — Regex-based extraction pulls structured data from free-text descriptions: in-unit laundry, parking type, pet policy, outdoor space, building style, nearest transit, lease terms, and move-in costs.

4. **Score** — Each listing is scored 0–100 using weighted criteria (see Scoring below). The score determines sort order on the dashboard and the notification threshold.

5. **Generate** — A static HTML dashboard is generated via Jinja2 templates and deployed to GitHub Pages.

6. **Notify** — If new listings were found, an email is sent to the group via Resend with the top 5 by score.

## Data Sources

| Source | Method | Cost | Notes |
|--------|--------|------|-------|
| Craigslist | RSS feed + HTML scraping | Free | Primary source. Parses RSS entries, then fetches each listing page to extract bathrooms, sqft, images, coordinates, and full description. Rate-limited with random delays. |
| Zillow | Apify actor `maxcopell~zillow-scraper` | ~$0.002/result | Scrapes Zillow search results for individual rental listings. Returns zpid, price, beds, baths, coordinates, images. |
| Zumper | Apify actor `benthepythondev~zumper-rental-scraper` | ~$0.002/result | Falls back to `stealth_mode~zumper-property-search-scraper` if the primary actor requires payment. |
| RentCast | REST API | 50 req/month free | Currently disabled — subscription inactive. |
| Redfin | RapidAPI | Varies | Currently disabled. |

## Neighborhood Detection

Listings are assigned to neighborhoods using a three-tier system (checked in order):

1. **Keyword matching** — Address and description text is checked against neighborhood-specific keywords (street names, landmarks, colloquial names). More specific neighborhoods (Dolores Heights, Mission Dolores) are checked before broader ones (Mission District) to avoid misclassification in overlapping areas.

2. **Zip code mapping** — Only used for unambiguous zips: Mission District (94110), Hayes Valley (94102), NoPa (94117, 94115), Financial District (94104, 94111), Noe Valley (94131). Shared zips like 94114 (Castro/Noe Valley/Dolores Heights/Mission Dolores) and 94107 (SoMa/Potrero Hill) are intentionally skipped at this tier — keyword or coordinate matching handles them.

3. **Coordinate bounding boxes** — If the listing has lat/lng, it's checked against bounding boxes for each neighborhood. Boxes are ordered smallest-first so that specific neighborhoods (Dolores Heights, Mission Dolores) take priority over larger overlapping ones (Mission District).

Listings that pass the zip code filter but don't get a confirmed neighborhood still appear in results — they just score lower on the neighborhood dimension (10–20 points instead of 100).

## Scoring

Listings are scored 0–100 with configurable weights. Each dimension produces a 0–100 sub-score, and the final score is the weighted average.

| Criterion | Weight | How It Scores |
|-----------|--------|---------------|
| Neighborhood | 25 | Target neighborhood = 100, other named = 20, unknown = 10 |
| Bathrooms | 15 | 2+ = 100, 1.5 = 60, 1 = 30, <1 = 0 |
| Square footage | 12 | Linear scale: 1,000 sqft = 0, 2,500+ sqft = 100, unknown = 30 |
| In-unit laundry | 10 | Yes = 100, No = 0, unknown = 30 |
| Building type | 8 | Modern/new = 100, renovated = 70, victorian = 50, unknown = 40 |
| Transit | 8 | Near BART = 85, near Muni = 70, mentioned = 60, unknown = 50 |
| Move-in timing | 6 | Available now = 100, by deadline = 70–100, after deadline = penalized |
| Parking | 6 | Garage = 100, lot = 70, street = 40, none = 0, unknown = 20 |
| Price | 5 | $4k or less = 100, $10k = 0, linear between |
| Pets | 5 | Pet-friendly = 100, cats only = 50, no = 0, unknown = 30 |
| Outdoor space | 5 | Yes = 100, No = 0, unknown = 20 |
| Lease flexibility | 3 | Month-to-month = 100, 1 year = 60, 2 year = 20, unknown = 50 |

Edit `config.yaml` to adjust weights or search parameters.

## Setup

### 1. Fork and Configure

Fork this repo, then go to **Settings > Pages** and set Source to **GitHub Actions**.

### 2. Add GitHub Secrets

Go to **Settings > Secrets and variables > Actions** and add:

| Secret | Required | Source |
|--------|----------|--------|
| `APIFY_API_KEY` | Yes (for Zillow + Zumper) | [apify.com](https://apify.com) — free tier: ~$5/month credit |
| `RESEND_API_KEY` | Yes (for email notifications) | [resend.com](https://resend.com) — free: 100 emails/day |
| `RENTCAST_API_KEY` | No (collector disabled) | [rentcast.io/api](https://rentcast.io/api) |
| `RAPIDAPI_KEY` | No (collector disabled) | [rapidapi.com](https://rapidapi.com) |

### 3. Configure Search

Edit `config.yaml` to set neighborhoods, price range, bedroom count, scoring weights, and notification recipients.

### 4. Run

The workflow runs automatically at ~8am and ~8pm UTC daily. To trigger manually: **Actions > Apartment Monitor > Run workflow**.

## Local Development

```bash
pip install -r requirements.txt

# Set API keys
cp .env.example .env
# Edit .env with your keys
source .env

# Run the full pipeline
python main.py run

# Or run individual steps
python main.py collect    # scrape all sources
python main.py process    # deduplicate, merge, score
python main.py generate   # build static site
python main.py notify     # send email if new listings

# View the site
open site/index.html
```

## Dashboard Features

- **Sorting** — By score, price, date, or bedrooms
- **Filtering** — By neighborhood, source, or status
- **Search** — Free-text search across address and keywords
- **Voting** — Thumbs up/down on listings
- **Status tracking** — Mark listings as New, Contacted, Toured, Favorite, or Rejected
- **Notes** — Add notes to individual listings
- **Score breakdown** — Expand any listing to see how each scoring dimension contributed

Collaboration data persists in `data/collaboration.json`.

## Project Structure

```
├── main.py                    CLI entry point (collect/process/generate/notify/run)
├── config.yaml                Search criteria, scoring weights, notification settings
├── .env.example               Template for local API keys
├── requirements.txt           Python dependencies
│
├── src/
│   ├── models.py              Listing dataclass + serialization
│   ├── config.py              YAML config loader + dataclasses
│   ├── feature_extractor.py   Regex-based feature extraction from descriptions
│   ├── scorer.py              Weighted 0–100 scoring (12 dimensions)
│   ├── processor.py           Deduplication, fuzzy matching, merge, orchestration
│   ├── notifier.py            Email notifications via Resend
│   ├── site_generator.py      Static site generation via Jinja2
│   └── collectors/
│       ├── base.py            Abstract base with API budget tracking
│       ├── craigslist.py      RSS feed + HTML scraping
│       ├── zillow.py          Apify actor (maxcopell~zillow-scraper)
│       ├── zumper.py          Apify actor (benthepythondev~zumper-rental-scraper)
│       ├── rentcast.py        REST API (disabled)
│       └── redfin.py          RapidAPI (disabled)
│
├── templates/
│   ├── index.html             Dashboard Jinja2 template
│   ├── email.html             Notification email template
│   └── static/                CSS and assets
│
├── data/
│   ├── listings.json          All listings (active + inactive history)
│   ├── active.json            Currently active listings only
│   ├── raw_latest.json        Raw collector output from most recent run
│   ├── collaboration.json     Votes, notes, and status from the dashboard
│   ├── api_usage.json         Monthly API call counts per collector
│   └── runs.json              Run log (last 200 runs)
│
├── site/                      Generated static site (deployed to GitHub Pages)
│
└── .github/workflows/
    └── monitor.yml            GitHub Actions workflow (cron + manual trigger)
```
