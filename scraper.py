"""
Aquatic Critter Freshwater Arrival Scraper
Scrapes all known arrival pages and updates fish_data.json
"""

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import json
import os
import re
import time
from datetime import datetime, date

DATA_FILE = "fish_data.json"

KNOWN_PAGES = [
    "https://aquaticcritter.com/blog/new-freshwater-arrival/",
]

# Nav/UI strings that are never fish — exact matches (case-insensitive)
FILTER_EXACT = {
    "check", "newer", "older", "freshwater", "arrival", "call", "us", "mail",
    "location", "home", "getting started", "reptile room", "blog", "faq",
    "store policies", "contact us", "new arrivals", "the aquatic critter",
    "aquatic critter", "getting started", "reptile room", "new saltwater arrival",
    "new freshwater arrival", "reptile arrivals", "mon", "fri", "sat", "sun",
    "back", "top", "next", "previous", "page", "fish", "aquatic", "critter",
    "nashville", "tn", "click", "here", "saltwater", "pond", "store", "contact",
    "faq", "policies", "instagram", "facebook", "subscribe", "email", "hours",
    "overview", "quick links", "copyright", "nolensville", "pk", "middle",
    "complete", "facility", "new", "arrivals", "list", "latest", "marine",
    "animals", "search", "menu", "navigation", "skip", "content", "toggle",
    "reptile", "room", "discover more", "learn more", "read more", "view all",
    "check older freshwater arrival", "check newer freshwater arrival",
    "new freshwater arrival old design", "new freshwater arrival original",
}

# Substrings that indicate a nav/UI string — if any found, skip
FILTER_SUBSTRINGS = [
    "aquaticcritter.com", "nolensville pk", "615", "832-4541",
    "cbeggin@", "middle tn", "mon-fri", "10:00am", "copyright",
    "check older", "check newer", "old design",
    "freshwater fish arrivals", "freshwater fish arriving",
    "new freshwater arrival", "saltwater arrivals",
]

# Size/modifier prefixes that make a name potentially ambiguous
AMBIGUOUS_PREFIX_RE = re.compile(
    r'^(\d+(\.\d+)?\s*["\'])',  # 2.5" 3.5' — size measurements only
    re.IGNORECASE
)

# Words too common to trigger fuzzy queue alone — includes fish family/type words
# since "betta" + "plakat" appearing in two names doesn't mean they're the same fish
COMMON_WORDS = {
    # Colors
    "red", "blue", "green", "black", "white", "orange", "yellow", "purple",
    "pink", "gold", "silver", "grey", "gray", "albino", "neon",
    # Sizes/descriptors
    "assorted", "mixed", "large", "small", "med", "reg", "regular", "select",
    "size", "grade", "giant", "nano", "mini", "super", "ultra", "jumbo",
    "florida", "sa", "wild", "tank", "bred",
    # Gender
    "male", "female",
    # Fish family/type words — these alone don't make two fish the same
    "betta", "tetra", "molly", "guppy", "pleco", "plecostomus", "corydoras",
    "cory", "loach", "barb", "danio", "rasbora", "cichlid", "oscar", "angel",
    "angelfish", "shark", "goby", "catfish", "shrimp", "snail", "crab",
    "frog", "eel", "knife", "puffer", "rainbow", "platy", "swordtail",
    "oranda", "ryukin", "ranchu", "goldfish", "koi", "gourami", "discus",
    "parrot", "flowerhorn", "oscar", "severum", "acara", "pike", "peacock",
    "halfmoon", "crowntail", "plakat", "dumbo", "lyretail", "tuxedo",
    "nerite", "mystery", "apple", "ghost", "cherry", "bamboo", "african",
    "dwarf", "clawed", "clown", "feeder", "comet", "roseline", "ramirez",
    "german", "electric", "fire", "tiger", "leopard", "zebra", "panda",
}

FETCH_DELAY = 2

# ── Playwright ──
_playwright = None
_browser = None
_page = None

def get_browser_page():
    global _playwright, _browser, _page
    if _page is None:
        _playwright = sync_playwright().start()
        _browser = _playwright.chromium.launch(headless=True)
        context = _browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        _page = context.new_page()
    return _page

def close_browser():
    global _playwright, _browser, _page
    try:
        if _browser: _browser.close()
        if _playwright: _playwright.stop()
    except Exception:
        pass
    _playwright = _browser = _page = None

def fetch_page(url):
    try:
        page = get_browser_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1500)
        return page.content()
    except Exception as e:
        print(f"  [WARN] Could not fetch {url}: {e}")
        return None


# ── Fuzzy matching (conservative) ──

def normalize(name):
    return re.sub(r'\s+', ' ', name.lower().strip())

def singular(name):
    n = normalize(name)
    if n.endswith('es') and len(n) > 4: return n[:-2]
    if n.endswith('s') and len(n) > 3: return n[:-1]
    return n

def significant_words(name):
    """Words longer than 3 chars that aren't common/color/size words."""
    return [w for w in normalize(name).split() if len(w) > 3 and w not in COMMON_WORDS]

def fuzzy_matches(new_name, existing_names):
    """
    Conservative fuzzy match. Only flags:
    1. One name is a substring of the other
    2. Plural/singular exact match
    3. 2+ significant (non-common) words overlap
    Single-word overlaps on common words are NOT flagged.
    """
    matches = []
    n_norm = normalize(new_name)
    n_sing = singular(new_name)
    n_sig = set(significant_words(new_name))

    for existing in existing_names:
        e_norm = normalize(existing)
        e_sing = singular(existing)
        e_sig = set(significant_words(existing))

        # Exact match — not ambiguous
        if n_norm == e_norm:
            return []

        # Plural/singular
        if n_sing == e_sing and n_sing and len(n_sing) > 4:
            matches.append((existing, f'plural/singular of "{existing}"'))
            continue

        # Substring — one fully contains the other, but only flag if the
        # shorter name is more than just the longer with a size word stripped.
        # e.g. "Plecostomus" ⊂ "Plecostomus Med" — don't flag (Med is common)
        if len(n_norm) > 6 and len(e_norm) > 6:
            if n_norm in e_norm:
                # Check if e_norm is just n_norm + common words
                suffix = e_norm.replace(n_norm, '').strip()
                if suffix and all(w in COMMON_WORDS for w in suffix.split()):
                    continue  # just a size/color variant suffix, skip
                matches.append((existing, f'substring match with "{existing}"'))
                continue
            if e_norm in n_norm:
                suffix = n_norm.replace(e_norm, '').strip()
                if suffix and all(w in COMMON_WORDS for w in suffix.split()):
                    continue
                matches.append((existing, f'substring match with "{existing}"'))
                continue

        # 2+ significant word overlap (ignoring common words)
        overlap = n_sig & e_sig
        if len(overlap) >= 2:
            matches.append((existing, f'shares key words {overlap} with "{existing}"'))
            continue

    return matches


# ── Name cleaning ──

def is_nav_junk(text):
    """True if this string looks like a nav/menu/UI element, not a fish."""
    lower = text.lower().strip()
    if lower in FILTER_EXACT:
        return True
    for sub in FILTER_SUBSTRINGS:
        if sub in lower:
            return True
    # Multi-word nav strings
    if any(lower == f for f in FILTER_EXACT):
        return True
    return False

def clean_fish_name(text):
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^[\s\-\.\*\•\–\—]+", "", text)
    text = re.sub(r"[\-\.\*\•\–\—\:]+$", "", text).strip()
    if len(text) < 3 or len(text) > 80: return None
    if re.match(r"^[\d\s\W]+$", text): return None
    lower = text.lower()
    # Single-word filter
    if lower in FILTER_EXACT: return None
    if any(fw == lower for fw in FILTER_EXACT): return None
    if "@" in text or "http" in text or ".com" in text: return None
    if re.search(r"\d{5,}", text): return None
    # Nav junk check
    if is_nav_junk(text): return None
    return text.title()

def parse_heading_date(text):
    text = text.strip()
    m = re.search(
        r'(January|February|March|April|May|June|July|August|September|October|November|December)'
        r'\s+(\d{1,2}),?\s+(\d{4})', text, re.IGNORECASE
    )
    if m:
        try:
            dt = datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y")
            return dt.strftime("%Y-%m-%d")
        except ValueError: pass
    m = re.search(r'(\d{1,2})/(\d{1,2})/(\d{2,4})', text)
    if m:
        try:
            year = m.group(3)
            if len(year) == 2: year = "20" + year
            dt = datetime.strptime(f"{m.group(1)}/{m.group(2)}/{year}", "%m/%d/%Y")
            return dt.strftime("%Y-%m-%d")
        except ValueError: pass
    return None


# ── Page extraction ──

def extract_fish_by_date(html, url, fallback_date, already_scraped_dates):
    """
    Returns {date_str: [name, ...]} — skips dates already in already_scraped_dates.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Try to isolate the main content area — avoid nav/header/footer
    content = (
        soup.find("div", class_=re.compile(r"entry-content|post-content|page-content|wp-block-post-content"))
        or soup.find("main")
        or soup.find("article")
    )
    # If we can't find a content area, fall back to body but strip known nav elements
    if not content:
        content = soup.body
        if content:
            for nav_el in content.find_all(['nav', 'header', 'footer']):
                nav_el.decompose()
            # Remove elements with nav-like classes
            for el in content.find_all(class_=re.compile(r'nav|menu|header|footer|sidebar')):
                el.decompose()

    if not content:
        return {}

    results = {}
    current_date = fallback_date
    seen_on_date = {}

    for el in content.descendants:
        if not hasattr(el, 'name') or el.name is None:
            continue

        if el.name in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            heading_text = el.get_text(separator=" ").strip()
            parsed = parse_heading_date(heading_text)
            if parsed:
                current_date = parsed
            # Never extract fish from headings — they're structural, not fish names
            continue

        if el.name in ('li', 'p', 'strong', 'b', 'em', 'span', 'div'):
            has_block_child = any(
                getattr(c, 'name', None) in ('p', 'div', 'ul', 'ol', 'h1','h2','h3','h4','h5','h6')
                for c in el.children
            )
            if has_block_child:
                continue

            raw = el.get_text(separator="\n").strip()
            for candidate in re.split(r"[\n,]+", raw):
                candidate = candidate.strip()
                if not candidate: continue

                # Skip if this date already fully scraped
                if current_date in already_scraped_dates:
                    continue

                cleaned = clean_fish_name(candidate)
                if not cleaned: continue

                if current_date not in seen_on_date:
                    seen_on_date[current_date] = set()
                key = cleaned.lower()
                if key in seen_on_date[current_date]: continue
                seen_on_date[current_date].add(key)
                if current_date not in results:
                    results[current_date] = []
                results[current_date].append(cleaned)

    return results


def get_best_fallback_date(html):
    """
    Find the best fallback date for a page by scanning all heading dates.
    Uses the EARLIEST heading date found (oldest content on the page).
    Falls back to today only as a last resort.
    """
    soup = BeautifulSoup(html, "html.parser")
    heading_dates = []
    for tag in soup.find_all(['h1','h2','h3','h4','h5','h6']):
        text = tag.get_text(separator=" ").strip()
        d = parse_heading_date(text)
        if d:
            heading_dates.append(d)
    if heading_dates:
        # Use the earliest date found — this is the oldest content section
        # Fish without an explicit heading will belong to that section
        return min(heading_dates)
    return date.today().strftime("%Y-%m-%d")


def discover_linked_pages(html):
    soup = BeautifulSoup(html, "html.parser")
    links = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "freshwater-arrival" in href and "aquaticcritter.com" in href:
            links.add(href.rstrip("/") + "/")
    return links


# ── Data ──

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "fish": {},
        "scrape_log": [],
        "pages_scraped": [],
        "scraped_dates": [],   # dates fully processed — skip on future runs
        "latest_page_date": None,
        "resolution_map": {},
        "pending_queue": [],
    }

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def snapshot_current_state(data):
    return {name: sorted(info.get("occurrences", [])) for name, info in data["fish"].items()}


# ── Resolution ──

def resolve_name(raw_name, data):
    """Returns (resolved_name, is_pending, similar_list)."""
    resolution_map = data.get("resolution_map", {})
    lower = raw_name.lower()

    for key, resolution in resolution_map.items():
        if key.lower() == lower:
            if resolution["action"] == "associate":
                return resolution["target"], False, []
            elif resolution["action"] == "individual":
                return resolution.get("name", raw_name), False, []

    # Size measurement prefix — always queue
    if AMBIGUOUS_PREFIX_RE.match(raw_name.strip()):
        existing = list(data.get("fish", {}).keys())
        similar = fuzzy_matches(raw_name, existing)
        return None, True, similar

    # Fuzzy match against existing
    existing = list(data.get("fish", {}).keys())
    similar = fuzzy_matches(raw_name, existing)
    if similar:
        return None, True, similar

    return raw_name, False, []


def add_to_queue(raw_name, fish_date, source_url, data, similar_to=None):
    queue = data.setdefault("pending_queue", [])
    for item in queue:
        if item["raw"].lower() == raw_name.lower():
            if fish_date > item.get("seen_on", ""):
                item["seen_on"] = fish_date
            return
    entry = {"raw": raw_name, "seen_on": fish_date, "source_url": source_url}
    if similar_to:
        entry["similar_to"] = [s[0] for s in similar_to[:3]]
        entry["reasons"] = [s[1] for s in similar_to[:3]]
    queue.append(entry)
    hint = f" (similar to: {', '.join(s[0] for s in similar_to[:2])})" if similar_to else ""
    print(f"  [QUEUE] '{raw_name}'{hint}")


def record_fish(name, fish_date, data, new_fish_count_ref):
    if name not in data["fish"]:
        data["fish"][name] = {"occurrences": [], "variants": [], "variant_occurrences": {}}
        new_fish_count_ref[0] += 1
    data["fish"][name].setdefault("variants", [])
    data["fish"][name].setdefault("variant_occurrences", {})
    occ = data["fish"][name].setdefault("occurrences", [])
    if fish_date not in occ:
        occ.append(fish_date)
        occ.sort()


# ── Main scrape ──

def run_scrape():
    print(f"\n=== Aquatic Critter Scraper — {datetime.now().strftime('%Y-%m-%d %H:%M')} ===")

    data = load_data()
    data.setdefault("resolution_map", {})
    data.setdefault("pending_queue", [])
    data.setdefault("scraped_dates", [])

    already_scraped_dates = set(data["scraped_dates"])
    state_before = snapshot_current_state(data)

    pages_to_scrape = set(KNOWN_PAGES)
    pages_to_scrape.update(data.get("pages_scraped", []))

    all_fish_found = {}

    for i, url in enumerate(sorted(pages_to_scrape)):
        if i > 0:
            print(f"  [WAIT] Pausing {FETCH_DELAY}s…")
            time.sleep(FETCH_DELAY)

        print(f"\nFetching: {url}")
        html = fetch_page(url)
        if not html: continue

        page_date = get_best_fallback_date(html)
        fish_by_date = extract_fish_by_date(html, url, page_date, already_scraped_dates)

        if fish_by_date:
            all_fish_found[url] = {"fish_by_date": fish_by_date, "latest_date": max(fish_by_date.keys())}
            total = sum(len(v) for v in fish_by_date.values())
            skipped = len([d for d in already_scraped_dates if d in (page_date,)])
            print(f"  [OK] Found {total} fish across {len(fish_by_date)} date section(s)")
            for d, names in sorted(fish_by_date.items(), reverse=True):
                print(f"       {d}: {len(names)} fish")
                for name in sorted(names)[:3]:
                    print(f"         - {name}")
                if len(names) > 3:
                    print(f"         ... and {len(names)-3} more")
        else:
            skipped_count = sum(1 for d in already_scraped_dates)
            print(f"  [SKIP] All dates already scraped" if skipped_count > 0 else f"  [EMPTY] No fish extracted")

    pages_scraped_set = set(data.get("pages_scraped", []))
    new_fish_count_ref = [0]
    newly_scraped_dates = set()

    all_page_dates = [info["latest_date"] for info in all_fish_found.values() if info.get("latest_date")]
    if all_page_dates:
        latest_this_run = max(all_page_dates)
        existing_latest = data.get("latest_page_date")
        if not existing_latest or latest_this_run > existing_latest:
            data["latest_page_date"] = latest_this_run

    for url, info in all_fish_found.items():
        pages_scraped_set.add(url)
        for fish_date, fish_names in info["fish_by_date"].items():
            newly_scraped_dates.add(fish_date)
            base_names_this_date = set()
            for raw_name in fish_names:
                resolved, is_pending, similar = resolve_name(raw_name, data)
                if is_pending:
                    add_to_queue(raw_name, fish_date, url, data, similar)
                elif resolved:
                    if resolved.lower() != raw_name.lower():
                        fish_entry = data["fish"].get(resolved, {})
                        variants = fish_entry.setdefault("variants", [])
                        v_occ = fish_entry.setdefault("variant_occurrences", {})
                        if raw_name not in variants:
                            variants.append(raw_name)
                        v_occ.setdefault(raw_name, [])
                        if fish_date not in v_occ[raw_name]:
                            v_occ[raw_name].append(fish_date)
                            v_occ[raw_name].sort()
                    if resolved.lower() not in base_names_this_date:
                        base_names_this_date.add(resolved.lower())
                        record_fish(resolved, fish_date, data, new_fish_count_ref)

    # Mark all processed dates as scraped
    scraped_set = set(data["scraped_dates"])
    scraped_set.update(newly_scraped_dates)
    data["scraped_dates"] = sorted(scraped_set)
    data["pages_scraped"] = sorted(pages_scraped_set)

    state_after = snapshot_current_state(data)
    changed = state_after != state_before
    pending_count = len(data.get("pending_queue", []))

    scrape_entry = {
        "timestamp": datetime.now().isoformat(),
        "pages_checked": len(pages_to_scrape),
        "new_fish": new_fish_count_ref[0],
        "total_fish": len(data["fish"]),
        "pending_queue": pending_count,
        "changed": changed,
    }
    data["scrape_log"].append(scrape_entry)
    data["scrape_log"] = data["scrape_log"][-100:]

    save_data(data)
    close_browser()

    print(f"\n=== Done. {new_fish_count_ref[0]} new fish added. {pending_count} in queue. Total: {len(data['fish'])} fish tracked. ===\n")
    return scrape_entry


if __name__ == "__main__":
    run_scrape()
