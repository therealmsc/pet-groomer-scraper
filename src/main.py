"""
Apify Actor: US Pet Groomer Scraper

Self-contained Apify actor that scrapes pet grooming business data for any US state:
1. Discovers groomers via DuckDuckGo search (3 queries per city)
2. Crawls each groomer website with PlaywrightCrawler
3. Extracts structured data with BeautifulSoup + regex
4. Outputs to Apify dataset

Zero API keys required. Uses embedded city lists (10,444 cities across 50 states + DC).
"""

import asyncio
import re
from datetime import timedelta
from urllib.parse import urlparse, unquote

from bs4 import BeautifulSoup
from crawlee.crawlers import PlaywrightCrawler, PlaywrightCrawlingContext
from crawlee.router import Router
from crawlee import Request
from ddgs import DDGS

from apify import Actor

from src.city_lists import get_cities_for_state

# ─── Router for groomer website crawling ───
router = Router[PlaywrightCrawlingContext]()

# ─── Regex patterns for groomer data extraction ───
PHONE_RE = re.compile(r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}')
SAT_RE = re.compile(r'Saturday[:\s]*(\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM)\s*(?:-|–|to)\s*\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM))', re.I)
SUNDAY_RE = re.compile(r'Sunday[:\s]*(\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM)\s*(?:-|–|to)\s*\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM))', re.I)
MOBILE_RE = re.compile(r'mobile grooming|mobile pet spa|house call|come to you|we come to|mobile service', re.I)
SELF_WASH_RE = re.compile(r'self.?wash|self.?serve|diy wash|do.?it.?yourself wash', re.I)
DOG_GROOMING_RE = re.compile(r'dog grooming|dog groom|cainine grooming|puppy groom', re.I)
CAT_GROOMING_RE = re.compile(r'cat grooming|cat groom|feline grooming|kitten groom', re.I)
NAIL_TRIM_RE = re.compile(r'nail trim|nail clip|nail grind|dremel', re.I)
BATH_RE = re.compile(r'bath|de.?shed|shampoo|conditioning treatment', re.I)
HAIRCUT_RE = re.compile(r'haircut|breed.?specific|scissor|clipper|trim', re.I)
TEETH_RE = re.compile(r'teeth cleaning|dental|breath', re.I)
FOUNDED_RE = re.compile(r'(?:since|established|founded|serving since)\s*(\d{4})', re.I)
GROOMER_NAMES_RE = re.compile(r'(?:Groomer|Stylist)\s*[:\-]?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)', re.I)


@router.default_handler
async def groomer_handler(context: PlaywrightCrawlingContext) -> None:
    """Crawl a groomer website and extract structured data."""
    url = context.request.url
    city = context.request.user_data.get("city", "Unknown")
    Actor.log.info(f"Crawling groomer: {url}")

    try:
        await context.page.goto(url, wait_until="domcontentloaded", timeout=10000)
        html = await context.page.content()
    except Exception as e:
        Actor.log.warning(f"Failed to load {url}: {e}")
        return

    soup = BeautifulSoup(html, "lxml")

    # ── Extract data ──
    name = _extract_name(soup, url)
    address = _extract_address(soup)
    phone = _extract_phone(soup, html)
    body = soup.find("body")
    page_text = body.get_text(" ", strip=True)[:5000] if body else ""
    text = soup.get_text(" ", strip=True)

    groomer = {
        "name": name,
        "url": url,
        "city": city,
        "state": context.request.user_data.get("state", ""),
        "address": address,
        "phone": phone,
        "mobile_grooming": bool(MOBILE_RE.search(text)),
        "self_wash": bool(SELF_WASH_RE.search(text)),
        "dog_grooming": bool(DOG_GROOMING_RE.search(text)),
        "cat_grooming": bool(CAT_GROOMING_RE.search(text)),
        "nail_trim": bool(NAIL_TRIM_RE.search(text)),
        "bathing": bool(BATH_RE.search(text)),
        "haircut_styling": bool(HAIRCUT_RE.search(text)),
        "teeth_cleaning": bool(TEETH_RE.search(text)),
        "sat_hours": _extract_saturday(text),
        "sun_hours": _extract_sunday(text),
        "founded": _extract_founded(text),
        "services": _extract_services(text),
        "notes": "",
    }

    # Skip Cloudflare / JS-challenge pages
    if name.strip() in ("Just a moment...", "Checking your browser", "Please Wait...", "One moment please"):
        Actor.log.info(f"  ✗ Skipping (challenge page): {url}")
        return

    # Skip aggregator/directory pages by name pattern
    name_lower = name.lower()
    agg_patterns = [
        "best groomers in", "dog groomers in", "pet groomers in",
        "top-rated groomer", "find a groomer", "groomer near me",
        "directory", "listings", "results for",
        "names and numbers", "groomers near",
        "dog grooming near", "pet grooming near",
    ]
    if any(p in name_lower for p in agg_patterns):
        Actor.log.info(f"  ✗ Skipping (aggregator page): {name}")
        return

    # Skip records with obfuscated phone numbers
    if phone and ("****" in phone or "*" in phone):
        Actor.log.info(f"  ✗ Skipping (obfuscated phone): {url}")
        return

    await context.push_data(groomer)
    Actor.log.info(f"  ✓ {name} ({city})")


# ─── Generic page titles ───
GENERIC_TITLES = {
    "home", "contact", "contact us", "about", "about us", "team", "our team",
    "services", "our services", "grooming", "pet grooming", "dog grooming",
    "pet groomer", "dog groomer", "groomer", "blog", "news", "gallery",
    "location", "hours", "appointments", "book now", "request appointment",
    "new client", "new customers", "welcome", "privacy policy", "terms",
    "faq", "reviews", "testimonials", "careers", "employment", "staff",
    "pricing", "rates", "packages", "photos", "before and after",
}


def _is_generic_title(title: str) -> bool:
    clean = title.strip().lower().rstrip(" .-|")
    if clean in GENERIC_TITLES:
        return True
    if len(clean) < 5:
        return True
    if len(set(clean)) <= 2 and len(clean) > 3:
        return True
    if clean in ("javascript is disabled", "page not found", "404"):
        return True
    return False


def _extract_name(soup: BeautifulSoup, url: str) -> str:
    """Extract groomer business name from page title, H1, or domain."""
    title = soup.title.string if soup.title else ""
    if title:
        # Strip common suffixes (check longest first to avoid partial matches)
        suffixes = [
            " - Dog Groomer", " | Dog Groomer", " - Pet Groomer", " | Pet Groomer",
            " - Dog Grooming", " | Dog Grooming", " - Pet Grooming", " | Pet Grooming",
            " - Grooming Salon", " | Grooming Salon", " - Pet Spa", " | Pet Spa",
            " - Dog Spa", " | Dog Spa", " - Home", " | Home",
            " - Contact Us", " | Contact Us", " - About Us", " | About Us",
        ]
        for suffix in suffixes:
            if suffix in title:
                title = title.split(suffix)[0].strip()
        # If title still has pipe-separated parts (e.g. "Dog Grooming | Arnold, MO | Playful Paws"),
        # take the last meaningful segment (the business name)
        if " | " in title:
            parts = [p.strip() for p in title.split(" | ")]
            # Remove parts that look like locations (short, comma-separated)
            location_words = {"mo", "il", "ks", "ia", "ne", "ok", "ar", "tn", "ky",
                              "tx", "co", "wy", "mt", "nd", "sd", "mn", "wi", "mi",
                              "in", "oh", "pa", "ny", "vt", "nh", "me", "ma", "ri",
                              "ct", "nj", "de", "md", "va", "wv", "nc", "sc", "ga",
                              "fl", "al", "ms", "la", "nm", "az", "ca", "nv", "ut",
                              "id", "or", "wa", "ak", "hi", "dc"}
            biz_parts = []
            for part in parts:
                # Skip parts that are just city, state abbreviation, or short generic labels
                if len(part) < 4:
                    continue
                if "," in part and len(part) < 30:
                    maybe_state = part.split(",")[-1].strip().lower()
                    if maybe_state in location_words:
                        continue
                if part.lower() in GENERIC_TITLES:
                    continue
                biz_parts.append(part)
            if biz_parts:
                title = biz_parts[-1]  # Last non-location segment = business name
        # Only use title if it's not generic and has reasonable length
        if not _is_generic_title(title) and 5 < len(title) < 80:
            return title

    h1 = soup.find("h1")
    if h1:
        h1_text = h1.get_text(strip=True)
        if h1_text and not _is_generic_title(h1_text) and len(h1_text) < 80:
            return h1_text

    domain = urlparse(url).netloc.replace("www.", "")
    return domain.split(".")[0].replace("-", " ").title()


def _extract_address(soup: BeautifulSoup) -> str:
    """Extract street address from common patterns."""
    for selector in [
        "[itemprop='address']", "[itemprop='streetAddress']",
        ".address", ".contact-address", ".street-address",
        "address", ".location", "[data-address]",
    ]:
        el = soup.select_one(selector)
        if el:
            text = el.get_text(" ", strip=True)
            for junk in ["Map pin icon", "Get directions", "Directions", "View on map", "Open in maps"]:
                text = text.replace(junk, "")
            if len(text) > 10 and any(c.isdigit() for c in text):
                if text.startswith("(") and text.count(")") == 1:
                    continue
                if len(text) > 120:
                    continue
                text = re.sub(r'\s+', ' ', text).strip()
                return text[:120]

    text = soup.get_text(" ", strip=True)
    addr_re = re.compile(
        r'(\d{1,6}\s+[A-Za-z0-9\s.,]+(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Way|Boulevard|Blvd|Highway|Hwy|Parkway|Pkwy)[,.\s]*'
        r'(?:[A-Za-z\s]+,\s*[A-Z]{2}\s*\d{5})?)'
    )
    m = addr_re.search(text)
    if m:
        found = m.group(1).strip()
        if found.startswith("(") and found.count("(") <= 1 and len(found) < 20:
            return ""
        if len(found) > 200:
            return ""
        review_words = ["months ago", "thank", "wonderful", "amazing"]
        if any(w in found.lower() for w in review_words):
            return ""
        return found[:120]
    return ""


def _extract_phone(soup: BeautifulSoup, html: str) -> str:
    """Extract first phone number found."""
    for a in soup.find_all("a", href=True):
        if a["href"].startswith("tel:"):
            raw = a["href"].replace("tel:", "").strip()
            return unquote(raw)

    for selector in ["[itemprop='telephone']", ".phone", ".tel", ".contact-phone"]:
        el = soup.select_one(selector)
        if el:
            m = PHONE_RE.search(el.get_text())
            if m:
                return m.group(0)

    m = PHONE_RE.search(soup.get_text())
    return m.group(0) if m else ""


def _extract_saturday(text: str) -> str:
    m = SAT_RE.search(text)
    return f"Sat {m.group(1).strip()}" if m else ""


def _extract_sunday(text: str) -> str:
    m = SUNDAY_RE.search(text)
    return f"Sun {m.group(1).strip()}" if m else ""


def _extract_founded(text: str) -> str:
    m = FOUNDED_RE.search(text)
    return m.group(1) if m else ""


def _extract_services(text: str) -> str:
    """Extract listed services beyond the boolean flags."""
    services = []
    service_patterns = [
        (r'ear cleaning', 'ear cleaning'),
        (r'anal gland', 'anal gland expression'),
        (r'flea.*?treatment|flea.*?bath', 'flea treatment'),
        (r'de.?matting|de.?shedding', 'de-shedding'),
        (r'pawdicure|paw.*?care', 'paw care'),
        (r'blueberry.*?facial|facial.*?treatment', 'facial treatment'),
        (r'spa.*?package|pet.*?spa', 'spa package'),
        (r'puppy.*?package|puppy.*?intro', 'puppy package'),
        (r'senior.*?dog|senior.*?pet', 'senior dog care'),
        (r'breed.*?specific|breed.*?standard', 'breed-specific cuts'),
        (r'hand.*?stripping', 'hand stripping'),
        (r'creative.*?grooming|color.*?dye', 'creative grooming'),
    ]
    for pattern, label in service_patterns:
        if re.search(pattern, text, re.I):
            services.append(label)

    return ", ".join(services) if services else ""


async def discover_groomers(state: str, cities: list[str]) -> dict[str, list[dict]]:
    """
    Discover groomer URLs by searching DuckDuckGo for each city.
    Returns dict mapping city -> list of {url, name} dicts.
    """
    groomer_urls: dict[str, list[dict]] = {}
    seen_urls: set[str] = set()

    search_queries = [
        "{city} {state} pet groomer",
        "{city} {state} dog grooming",
        "{city} {state} pet grooming salon",
    ]

    for city in cities:
        Actor.log.info(f"Searching: {city}, {state}...")
        city_groomers = []

        for query_template in search_queries:
            query = query_template.format(city=city, state=state)
            results = []
            for attempt in range(3):
                try:
                    with DDGS() as ddgs:
                        results = list(ddgs.text(query, max_results=8))
                    break
                except Exception as e:
                    if attempt == 2:
                        Actor.log.warning(f"  Search failed for {city} after 3 attempts: {e}")
                    else:
                        await asyncio.sleep(1.5)

            for r in results:
                url = r.get("href", "")
                if not url or not url.startswith("http"):
                    continue
                parsed = urlparse(url)
                domain = parsed.netloc.lower()

                # Skip known non-groomer domains
                skip_domains = {
                    "yelp.com", "facebook.com", "nextdoor.com", "mapquest.com",
                    "yellowpages.com", "chamberofcommerce.com", "manta.com",
                    "linkedin.com", "instagram.com", "twitter.com", "x.com",
                    "google.com", "bing.com", "duckduckgo.com",
                    "youtube.com", "pinterest.com", "tiktok.com",
                    "wagwalking.com", "rover.com", "care.com",
                    "petco.com", "petsmart.com", "pet supplies plus",
                    "petlist.us", "petsathome.com",
                    "chewy.com", "petsupply.com", "tractorsupply.com",
                    "hotels.com", "booking.com", "bringfido.com",
                    "animalshelter.org", "petfinder.com", "adoptapet.com",
                    "scratchpay.com", "carecredit.com",
                    "healthgrades.com", "vcahospitals.com",
                    "greatpetcare.com", "geniusvets.com", "pawlicy.com",
                    "birdeye.com", "superpages.com",
                    "namesandnumbers.com", "regionaldirectory.us",
                }
                if any(d in domain for d in skip_domains):
                    continue

                base_domain = domain.split(".")[0] if domain.count(".") == 1 else ".".join(domain.split(".")[-2:])
                if base_domain in seen_urls:
                    continue
                seen_urls.add(base_domain)

                name = r.get("title", "")[:80]
                city_groomers.append({"url": url, "name": name})

        if city_groomers:
            groomer_urls[city] = city_groomers
            Actor.log.info(f"  {city}: {len(city_groomers)} groomers found")
        else:
            Actor.log.info(f"  {city}: 0 groomers")

        await asyncio.sleep(1)

    return groomer_urls


async def main() -> None:
    async with Actor:
        # ── Read input ──
        actor_input = await Actor.get_input() or {}
        state = actor_input.get("state", "Missouri")
        max_cities = actor_input.get("maxCities", 0)
        max_groomers_per_city = actor_input.get("maxGroomersPerCity", 15)

        Actor.log.info(f"✂️ Pet Groomer Scraper — {state}")
        Actor.log.info(f"   Max cities: {max_cities or 'ALL'}")
        Actor.log.info(f"   Max groomers/city: {max_groomers_per_city}")

        # ── Load city list ──
        state = state.strip()
        try:
            cities = get_cities_for_state(state)
        except ValueError:
            try:
                cities = get_cities_for_state(state.title())
                state = state.title()
            except ValueError as e:
                await Actor.fail(status_message=f"Unknown state: '{state}'. Valid: Alabama, Alaska, ..., Wyoming")
                return

        if max_cities and max_cities > 0:
            cities = cities[:max_cities]

        Actor.log.info(f"   Cities to search: {len(cities)}")

        # ── Phase 1: Discover groomers via DuckDuckGo ──
        Actor.log.info("🔍 Phase 1: Discovering groomers...")
        groomer_urls = await discover_groomers(state, cities)

        total_groomers = sum(len(v) for v in groomer_urls.values())
        cities_with = len(groomer_urls)
        Actor.log.info(f"   Found {total_groomers} groomers across {cities_with}/{len(cities)} cities")

        if not groomer_urls:
            Actor.log.info("No groomers found. Exiting.")
            return

        # ── Phase 2: Crawl groomer websites ──
        Actor.log.info("🕷️ Phase 2: Crawling groomer websites...")

        start_urls = []
        for city, groomers in groomer_urls.items():
            for groomer in groomers[:max_groomers_per_city]:
                start_urls.append(Request.from_url(
                    groomer["url"],
                    user_data={"city": city, "state": state}
                ))

        proxy_configuration = await Actor.create_proxy_configuration()
        if proxy_configuration is None:
            Actor.log.warning("No proxy configuration available, crawling without proxy")

        crawler = PlaywrightCrawler(
            proxy_configuration=proxy_configuration,
            request_handler=router,
            max_requests_per_crawl=len(start_urls) * 2,
            headless=True,
            browser_launch_options={
                "args": ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
            },
            max_request_retries=1,
            request_handler_timeout=timedelta(seconds=30),
        )

        await crawler.run(start_urls)

        Actor.log.info(f"✅ Done! Crawled {total_groomers} groomer URLs.")
        Actor.log.info(f"   Results saved to default dataset.")


if __name__ == "__main__":
    asyncio.run(main())
