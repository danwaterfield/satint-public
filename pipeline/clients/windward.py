"""
Windward Maritime Intelligence Daily scraper.

Extracts commercial vessel transit counts and chokepoint data from
Windward's daily Iran War Maritime Intelligence blog posts.

URL pattern: https://windward.ai/blog/march-{day}-maritime-intelligence-daily/
(early posts use: march-{day}-iran-war-maritime-intelligence-daily/)

No authentication required — public blog posts.
"""

import logging
import re
from datetime import date, timedelta

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Windward blog URL patterns (they changed naming mid-series)
URL_PATTERNS = [
    "https://windward.ai/blog/march-{day}-maritime-intelligence-daily/",
    "https://windward.ai/blog/march-{day}-iran-war-maritime-intelligence-daily/",
]

# Pre-war baselines (daily vessel crossings)
BASELINES = {
    "hormuz": 138,
    "bab_al_mandeb": 40,
    "suez": 50,
    "cape": 70,
}

# Regex patterns to extract crossing data from blog text
# Windward reports "N crossings" or "N total" for each chokepoint
CROSSING_PATTERNS = {
    "hormuz": [
        re.compile(
            r"(?:hormuz|strait).*?(\d+)\s*(?:total\s*)?(?:crossings?|transits?|vessels?)",
            re.IGNORECASE,
        ),
        re.compile(
            r"(\d+)\s*(?:total\s*)?(?:crossings?|transits?).*?(?:hormuz|strait)",
            re.IGNORECASE,
        ),
    ],
    "bab_al_mandeb": [
        re.compile(
            r"(?:bab\s*(?:el|al)[- ]mandeb).*?(\d+)\s*(?:total\s*)?crossings?",
            re.IGNORECASE,
        ),
    ],
    "suez": [
        re.compile(
            r"(?:suez).*?(\d+)\s*(?:total\s*)?crossings?",
            re.IGNORECASE,
        ),
    ],
    "cape": [
        re.compile(
            r"(?:cape\s*(?:of\s*)?good\s*hope).*?(\d+)\s*(?:total\s*)?(?:crossings?|transits?)",
            re.IGNORECASE,
        ),
    ],
}

INBOUND_RE = re.compile(r"(\d+)\s*inbound", re.IGNORECASE)
OUTBOUND_RE = re.compile(r"(\d+)\s*outbound", re.IGNORECASE)
SEVEN_DAY_RE = re.compile(r"7[- ]day\s*(?:moving\s*)?average[:\s]*([0-9.]+)", re.IGNORECASE)


def fetch_windward_daily(target_date: date) -> dict | None:
    """
    Fetch and parse a Windward Maritime Intelligence Daily post.

    Returns dict of chokepoint data or None if post not found.
    """
    day = target_date.day
    text = None

    for pattern in URL_PATTERNS:
        url = pattern.format(day=day)
        try:
            resp = requests.get(url, timeout=30, headers={
                "User-Agent": "SatInt-Pipeline/1.0 (research)"
            })
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                # Extract main article text
                article = soup.find("article") or soup.find("main") or soup
                text = article.get_text(separator=" ", strip=True)
                logger.info(f"Fetched Windward post: {url}")
                break
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch {url}: {e}")
            continue

    if not text:
        logger.warning(f"No Windward post found for {target_date}")
        return None

    results = {}
    for chokepoint, patterns in CROSSING_PATTERNS.items():
        for pat in patterns:
            match = pat.search(text)
            if match:
                crossings = int(match.group(1))
                # Try to find inbound/outbound near the match
                context = text[max(0, match.start() - 200):match.end() + 200]
                inbound_m = INBOUND_RE.search(context)
                outbound_m = OUTBOUND_RE.search(context)
                avg7_m = SEVEN_DAY_RE.search(context)

                results[chokepoint] = {
                    "crossings": crossings,
                    "inbound": int(inbound_m.group(1)) if inbound_m else None,
                    "outbound": int(outbound_m.group(1)) if outbound_m else None,
                    "seven_day_avg": float(avg7_m.group(1)) if avg7_m else None,
                    "baseline": BASELINES.get(chokepoint, 100),
                }
                break

    return results if results else None
