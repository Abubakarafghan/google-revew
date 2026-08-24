"""Google Reviews viewer — search a business, see reviews in a Google-like card grid."""

from __future__ import annotations

import html
import importlib
import json
import subprocess
import sys
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

import scraper
import scraper.maps as maps_mod

# Always reload scraper modules so Streamlit picks up fixes without a full process restart
importlib.reload(maps_mod)
importlib.reload(scraper)
from scraper import search_places  # noqa: E402

ROOT = Path(__file__).resolve().parent
FETCH_SCRIPT = ROOT / "scraper" / "run_fetch.py"
CACHE_FILE = ROOT / ".last_reviews.json"

st.set_page_config(
    page_title="Google Reviews",
    page_icon="⭐",
    layout="wide",
    initial_sidebar_state="collapsed",
)

CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Google+Sans:wght@400;500;700&family=Roboto:wght@400;500;700&display=swap');

html, body, [class*="css"] {
  font-family: "Roboto", "Google Sans", system-ui, sans-serif;
}

/* Hide Streamlit chrome */
#MainMenu, footer, header { visibility: hidden; }
div[data-testid="stToolbar"] { display: none; }
.block-container {
  padding-top: 1.25rem;
  padding-bottom: 3rem;
  max-width: 1280px;
}

.gr-hero {
  background: linear-gradient(180deg, #e8f0fe 0%, #ffffff 70%);
  border-bottom: 1px solid #e0e3e7;
  margin: -1.25rem -1rem 1.5rem -1rem;
  padding: 1.75rem 1.25rem 1.5rem;
}

.gr-brand {
  font-size: 1.75rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: #202124;
  margin: 0 0 0.35rem 0;
}
.gr-brand span.g-blue { color: #4285F4; }
.gr-brand span.g-red { color: #EA4335; }
.gr-brand span.g-yellow { color: #FBBC05; }
.gr-brand span.g-green { color: #34A853; }

.gr-sub {
  color: #5f6368;
  font-size: 0.95rem;
  margin: 0 0 1.1rem 0;
}

.gr-business-header {
  background: #fff;
  border: 1px solid #dadce0;
  border-radius: 16px;
  padding: 1.25rem 1.4rem;
  margin-bottom: 1.25rem;
  box-shadow: 0 1px 2px rgba(60,64,67,.08);
}
.gr-business-header h2 {
  margin: 0 0 0.35rem 0;
  font-size: 1.45rem;
  color: #202124;
  font-weight: 500;
}
.gr-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem 1.25rem;
  align-items: center;
  color: #5f6368;
  font-size: 0.95rem;
}
.gr-stars {
  color: #fbbc04;
  letter-spacing: 1px;
  font-size: 1.05rem;
}
.gr-rating-num {
  color: #202124;
  font-weight: 500;
}

.gr-match {
  border: 1px solid #dadce0;
  border-radius: 12px;
  padding: 0.9rem 1rem;
  margin-bottom: 0.65rem;
  background: #fff;
  transition: border-color .15s, box-shadow .15s;
}
.gr-match:hover {
  border-color: #4285F4;
  box-shadow: 0 1px 4px rgba(66,133,244,.2);
}
.gr-match h4 {
  margin: 0 0 0.25rem 0;
  font-size: 1.05rem;
  color: #202124;
  font-weight: 500;
}
.gr-match p {
  margin: 0;
  color: #5f6368;
  font-size: 0.88rem;
}

.review-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 1rem;
}

@media (max-width: 1400px) {
  .review-grid { grid-template-columns: repeat(4, 1fr); }
}
@media (max-width: 1100px) {
  .review-grid { grid-template-columns: repeat(3, 1fr); }
}
@media (max-width: 800px) {
  .review-grid { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 520px) {
  .review-grid { grid-template-columns: 1fr; }
}

.review-card {
  background: #fff;
  border: 1px solid #dadce0;
  border-radius: 12px;
  padding: 1rem 1.05rem 1.1rem;
  box-shadow: 0 1px 2px rgba(60,64,67,.08);
  display: flex;
  flex-direction: column;
  min-height: 180px;
  height: 100%;
}
.review-card-top {
  display: flex;
  gap: 0.75rem;
  align-items: center;
  margin-bottom: 0.55rem;
}
.avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: #1a73e8;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 500;
  flex-shrink: 0;
  font-size: 1rem;
}
.author-name {
  font-weight: 500;
  color: #202124;
  font-size: 0.95rem;
  line-height: 1.25;
}
.review-date {
  color: #70757a;
  font-size: 0.8rem;
  margin-top: 2px;
}
.star-row {
  color: #fbbc04;
  font-size: 0.95rem;
  letter-spacing: 1px;
  margin-bottom: 0.45rem;
}
.review-text {
  color: #3c4043;
  font-size: 0.9rem;
  line-height: 1.45;
  flex: 1;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 8;
  -webkit-box-orient: vertical;
}
.empty-state {
  text-align: center;
  color: #5f6368;
  padding: 2.5rem 1rem;
  border: 1px dashed #dadce0;
  border-radius: 12px;
  background: #fafafa;
}
.status-pill {
  display: inline-block;
  background: #e8f0fe;
  color: #1967d2;
  border-radius: 999px;
  padding: 0.2rem 0.7rem;
  font-size: 0.8rem;
  font-weight: 500;
}
</style>
"""

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def fetch_reviews_fresh(maps_url: str, max_reviews: int = 250) -> dict:
    """Run scraper in a separate process so Streamlit's event loop can't break Playwright."""
    proc = subprocess.run(
        [sys.executable, str(FETCH_SCRIPT), maps_url, str(max_reviews)],
        cwd=str(ROOT / "scraper"),
        capture_output=True,
        text=True,
        timeout=300,
    )
    raw = (proc.stdout or "").strip()
    if not raw:
        raise RuntimeError((proc.stderr or "Scraper returned no output").strip())
    # Last JSON line wins (in case of warnings)
    line = raw.splitlines()[-1]
    data = json.loads(line)
    if "error" in data and "reviews" not in data:
        raise RuntimeError(data["error"])
    CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def stars_simple(rating: float | str) -> str:
    try:
        value = float(str(rating).replace(",", "."))
    except (TypeError, ValueError):
        value = 0.0
    full = min(5, max(0, round(value)))
    return "★" * full + "☆" * (5 - full)


def reviews_look_stale(reviews: list[dict]) -> bool:
    """Old session data before photos/owner replies were added."""
    if not reviews:
        return False
    return not any(
        (r.get("profile_photo") or r.get("photos") or r.get("owner_response"))
        for r in reviews
    )


def render_review_cards(reviews: list[dict], business_name: str = "Business") -> None:
    if not reviews:
        st.markdown(
            '<div class="empty-state">No reviews found for this business.</div>',
            unsafe_allow_html=True,
        )
        return

    colors = ["#1a73e8", "#ea4335", "#34a853", "#f9ab00", "#9334e6", "#e8710a"]
    biz = html.escape(business_name or "Business")
    cards = []

    for idx, r in enumerate(reviews):
        author = html.escape(r.get("author") or "Anonymous")
        date = html.escape(r.get("date") or "")
        text_body = html.escape(r.get("text") or "No written review.").replace("\n", "<br>")
        initial = html.escape((r.get("avatar_initial") or author[:1] or "?").upper())
        rating = r.get("rating") or 0
        color = colors[idx % len(colors)]
        profile = html.escape(r.get("profile_photo") or "")
        photos = [p for p in (r.get("photos") or []) if p]
        owner = html.escape(r.get("owner_response") or "").replace("\n", "<br>")
        owner_date = html.escape(r.get("owner_response_date") or "")
        meta = html.escape(r.get("reviewer_meta") or "")

        if profile:
            avatar_html = f"""
              <img class="avatar-img" src="{profile}" alt="{author}"
                   referrerpolicy="no-referrer" loading="lazy"
                   onerror="this.style.display='none';this.nextElementSibling.style.display='flex';" />
              <div class="avatar fallback" style="display:none;background:{color}">{initial}</div>
            """
        else:
            avatar_html = f'<div class="avatar" style="background:{color}">{initial}</div>'

        meta_html = f'<div class="reviewer-meta">{meta}</div>' if meta else ""

        photos_html = ""
        if photos:
            thumbs = []
            show = photos[:5]
            for pi, src in enumerate(show):
                safe = html.escape(src)
                label = ""
                if pi == len(show) - 1 and len(photos) > 5:
                    label = f'<span class="photo-overlay">+{len(photos) - 5}</span>'
                thumbs.append(
                    f"""
                    <a class="photo-thumb" href="{safe}" target="_blank" rel="noopener">
                      <img src="{safe}" alt="Review photo {pi + 1}"
                           referrerpolicy="no-referrer" loading="lazy" />
                      {label}
                    </a>
                    """
                )
            photos_html = f'<div class="photo-row">{"".join(thumbs)}</div>'

        owner_html = ""
        if owner:
            owner_html = f"""
            <div class="owner-reply">
              <div class="owner-rail"></div>
              <div class="owner-body">
                <div class="owner-top">
                  <div class="owner-avatar" title="{biz}">👤</div>
                  <div>
                    <div class="owner-name">{biz} <span>(Owner)</span></div>
                    <div class="owner-date">{owner_date}</div>
                  </div>
                </div>
                <div class="owner-text">{owner}</div>
              </div>
            </div>
            """

        cards.append(
            f"""
            <article class="review-card">
              <div class="review-card-top">
                <div class="avatar-wrap">{avatar_html}</div>
                <div class="author-meta">
                  <div class="author-name">{author}</div>
                  {meta_html}
                </div>
              </div>
              <div class="rating-line">
                <span class="star-row">{stars_simple(rating)}</span>
                <span class="review-date">{date}</span>
              </div>
              <div class="review-text">{text_body}</div>
              {photos_html}
              {owner_html}
            </article>
            """
        )

    grid_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8" />
      <meta name="referrer" content="no-referrer" />
      <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
      <style>
        * {{ box-sizing: border-box; }}
        body {{
          margin: 0;
          font-family: "DM Sans", Roboto, system-ui, sans-serif;
          background: transparent;
          color: #202124;
        }}
        .review-grid {{
          display: grid;
          grid-template-columns: repeat(3, minmax(0, 1fr));
          gap: 1.15rem;
          padding: 0.25rem;
        }}
        @media (max-width: 1100px) {{
          .review-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
        }}
        @media (max-width: 640px) {{
          .review-grid {{ grid-template-columns: 1fr; }}
        }}
        .review-card {{
          background: #fff;
          border: 1px solid #e8eaed;
          border-radius: 20px;
          padding: 1.15rem 1.2rem 1.2rem;
          box-shadow: 0 10px 28px rgba(32,33,36,.06);
          display: flex;
          flex-direction: column;
          gap: 0.65rem;
        }}
        .review-card-top {{
          display: flex;
          gap: 0.85rem;
          align-items: center;
        }}
        .avatar-wrap {{
          width: 48px;
          height: 48px;
          flex-shrink: 0;
          position: relative;
        }}
        .avatar-img, .avatar {{
          width: 48px;
          height: 48px;
          border-radius: 50%;
          object-fit: cover;
          border: 2px solid #fff;
          box-shadow: 0 0 0 1px #dadce0;
        }}
        .avatar {{
          color: #fff;
          display: flex;
          align-items: center;
          justify-content: center;
          font-weight: 600;
          font-size: 1.1rem;
        }}
        .author-name {{
          font-weight: 700;
          font-size: 1rem;
          line-height: 1.25;
        }}
        .reviewer-meta {{
          color: #80868b;
          font-size: 0.8rem;
          margin-top: 2px;
        }}
        .rating-line {{
          display: flex;
          align-items: center;
          gap: 0.55rem;
        }}
        .star-row {{
          color: #fbbc04;
          font-size: 0.95rem;
          letter-spacing: 1px;
        }}
        .review-date {{
          color: #80868b;
          font-size: 0.82rem;
        }}
        .review-text {{
          color: #3c4043;
          font-size: 0.92rem;
          line-height: 1.5;
        }}
        .photo-row {{
          display: grid;
          grid-template-columns: repeat(5, minmax(0, 1fr));
          gap: 0.4rem;
        }}
        .photo-thumb {{
          position: relative;
          display: block;
          aspect-ratio: 1.15;
          border-radius: 10px;
          overflow: hidden;
          background: #f1f3f4;
          border: 1px solid #e8eaed;
        }}
        .photo-thumb img {{
          width: 100%;
          height: 100%;
          object-fit: cover;
          display: block;
        }}
        .photo-overlay {{
          position: absolute;
          inset: 0;
          background: rgba(32,33,36,.55);
          color: #fff;
          display: flex;
          align-items: center;
          justify-content: center;
          font-weight: 700;
          font-size: 0.95rem;
        }}
        .owner-reply {{
          display: flex;
          gap: 0.75rem;
          margin-top: 0.2rem;
          padding-top: 0.55rem;
          border-top: 1px solid #f1f3f4;
        }}
        .owner-rail {{
          width: 3px;
          border-radius: 99px;
          background: #dadce0;
          flex-shrink: 0;
          margin: 0.15rem 0;
        }}
        .owner-body {{ flex: 1; min-width: 0; }}
        .owner-top {{
          display: flex;
          gap: 0.6rem;
          align-items: center;
          margin-bottom: 0.35rem;
        }}
        .owner-avatar {{
          width: 28px;
          height: 28px;
          border-radius: 50%;
          background: #1a73e8;
          color: #fff;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 0.85rem;
          flex-shrink: 0;
        }}
        .owner-name {{
          font-weight: 600;
          font-size: 0.88rem;
          color: #202124;
        }}
        .owner-name span {{
          color: #5f6368;
          font-weight: 500;
        }}
        .owner-date {{
          color: #80868b;
          font-size: 0.75rem;
        }}
        .owner-text {{
          color: #3c4043;
          font-size: 0.86rem;
          line-height: 1.45;
        }}
      </style>
    </head>
    <body>
      <div class="review-grid">{"".join(cards)}</div>
      <script>
        function sendHeight() {{
          const h = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight) + 20;
          window.parent.postMessage({{ isStreamlitMessage: true, type: "streamlit:setFrameHeight", height: h }}, "*");
        }}
        window.addEventListener("load", sendHeight);
        document.querySelectorAll("img").forEach(img => {{
          img.addEventListener("load", sendHeight);
          img.addEventListener("error", sendHeight);
        }});
        setTimeout(sendHeight, 100);
        setTimeout(sendHeight, 500);
        setTimeout(sendHeight, 1200);
      </script>
    </body>
    </html>
    """

    rich = sum(1 for r in reviews if (r.get("photos") or r.get("owner_response")))
    rows = max(1, (len(reviews) + 2) // 3)
    height = min(8000, max(480, rows * (460 if rich else 310)))
    components.html(grid_html, height=height, scrolling=True)


# ---------- Session state ----------
for key, default in {
    "matches": [],
    "selected_place": None,
    "place_details": None,
    "error": None,
    "auto_fetched": False,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


# ---------- Hero / search ----------
st.markdown(
    """
    <div class="gr-hero">
      <p class="gr-brand">
        <span class="g-blue">G</span><span class="g-red">o</span><span class="g-yellow">o</span><span class="g-blue">g</span><span class="g-green">l</span><span class="g-red">e</span>
        Reviews
      </p>
      <p class="gr-sub">Enter your business name — we’ll find it on Maps and show reviews in cards.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.form("search_form", clear_on_submit=False):
    c1, c2 = st.columns([2, 2])
    with c1:
        business_name = st.text_input(
            "Business name",
            placeholder="e.g. Joe's Pizza Downtown Lahore",
            help="Be specific — add city or area for better matches.",
        )
    with c2:
        website = st.text_input(
            "Website (optional)",
            placeholder="e.g. https://www.mybusiness.com",
            help="If provided, we prefer the Maps listing that matches this site.",
        )
    submitted = st.form_submit_button("Search reviews", type="primary", use_container_width=True)

if submitted:
    st.session_state.error = None
    st.session_state.matches = []
    st.session_state.selected_place = None
    st.session_state.place_details = None
    st.session_state.auto_fetched = False

    if not business_name.strip():
        st.session_state.error = "Please enter a business name."
    else:
        with st.spinner("Searching Google Maps… this can take a moment"):
            try:
                matches = search_places(business_name.strip(), website.strip(), max_results=5)
                st.session_state.matches = [m.to_dict() for m in matches]
                if not matches:
                    st.session_state.error = (
                        "No places found. Try a more specific name (add city) or check spelling."
                    )
                else:
                    # Auto-select if website uniquely matches, or only one result
                    chosen = None
                    if website.strip():
                        from scraper.maps import _urls_match

                        preferred = [
                            m for m in matches if _urls_match(m.website, website.strip())
                        ]
                        if len(preferred) == 1:
                            chosen = preferred[0]
                        elif len(preferred) > 1:
                            st.session_state.matches = [m.to_dict() for m in preferred]
                    if chosen is None and len(matches) == 1:
                        chosen = matches[0]
                    if chosen is not None:
                        st.session_state.selected_place = chosen.to_dict()
            except Exception as exc:
                st.session_state.error = f"Search failed: {exc}"

if st.session_state.error:
    st.error(st.session_state.error)

matches = st.session_state.matches
selected = st.session_state.selected_place

# ---------- Match picker ----------
if matches and selected is None:
    st.markdown("#### Choose your business")
    st.caption("We found multiple listings. Pick the correct one to load reviews.")
    for i, m in enumerate(matches):
        rating_bits = []
        if m.get("rating"):
            rating_bits.append(f'{m["rating"]} {stars_simple(m["rating"])}')
        if m.get("review_count"):
            rating_bits.append(f'{m["review_count"]} reviews')
        meta = " · ".join(rating_bits)
        address = html.escape(m.get("address") or "")
        name = html.escape(m.get("name") or "Unknown")
        site = html.escape(m.get("website") or "")
        st.markdown(
            f"""
            <div class="gr-match">
              <h4>{name}</h4>
              <p>{html.escape(meta)}</p>
              <p>{address}</p>
              {"<p>" + site + "</p>" if site else ""}
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button(f"Show reviews for: {m.get('name')}", key=f"pick_{i}", use_container_width=True):
            st.session_state.selected_place = m
            st.session_state.place_details = None
            st.session_state.auto_fetched = False
            st.rerun()

details = st.session_state.place_details

# Auto-refresh old cached reviews that lack photos / owner replies / profile pics
if (
    details
    and selected
    and reviews_look_stale(details.get("reviews") or [])
    and not st.session_state.get("stale_refresh_attempted")
):
    st.session_state.stale_refresh_attempted = True
    st.session_state.place_details = None
    st.session_state.auto_fetched = False
    st.info("Refreshing reviews to load profile photos, uploaded images, and owner replies…")
    st.rerun()

# ---------- Fetch reviews for selected place ----------
if selected and st.session_state.place_details is None and not st.session_state.auto_fetched:
    st.session_state.auto_fetched = True
    with st.spinner("Loading reviews from Google Maps… photos & owner replies included"):
        try:
            st.session_state.place_details = fetch_reviews_fresh(selected["maps_url"], max_reviews=250)
        except Exception as exc:
            st.session_state.error = f"Could not load reviews: {exc}"
            st.session_state.auto_fetched = False

details = st.session_state.place_details

# ---------- Business header + review grid ----------
if details:
    reviews = details.get("reviews") or []
    with_photos = sum(1 for r in reviews if r.get("photos"))
    with_owner = sum(1 for r in reviews if r.get("owner_response"))
    with_avatar = sum(1 for r in reviews if r.get("profile_photo"))

    rating = details.get("rating") or ""
    count = details.get("review_count") or len(reviews)
    address = html.escape(details.get("address") or "")
    site = html.escape(details.get("website") or "")
    name = html.escape(details.get("name") or (selected or {}).get("name") or "Business")
    if name in {"Unknown business", "Business"} and selected:
        name = html.escape(selected.get("name") or name)
    if not details.get("rating") and selected and selected.get("rating"):
        rating = selected.get("rating") or rating
    if (not details.get("website")) and selected and selected.get("website"):
        site = html.escape(selected.get("website") or "")
    if (not details.get("address")) and selected and selected.get("address"):
        address = html.escape(selected.get("address") or "")

    star_row = stars_simple(rating) if rating else ""
    st.markdown(
        f"""
        <div class="gr-business-header">
          <h2>{name}</h2>
          <div class="gr-meta">
            <span class="gr-rating-num">{html.escape(str(rating))}</span>
            <span class="gr-stars">{star_row}</span>
            <span>{html.escape(str(count))} reviews</span>
            {"<span>" + address + "</span>" if address else ""}
            {"<span>" + site + "</span>" if site else ""}
            <span class="status-pill">{len(reviews)} loaded</span>
            <span class="status-pill">{with_avatar} avatars</span>
            <span class="status-pill">{with_photos} with photos</span>
            <span class="status-pill">{with_owner} owner replies</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if with_photos == 0 and with_owner == 0:
        st.warning(
            "Photos/replies were not found in this load. Click **Reload reviews (photos + replies)** again."
        )

    b1, b2 = st.columns(2)
    with b1:
        if st.button("Reload reviews (photos + replies)", use_container_width=True):
            st.session_state.place_details = None
            st.session_state.auto_fetched = False
            st.session_state.stale_refresh_attempted = False
            st.rerun()
    with b2:
        if st.button("Search another business", use_container_width=True):
            st.session_state.matches = []
            st.session_state.selected_place = None
            st.session_state.place_details = None
            st.session_state.auto_fetched = False
            st.session_state.stale_refresh_attempted = False
            st.session_state.error = None
            st.rerun()

    plain_name = details.get("name") or (selected or {}).get("name") or "Business"
    render_review_cards(reviews, business_name=plain_name)

elif not matches and not st.session_state.error:
    st.markdown(
        """
        <div class="empty-state">
          Type your business name above (website optional), then click
          <strong>Search reviews</strong>.
        </div>
        """,
        unsafe_allow_html=True,
    )
