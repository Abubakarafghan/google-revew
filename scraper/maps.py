"""Google Maps review scraper — no official API, browser automation only."""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any
from urllib.parse import quote_plus, urlparse

from playwright.sync_api import sync_playwright, Page, Browser, TimeoutError as PlaywrightTimeout


@dataclass
class PlaceMatch:
    name: str
    address: str
    rating: str
    review_count: str
    maps_url: str
    website: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Review:
    author: str
    rating: float
    date: str
    text: str
    avatar_initial: str = ""
    profile_photo: str = ""
    photos: list[str] | None = None
    owner_response: str = ""
    owner_response_date: str = ""
    reviewer_meta: str = ""

    def __post_init__(self) -> None:
        if self.photos is None:
            self.photos = []

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PlaceDetails:
    name: str
    rating: str
    review_count: str
    address: str
    website: str
    maps_url: str
    reviews: list[Review]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data


def _normalize_url(url: str) -> str:
    if not url:
        return ""
    url = url.strip().lower()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    host = parsed.netloc.removeprefix("www.")
    path = parsed.path.rstrip("/")
    return f"{host}{path}"


def _urls_match(a: str, b: str) -> bool:
    na, nb = _normalize_url(a), _normalize_url(b)
    if not na or not nb:
        return False
    return na == nb or na in nb or nb in na


def _dismiss_consent(page: Page) -> None:
    selectors = [
        'button:has-text("Accept all")',
        'button:has-text("Accept All")',
        'button:has-text("I agree")',
        'button:has-text("Agree")',
        'button[aria-label="Accept all"]',
        'form[action*="consent"] button',
        'button:has-text("Alle akzeptieren")',
    ]
    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=1500):
                btn.click(timeout=2000)
                page.wait_for_timeout(800)
                return
        except Exception:
            continue


def _launch_browser(p) -> Browser:
    return p.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ],
    )


def _new_page(browser: Browser) -> Page:
    context = browser.new_context(
        viewport={"width": 1600, "height": 1000},
        locale="en-US",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        ),
    )
    page = context.new_page()
    # Reduce automation fingerprint so Maps doesn't stay on "limited view"
    page.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
    )
    return page


def _force_reviews_url(maps_url: str) -> str:
    """Rewrite a Maps place URL so the reviews panel opens (!9m1!1b1)."""
    if not maps_url:
        return maps_url
    if "!9m1!1b1" in maps_url:
        return maps_url

    # Prefer injecting into an existing !4m…!3m… data blob
    m = re.search(r"(!4m\d+!3m\d+!1s0x[0-9a-fA-F]+:0x[0-9a-fA-F]+)", maps_url)
    if m:
        anchor = m.group(1)
        # Replace compact place data with reviews-enabled variant when possible
        rebuilt = re.sub(
            r"!4m\d+!3m\d+(!1s0x[0-9a-fA-F]+:0x[0-9a-fA-F]+)(!8m2!3d[^!]+!4d[^!]+)?",
            r"!4m8!3m7\1!8m2!3d0!4d0!9m1!1b1",
            maps_url,
            count=1,
        )
        # If coords were zeroed, keep original coords if present
        coords = re.search(r"!8m2(!3d[^!]+!4d[^!]+)", maps_url)
        if coords and "!3d0!4d0" in rebuilt:
            rebuilt = rebuilt.replace("!3d0!4d0", coords.group(1), 1)
        if "!9m1!1b1" in rebuilt:
            sep = "&" if "?" in rebuilt else "?"
            if "hl=" not in rebuilt:
                rebuilt = f"{rebuilt}{sep}hl=en"
            return rebuilt

    # Fallback: append reviews flag before query string
    if "/maps/place/" in maps_url:
        base, _, query = maps_url.partition("?")
        if "/data=" in base:
            base = base + "!9m1!1b1"
        else:
            # Extract feature id if present in URL
            fid = re.search(r"(0x[0-9a-fA-F]+:0x[0-9a-fA-F]+)", maps_url)
            if fid:
                base = re.sub(
                    r"/data=[^/]*",
                    f"/data=!4m6!3m5!1s{fid.group(1)}!9m1!1b1",
                    base,
                )
                if "/data=" not in base:
                    base = base.rstrip("/") + f"/data=!4m6!3m5!1s{fid.group(1)}!9m1!1b1"
        out = base + (("?" + query) if query else "")
        sep = "&" if "?" in out else "?"
        if "hl=" not in out:
            out = f"{out}{sep}hl=en"
        return out
    return maps_url


def search_places(business_name: str, website: str = "", max_results: int = 5) -> list[PlaceMatch]:
    """Search Google Maps and return top place matches."""
    query = business_name.strip()
    if not query:
        return []

    url = f"https://www.google.com/maps/search/{quote_plus(query)}"
    matches: list[PlaceMatch] = []

    with sync_playwright() as p:
        browser = _launch_browser(p)
        page = _new_page(browser)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            _dismiss_consent(page)
            page.wait_for_timeout(2500)

            # If Maps jumped straight to a single place panel
            if _is_place_panel(page):
                place = _extract_place_from_panel(page)
                if place:
                    matches.append(place)
            else:
                matches = _extract_search_results(page, max_results)

            # Enrich websites for matching (open each briefly if missing)
            for i, m in enumerate(matches):
                if not m.website and m.maps_url:
                    try:
                        matches[i] = _enrich_place_website(browser, m)
                    except Exception:
                        pass

            if website:
                preferred = [m for m in matches if _urls_match(m.website, website)]
                if preferred:
                    rest = [m for m in matches if m not in preferred]
                    matches = preferred + rest
        finally:
            browser.close()

    return matches


def fetch_reviews(maps_url: str, max_reviews: int = 200) -> PlaceDetails:
    """Open a Maps place URL and scrape as many reviews as possible."""
    reviews_url = _force_reviews_url(maps_url)
    with sync_playwright() as p:
        browser = _launch_browser(p)
        page = _new_page(browser)
        try:
            details: PlaceMatch | None = None

            # First open the normal place page for name / rating / website
            page.goto(maps_url, wait_until="domcontentloaded", timeout=60000)
            _dismiss_consent(page)
            page.wait_for_timeout(2200)
            details = _extract_place_from_panel(page)

            # Then force the reviews panel (avoids Maps "limited view" with no Reviews tab)
            page.goto(reviews_url, wait_until="domcontentloaded", timeout=60000)
            _dismiss_consent(page)
            page.wait_for_timeout(3500)

            if page.locator("div[data-review-id]").count() == 0:
                _open_reviews_tab(page)
                page.wait_for_timeout(2000)

            if page.locator("div[data-review-id]").count() == 0:
                _open_reviews_tab(page)
                page.wait_for_timeout(2000)

            # Refresh metadata from reviews view when available
            panel = _extract_place_from_panel(page)
            if panel:
                if details:
                    details.name = details.name or panel.name
                    details.rating = panel.rating or details.rating
                    details.review_count = panel.review_count or details.review_count
                    details.address = details.address or panel.address
                    details.website = details.website or panel.website
                    details.maps_url = page.url
                else:
                    details = panel

            if not details:
                details = PlaceMatch(
                    name=_name_from_maps_url(maps_url) or "Unknown business",
                    address="",
                    rating="",
                    review_count="",
                    maps_url=page.url,
                )
            elif not details.name or details.name == "Unknown business":
                details.name = _name_from_maps_url(maps_url) or details.name

            if not details.review_count:
                details.review_count = _extract_review_count_from_page(page)

            reviews = _scrape_review_cards(page, max_reviews=max_reviews)
            _embed_review_images(page, reviews)

            return PlaceDetails(
                name=details.name,
                rating=details.rating,
                review_count=details.review_count or str(len(reviews)),
                address=details.address,
                website=details.website,
                maps_url=page.url,
                reviews=reviews,
            )
        finally:
            browser.close()


def _name_from_maps_url(maps_url: str) -> str:
    m = re.search(r"/maps/place/([^/@]+)", maps_url)
    if not m:
        return ""
    from urllib.parse import unquote_plus

    return unquote_plus(m.group(1)).replace("+", " ").strip()


def _extract_review_count_from_page(page: Page) -> str:
    try:
        text = page.locator('div[role="main"]').inner_text(timeout=3000)
    except Exception:
        try:
            text = page.inner_text("body")
        except Exception:
            return ""
    m = re.search(r"([\d,]+)\s+reviews?\b", text, re.I)
    return m.group(1) if m else ""


def _is_place_panel(page: Page) -> bool:
    try:
        # Place title heading or reviews button typically present
        if page.locator('h1[class*="fontHeadline"]').count() > 0:
            return True
        if page.locator('button[aria-label*="Reviews"]').count() > 0:
            return True
        if page.locator('button[aria-label*="reviews"]').count() > 0:
            return True
    except Exception:
        pass
    return False


def _text_or_empty(locator) -> str:
    try:
        if locator.count() == 0:
            return ""
        return (locator.first.inner_text(timeout=2000) or "").strip()
    except Exception:
        return ""


def _extract_place_from_panel(page: Page) -> PlaceMatch | None:
    name = ""
    for sel in ['h1.DUwDvf', 'h1[class*="fontHeadline"]', "h1"]:
        name = _text_or_empty(page.locator(sel))
        if name:
            break
    if not name:
        return None

    rating = ""
    review_count = ""
    try:
        rating_el = page.locator('div.F7nice span[aria-hidden="true"]').first
        if rating_el.count():
            rating = (rating_el.inner_text(timeout=1500) or "").strip()
    except Exception:
        pass

    try:
        star = page.locator('div.F7nice span[role="img"]').first
        if star.count():
            aria = star.get_attribute("aria-label") or ""
            rm = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*star", aria, re.I)
            if rm:
                rating = rating or rm.group(1)
    except Exception:
        pass

    try:
        count_el = page.locator('div.F7nice span[aria-label*="review"]').first
        if count_el.count():
            label = count_el.get_attribute("aria-label") or ""
            m = re.search(r"([\d,]+)", label)
            if m:
                review_count = m.group(1)
        if not review_count:
            raw = _text_or_empty(page.locator("div.F7nice"))
            m = re.search(r"\(([\d,]+)\)", raw)
            if m:
                review_count = m.group(1)
        if not review_count:
            review_count = _extract_review_count_from_page(page)
    except Exception:
        pass

    address = ""
    for sel in [
        'button[data-item-id="address"]',
        'button[data-item-id*="address"]',
        'button[aria-label*="Address"]',
    ]:
        address = _text_or_empty(page.locator(sel))
        if address:
            address = re.sub(r"^Address:\s*", "", address, flags=re.I).strip()
            # Strip leading icon / private-use unicode glyphs
            address = re.sub(r"^[\ue000-\uf8ff\W]+", "", address).strip()
            break

    website = ""
    for sel in [
        'a[data-item-id="authority"]',
        'a[aria-label*="Website"]',
        'a[data-item-id*="authority"]',
    ]:
        try:
            link = page.locator(sel).first
            if link.count():
                website = link.get_attribute("href") or ""
                if website:
                    break
        except Exception:
            continue

    return PlaceMatch(
        name=name,
        address=address,
        rating=rating,
        review_count=review_count,
        maps_url=page.url,
        website=website,
    )


def _extract_search_results(page: Page, max_results: int) -> list[PlaceMatch]:
    matches: list[PlaceMatch] = []

    # Wait for feed results
    try:
        page.wait_for_selector('div[role="feed"]', timeout=10000)
    except PlaywrightTimeout:
        # Might already be on a place
        place = _extract_place_from_panel(page)
        return [place] if place else []

    articles = page.locator('div[role="feed"] > div > div[jsaction]')
    # Fallback broader selector
    if articles.count() == 0:
        articles = page.locator('a[href*="/maps/place/"]')

    seen_urls: set[str] = set()
    count = articles.count()
    for i in range(min(count, max_results * 3)):
        if len(matches) >= max_results:
            break
        try:
            item = articles.nth(i)
            # Prefer clickable place link
            link = item.locator('a[href*="/maps/place/"]').first
            if link.count() == 0 and item.evaluate("el => el.tagName") == "A":
                link = item

            href = ""
            if link.count():
                href = link.get_attribute("href") or ""
            if not href or href in seen_urls:
                continue
            if "/maps/place/" not in href:
                continue
            seen_urls.add(href)

            name = ""
            for sel in [".qBF1Pd", ".fontHeadlineSmall", "div.fontHeadlineSmall"]:
                name = _text_or_empty(item.locator(sel))
                if name:
                    break
            if not name:
                aria = link.get_attribute("aria-label") or ""
                name = aria.split(",")[0].strip() if aria else ""
            if not name:
                continue

            rating = ""
            review_count = ""
            try:
                rating = _text_or_empty(item.locator('span[role="img"]').first)
                # Sometimes rating is in aria-label like "4.5 stars 120 reviews"
                aria = item.locator('span[role="img"]').first.get_attribute("aria-label") or ""
                rm = re.search(r"([0-9.]+)\s*star", aria, re.I)
                if rm:
                    rating = rm.group(1)
                cm = re.search(r"([\d,]+)\s*review", aria, re.I)
                if cm:
                    review_count = cm.group(1)
            except Exception:
                pass

            address = ""
            try:
                # Secondary text lines often include category / address
                lines = item.locator(".W4Efsd").all_inner_texts()
                if lines:
                    address = " · ".join(t.strip() for t in lines if t.strip())[:180]
            except Exception:
                pass

            full_url = href if href.startswith("http") else f"https://www.google.com{href}"
            matches.append(
                PlaceMatch(
                    name=name,
                    address=address,
                    rating=rating,
                    review_count=review_count,
                    maps_url=full_url,
                    website="",
                )
            )
        except Exception:
            continue

    return matches


def _enrich_place_website(browser: Browser, place: PlaceMatch) -> PlaceMatch:
    page = _new_page(browser)
    try:
        page.goto(place.maps_url, wait_until="domcontentloaded", timeout=45000)
        _dismiss_consent(page)
        page.wait_for_timeout(1800)
        enriched = _extract_place_from_panel(page)
        if enriched:
            place.website = enriched.website or place.website
            place.address = enriched.address or place.address
            place.rating = enriched.rating or place.rating
            place.review_count = enriched.review_count or place.review_count
            place.maps_url = page.url or place.maps_url
    finally:
        page.context.close()
    return place


def _open_reviews_tab(page: Page) -> None:
    candidates = [
        'button[aria-label*="Reviews for"]',
        'button[aria-label*="reviews"]',
        'button[role="tab"]:has-text("Reviews")',
        'button:has-text("Reviews")',
        'button[aria-label*="Reviews"]',
        'button:has-text("reviews")',
    ]
    for sel in candidates:
        try:
            btn = page.locator(sel).first
            if btn.count() and btn.is_visible(timeout=1500):
                btn.click(timeout=3000)
                page.wait_for_timeout(1500)
                return
        except Exception:
            continue

    # Fallback: click rating summary which often opens reviews
    for sel in ["div.F7nice", 'span[aria-label*="stars"]', 'button[aria-label*="stars"]']:
        try:
            rating_btn = page.locator(sel).first
            if rating_btn.count() and rating_btn.is_visible(timeout=1000):
                rating_btn.click(timeout=3000)
                page.wait_for_timeout(1500)
                if page.locator("div[data-review-id]").count() > 0:
                    return
        except Exception:
            continue


def _find_reviews_scroll_container(page: Page):
    selectors = [
        'div[role="main"] div.m6QErb.DxyBCb.kA9KIf.dS8AEf',
        "div.m6QErb.DxyBCb.kA9KIf.dS8AEf",
        'div[role="main"] div.m6QErb.DxyBCb',
        "div.m6QErb.DxyBCb",
        'div[role="main"] div[tabindex="-1"]',
    ]
    for sel in selectors:
        loc = page.locator(sel).first
        try:
            if loc.count() and loc.is_visible(timeout=1000):
                return loc
        except Exception:
            continue
    return page.locator('div[role="main"]').first


def _url_to_data_uri(page: Page, url: str) -> str:
    """Download an image through the browser context so it always displays in the app."""
    if not url or url.startswith("data:"):
        return url
    try:
        resp = page.context.request.get(url, timeout=20000)
        if not resp.ok:
            return url
        body = resp.body()
        if not body or len(body) > 2_500_000:
            return url
        import base64

        ctype = resp.headers.get("content-type") or "image/jpeg"
        if ";" in ctype:
            ctype = ctype.split(";", 1)[0].strip()
        if not ctype.startswith("image/"):
            ctype = "image/jpeg"
        return f"data:{ctype};base64,{base64.b64encode(body).decode('ascii')}"
    except Exception:
        return url


def _embed_review_images(page: Page, reviews: list[Review]) -> None:
    """Inline images as data URIs so the Streamlit iframe can display them."""
    seen: dict[str, str] = {}

    def embed(url: str) -> str:
        if not url:
            return ""
        if url not in seen:
            seen[url] = _url_to_data_uri(page, url)
        return seen[url]

    for review in reviews:
        if review.profile_photo:
            review.profile_photo = embed(review.profile_photo)
        # Keep photo count reasonable for UI payload size
        review.photos = [embed(photo) for photo in (review.photos or [])[:6]]


def _upgrade_image_url(url: str, size: int = 400) -> str:
    """Bump Google usercontent thumbnails to a sharper size."""
    if not url:
        return ""
    url = url.strip()
    # Avatar-style: ...=w36-h36-p-rp-mo-br100
    url = re.sub(r"=w\d+-h\d+", f"=w{size}-h{size}", url)
    # Photo thumbs often end with =w300-h300-p-k-no or =s0
    url = re.sub(r"=w\d+(?:-h\d+)?(?:-[a-z0-9-]+)*$", f"=w{size}-h{size}-p-k-no", url)
    return url


def _extract_bg_urls(card) -> list[str]:
    try:
        urls = card.evaluate(
            """el => {
              const out = [];
              const seen = new Set();
              for (const node of el.querySelectorAll('button.Tya61d, div.KtCyie button, button[aria-label*="Photo"]')) {
                const bg = getComputedStyle(node).backgroundImage || '';
                const m = bg.match(/url\\(["']?(.*?)["']?\\)/);
                if (m && m[1] && !seen.has(m[1])) {
                  seen.add(m[1]);
                  out.push(m[1]);
                }
              }
              return out;
            }"""
        )
        return [_upgrade_image_url(u, 600) for u in (urls or []) if u]
    except Exception:
        return []


def _expand_card_text(card, page: Page) -> None:
    try:
        mores = card.locator(
            'button:has-text("More"), button[aria-label*="See more"], button[aria-label*="More"]'
        )
        count = min(mores.count(), 4)
        for i in range(count):
            btn = mores.nth(i)
            try:
                if btn.is_visible(timeout=250):
                    btn.click(timeout=800)
                    page.wait_for_timeout(180)
            except Exception:
                continue
    except Exception:
        pass


def _parse_owner_response(card) -> tuple[str, str]:
    """Return (owner_response_text, owner_response_date)."""
    try:
        block = card.locator("div.CDe7pd").first
        if block.count() == 0:
            return "", ""
        raw = (block.inner_text(timeout=1500) or "").strip()
        if not raw:
            return "", ""
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        date = ""
        text_lines: list[str] = []
        for ln in lines:
            if re.match(r"^Response from the owner", ln, re.I):
                # "Response from the owner 3 weeks ago"
                m = re.search(r"Response from the owner\s*(.*)$", ln, re.I)
                date = (m.group(1).strip() if m else "").strip()
                continue
            text_lines.append(ln)
        text = "\n".join(text_lines).strip()
        # Prefer dedicated review text node inside owner block if present
        try:
            owner_text = _text_or_empty(block.locator("span.wiI7pd"))
            if owner_text:
                text = owner_text
        except Exception:
            pass
        return text, date
    except Exception:
        return "", ""


def _scrape_review_cards(page: Page, max_reviews: int = 200) -> list[Review]:
    """Scroll the reviews panel, expand text, then extract everything in one JS pass."""
    scroll = _find_reviews_scroll_container(page)
    last_count = 0
    stagnant = 0

    for _ in range(100):
        try:
            count = page.locator("div.jftiEf[data-review-id], div[data-review-id]").count()
        except Exception:
            count = 0
        try:
            scroll.evaluate("el => { el.scrollTop = el.scrollHeight; }")
        except Exception:
            page.mouse.wheel(0, 2600)
        page.wait_for_timeout(900)
        if count <= last_count:
            stagnant += 1
        else:
            stagnant = 0
            last_count = count
        if stagnant >= 6 or count >= max_reviews * 3:
            break

    # Expand every "More" so full review + owner reply text is visible
    try:
        page.evaluate(
            """() => {
              const buttons = [...document.querySelectorAll('button')];
              for (const b of buttons) {
                const label = (b.innerText || b.getAttribute('aria-label') || '').trim();
                if (/^More$/i.test(label) || /see more/i.test(label)) {
                  try { b.click(); } catch (e) {}
                }
              }
            }"""
        )
        page.wait_for_timeout(800)
    except Exception:
        pass

    raw = page.evaluate(
        """() => {
          const cards = [...document.querySelectorAll('div.jftiEf[data-review-id], div[data-review-id]')]
            .filter(c => !(c.parentElement && c.parentElement.closest('[data-review-id]')));

          const bgUrl = (el) => {
            const bg = getComputedStyle(el).backgroundImage || '';
            const m = bg.match(/url\\(["']?(.*?)["']?\\)/);
            return m ? m[1] : '';
          };

          const upgrade = (url, size) => {
            if (!url) return '';
            return url
              .replace(/=w\\d+-h\\d+/g, `=w${size}-h${size}`)
              .replace(/=w\\d+(?:-h\\d+)?(?:-[a-z0-9-]+)*$/i, `=w${size}-h${size}-p-k-no`);
          };

          return cards.map(card => {
            const author = (card.querySelector('div.d4r55')?.innerText || '').trim() || 'Anonymous';
            const stars = card.querySelector('span[role="img"][aria-label*="star"], span[role="img"]');
            const aria = stars?.getAttribute('aria-label') || '';
            const rm = aria.match(/([0-9]+(?:\\.[0-9]+)?)/);
            const rating = rm ? parseFloat(rm[1]) : 0;
            const date = (card.querySelector('span.rsqaWe, span.x5LiIe')?.innerText || '').trim();

            let text = '';
            for (const node of card.querySelectorAll('span.wiI7pd')) {
              if (!node.closest('.CDe7pd')) {
                text = (node.innerText || '').trim();
                if (text) break;
              }
            }
            if (!text) {
              text = (card.querySelector('div.MyEned span')?.innerText || '').trim();
            }

            const avatar = card.querySelector('img.NBa7we')?.getAttribute('src') || '';
            const meta = (card.querySelector('div.RfnDt')?.innerText || '').trim();

            const photos = [];
            const seen = new Set();
            for (const btn of card.querySelectorAll('button.Tya61d, div.KtCyie button, button[aria-label*="Photo"]')) {
              const u = bgUrl(btn);
              if (u && !seen.has(u)) {
                seen.add(u);
                photos.push(upgrade(u, 600));
              }
            }

            let owner_response = '';
            let owner_response_date = '';
            const owner = card.querySelector('div.CDe7pd');
            if (owner) {
              const lines = (owner.innerText || '').split('\\n').map(s => s.trim()).filter(Boolean);
              for (const ln of lines) {
                const m = ln.match(/^Response from the owner\\s*(.*)$/i);
                if (m) { owner_response_date = (m[1] || '').trim(); continue; }
              }
              const ownerText = owner.querySelector('span.wiI7pd');
              owner_response = (ownerText?.innerText || lines.filter(l => !/^Response from the owner/i.test(l)).join('\\n')).trim();
            }

            return {
              author,
              rating,
              date,
              text,
              profile_photo: upgrade(avatar, 128),
              photos,
              owner_response,
              owner_response_date,
              reviewer_meta: /review/i.test(meta) ? meta : '',
            };
          });
        }"""
    )

    reviews: list[Review] = []
    seen: set[str] = set()
    for item in raw or []:
        if len(reviews) >= max_reviews:
            break
        author = (item.get("author") or "Anonymous").strip()
        if author.lower().startswith("response from the owner"):
            continue
        text = (item.get("text") or "").strip()
        date = (item.get("date") or "").strip()
        key = f"{author}|{date}|{text[:80]}"
        if key in seen:
            continue
        seen.add(key)
        reviews.append(
            Review(
                author=author,
                rating=float(item.get("rating") or 0),
                date=date,
                text=text,
                avatar_initial=(author[:1] or "?").upper(),
                profile_photo=item.get("profile_photo") or "",
                photos=list(item.get("photos") or []),
                owner_response=item.get("owner_response") or "",
                owner_response_date=item.get("owner_response_date") or "",
                reviewer_meta=item.get("reviewer_meta") or "",
            )
        )
    return reviews
