"""
Aquatic Critter Freshwater Arrival Scraper
Scrapes all known arrival pages and updates fish_data.json
"""

import requests
from bs4 import BeautifulSoup
import json
import os
import re
from datetime import datetime, date

DATA_FILE = "fish_data.json"

# All known arrival page URLs - scraper will also try to discover new ones
KNOWN_PAGES = [
    "https://aquaticcritter.com/new-freshwater-arrival-old/",
    "https://aquaticcritter.com/blog/new-freshwater-arrival-original/",
    "https://aquaticcritter.com/blog/new-freshwater-arrival-2/",
    "https://aquaticcritter.com/blog/new-freshwater-arrival-3/",
    "https://aquaticcritter.com/blog/new-freshwater-arrival-4/",
    "https://aquaticcritter.com/blog/new-freshwater-arrival/",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Words/phrases that are NOT fish names - used to filter junk from page text
FILTER_WORDS = {
    "check", "newer", "older", "freshwater", "arrival", "call", "us", "mail",
    "location", "home", "getting", "started", "reptile", "room", "blog",
    "mon", "fri", "sat", "sun", "back", "top", "next", "previous", "page",
    "fish", "aquatic", "critter", "nashville", "tn", "click", "here",
    "saltwater", "pond", "store", "contact", "faq", "policies", "instagram",
    "facebook", "subscribe", "email", "hours", "overview", "quick", "links",
    "copyright", "nolensville", "pk", "middle", "complete", "facility",
    "new", "arrivals", "list", "latest", "marine", "animals", "reptile",
    "search", "menu", "navigation", "skip", "content", "toggle",
}


def fetch_page(url):
    """Fetch a page with browser-like headers."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        print(f"  [WARN] Could not fetch {url}: {e}")
        return None


def extract_fish_names(html, url):
    """
    Extract fish names from an arrival page.
    The site uses various formats - we look for lists, bold items,
    and line-by-line text within the main content area.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Try to find the main content area
    content = (
        soup.find("div", class_=re.compile(r"entry-content|post-content|page-content|wp-block-post-content"))
        or soup.find("main")
        or soup.find("article")
        or soup.body
    )

    fish_names = set()

    if not content:
        return fish_names

    # Strategy 1: Look for list items (ul/ol)
    for li in content.find_all("li"):
        text = li.get_text(separator=" ").strip()
        name = clean_fish_name(text)
        if name:
            fish_names.add(name)

    # Strategy 2: Look for paragraphs that look like fish lists
    # (short lines, often separated by line breaks or commas)
    for p in content.find_all("p"):
        text = p.get_text(separator="\n").strip()
        # Split on newlines and commas
        candidates = re.split(r"[\n,]+", text)
        for candidate in candidates:
            name = clean_fish_name(candidate)
            if name:
                fish_names.add(name)

    # Strategy 3: Bold/strong text often highlights fish names
    for tag in content.find_all(["strong", "b", "em"]):
        text = tag.get_text().strip()
        name = clean_fish_name(text)
        if name:
            fish_names.add(name)

    return fish_names


def clean_fish_name(text):
    """
    Clean and validate a potential fish name.
    Returns the cleaned name or None if it looks like junk.
    """
    # Remove extra whitespace
    text = re.sub(r"\s+", " ", text).strip()

    # Remove leading/trailing punctuation and numbers
    text = re.sub(r"^[\d\s\-\.\*\•\–\—]+", "", text)
    text = re.sub(r"[\-\.\*\•\–\—\:]+$", "", text).strip()

    # Skip if too short or too long
    if len(text) < 3 or len(text) > 80:
        return None

    # Skip if it's just numbers or symbols
    if re.match(r"^[\d\s\W]+$", text):
        return None

    # Skip known non-fish words
    lower = text.lower()
    if any(fw == lower for fw in FILTER_WORDS):
        return None

    # Skip if it contains URLs or email patterns
    if "@" in text or "http" in text or ".com" in text:
        return None

    # Skip lines that look like addresses or phone numbers
    if re.search(r"\d{3,}", text):
        return None

    # Skip very generic short words (navigation leftovers)
    words = lower.split()
    if len(words) == 1 and lower in FILTER_WORDS:
        return None

    # Capitalize properly (Title Case for fish names)
    return text.title()


def get_page_date(html, url):
    """
    Try to extract a publish/update date from the page.
    Falls back to today's date.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Try common WordPress date meta tags
    for selector in [
        {"name": "article:published_time"},
        {"property": "article:published_time"},
        {"name": "article:modified_time"},
    ]:
        meta = soup.find("meta", selector)
        if meta and meta.get("content"):
            try:
                dt = datetime.fromisoformat(meta["content"][:10])
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                pass

    # Try <time> tags
    time_tag = soup.find("time")
    if time_tag:
        dt_str = time_tag.get("datetime", "")
        if dt_str:
            try:
                dt = datetime.fromisoformat(dt_str[:10])
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                pass

    return date.today().strftime("%Y-%m-%d")


def discover_linked_pages(html):
    """Find any additional arrival page links on a page."""
    soup = BeautifulSoup(html, "html.parser")
    links = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "freshwater-arrival" in href and "aquaticcritter.com" in href:
            links.add(href.rstrip("/") + "/")
    return links


def load_data():
    """Load existing fish data from JSON file."""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "fish": {},
        "scrape_log": [],
        "pages_scraped": []
    }


def save_data(data):
    """Save fish data to JSON file."""
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def run_scrape():
    """Main scrape function. Returns a summary dict."""
    print(f"\n=== Aquatic Critter Scraper — {datetime.now().strftime('%Y-%m-%d %H:%M')} ===")

    data = load_data()
    pages_to_scrape = set(KNOWN_PAGES)
    pages_to_scrape.update(data.get("pages_scraped", []))

    all_fish_found = {}  # page_url -> {date, fish_set}
    newly_discovered = set()

    for url in sorted(pages_to_scrape):
        print(f"\nFetching: {url}")
        html = fetch_page(url)
        if not html:
            continue

        page_date = get_page_date(html, url)
        fish = extract_fish_names(html, url)

        # Discover more linked pages
        new_links = discover_linked_pages(html)
        for link in new_links:
            if link not in pages_to_scrape:
                newly_discovered.add(link)
                print(f"  [DISCOVER] Found new page: {link}")

        if fish:
            all_fish_found[url] = {"date": page_date, "fish": fish}
            print(f"  [OK] Found {len(fish)} fish, dated {page_date}")
            for name in sorted(fish)[:5]:
                print(f"       - {name}")
            if len(fish) > 5:
                print(f"       ... and {len(fish)-5} more")
        else:
            print(f"  [EMPTY] No fish extracted from this page")

    # Scrape newly discovered pages too
    for url in newly_discovered:
        print(f"\nFetching (new): {url}")
        html = fetch_page(url)
        if not html:
            continue
        page_date = get_page_date(html, url)
        fish = extract_fish_names(html, url)
        if fish:
            all_fish_found[url] = {"date": page_date, "fish": fish}
            print(f"  [OK] Found {len(fish)} fish, dated {page_date}")

    # Update the fish database
    pages_scraped_set = set(data.get("pages_scraped", []))
    new_fish_count = 0

    for url, info in all_fish_found.items():
        pages_scraped_set.add(url)
        page_date = info["date"]
        for fish_name in info["fish"]:
            if fish_name not in data["fish"]:
                data["fish"][fish_name] = {"occurrences": []}
                new_fish_count += 1
            # Add this date if not already recorded
            occ = data["fish"][fish_name]["occurrences"]
            if page_date not in occ:
                occ.append(page_date)
                occ.sort()

    data["pages_scraped"] = sorted(pages_scraped_set)

    # Log this scrape run
    scrape_entry = {
        "timestamp": datetime.now().isoformat(),
        "pages_checked": len(all_fish_found),
        "new_fish": new_fish_count,
        "total_fish": len(data["fish"]),
    }
    data["scrape_log"].append(scrape_entry)
    # Keep last 100 log entries
    data["scrape_log"] = data["scrape_log"][-100:]

    save_data(data)

    print(f"\n=== Done. {new_fish_count} new fish added. Total: {len(data['fish'])} fish tracked. ===\n")
    return scrape_entry


if __name__ == "__main__":
    run_scrape()
