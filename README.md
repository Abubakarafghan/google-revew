
# google-revew
 This app is a Google Maps review scraper and analyzer built with Python and Streamlit. It helps users search for a business or location, collect public Google reviews, and view the extracted review data in a simple dashboard for quick analysis.

# Google Reviews Scraper

Local Python app: enter a business name (optional website), scrape Google Maps reviews (no API), show them in a Google-style responsive card grid.

## Features

- Business name search on Google Maps
- Optional website to auto-match the correct listing
- If multiple matches → pick from 2–5 results
- Loads reviews by scrolling the Maps reviews panel
- UI: header search + overall rating + review cards
- Responsive grid: **5 → 4 → 3 → 2 → 1** columns by screen size
- No CSV export, no Google API keys

## Setup (Fedora / Linux)

```bash
cd "/home/itsabu/Pictures/google revew"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

## Run

```bash
source .venv/bin/activate
streamlit run app.py
```

Open the URL Streamlit prints (usually http://localhost:8501).

## Notes

- First search can take 30–90 seconds while the browser loads Maps and scrolls reviews.
- Google may show a CAPTCHA or change page layout; if scraping fails, try again or be more specific with the business name + city.
- For personal / your-own-business use. Scraping can break when Google updates Maps.