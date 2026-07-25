"""
Windward Maritime Intelligence Daily scraper.

Extracts commercial vessel transit counts and chokepoint data from
Windward's daily Iran War Maritime Intelligence blog posts.

URL pattern: https://windward.ai/blog/{month}-{day}-maritime-intelligence-daily/
(early posts use: {month}-{day}-iran-war-maritime-intelligence-daily/)

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
    "https://windward.ai/blog/{month}-{day}-maritime-intelligence-daily/",
    "https://windward.ai/blog/{month}-{day}-iran-war-maritime-intelligence-daily/",
]

# Pre-war baselines (daily vessel crossings)
BASELINES = {
    "hormuz": 138,
    "bab_al_mandeb": 40,
    "suez": 50,
    "cape": 70,
}

# Keep the count close to the chokepoint name and tie vessel counts explicitly
# to transit wording.  A broad ``.*?`` previously crossed section boundaries
# and mistook Gulf-wide vessel presence for Strait of Hormuz crossings.
_NUMBER = r"(?:\d{1,3}|zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
CROSSING_PATTERNS = {
    "hormuz": [
        re.compile(
            rf"(?:strait\s+of\s+)?hormuz.{{0,300}}?({_NUMBER})\s+"
            rf"(?:AIS-transmitting\s+)?vessels?\s+(?:were\s+)?recorded\s+transiting",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?:strait\s+of\s+)?hormuz.{{0,300}}?({_NUMBER})\s+"
            rf"(?:inbound\s+|outbound\s+)?(?:crossings?|transits?)",
            re.IGNORECASE,
        ),
        re.compile(
            rf"({_NUMBER})\s+(?:total\s+)?(?:crossings?|transits?).{{0,160}}?"
            rf"(?:strait\s+of\s+)?hormuz",
            re.IGNORECASE,
        ),
    ],
    "bab_al_mandeb": [
        re.compile(
            rf"(?:bab\s*(?:el|al)[- ]mandeb).{{0,240}}?({_NUMBER})\s+"
            rf"(?:total\s+)?(?:crossings?|transits?)",
            re.IGNORECASE,
        ),
    ],
    "suez": [
        re.compile(
            rf"(?:suez).{{0,240}}?({_NUMBER})\s+(?:total\s+)?(?:crossings?|transits?)",
            re.IGNORECASE,
        ),
    ],
    "cape": [
        re.compile(
            rf"(?:cape\s*(?:of\s*)?good\s*hope).{{0,240}}?({_NUMBER})\s+"
            rf"(?:total\s+)?(?:crossings?|transits?)",
            re.IGNORECASE,
        ),
    ],
}

_NUMBER_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}

INBOUND_RE = re.compile(r"(\d+)\s*inbound", re.IGNORECASE)
OUTBOUND_RE = re.compile(r"(\d+)\s*outbound", re.IGNORECASE)
SEVEN_DAY_RE = re.compile(r"7[- ]day\s*(?:moving\s*)?average[:\s]*([0-9.]+)", re.IGNORECASE)


def _parse_count(value: str) -> int:
    value = value.lower()
    return int(value) if value.isdigit() else _NUMBER_WORDS[value]


def parse_windward_text(text: str) -> dict:
    """Extract defensible chokepoint transit counts from one article."""
    results = {}
    for chokepoint, patterns in CROSSING_PATTERNS.items():
        for pat in patterns:
            match = pat.search(text)
            if not match:
                continue

            crossings = _parse_count(match.group(1))
            baseline = BASELINES.get(chokepoint, 100)
            # Chokepoint capacity cannot plausibly jump several-fold overnight.
            # Treat such matches as a parser failure, not an extraordinary event.
            if crossings > baseline * 2:
                logger.warning(
                    "Rejected implausible Windward %s count: %d (baseline=%d)",
                    chokepoint,
                    crossings,
                    baseline,
                )
                break

            context = text[max(0, match.start() - 200):match.end() + 200]
            inbound_m = INBOUND_RE.search(context)
            outbound_m = OUTBOUND_RE.search(context)
            avg7_m = SEVEN_DAY_RE.search(context)
            results[chokepoint] = {
                "crossings": crossings,
                "inbound": int(inbound_m.group(1)) if inbound_m else None,
                "outbound": int(outbound_m.group(1)) if outbound_m else None,
                "seven_day_avg": float(avg7_m.group(1)) if avg7_m else None,
                "baseline": baseline,
            }
            break
    return results


def fetch_windward_daily(target_date: date) -> dict | None:
    """
    Fetch and parse a Windward Maritime Intelligence Daily post.

    Returns dict of chokepoint data or None if post not found.
    """
    day = target_date.day
    month = target_date.strftime("%B").lower()
    text = None

    for pattern in URL_PATTERNS:
        url = pattern.format(month=month, day=day)
        try:
            resp = requests.get(url, timeout=30, headers={
                "User-Agent": "SatInt-Pipeline/1.0 (research)"
            })
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                page_title = soup.title.get_text(" ", strip=True) if soup.title else ""
                expected_date = f"{target_date.strftime('%B')} {day}, {target_date.year}"
                if expected_date not in page_title:
                    logger.warning(
                        "Ignoring Windward page with mismatched date: expected %s, title=%r",
                        expected_date,
                        page_title,
                    )
                    continue
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

    results = parse_windward_text(text)
    return results if results else None
