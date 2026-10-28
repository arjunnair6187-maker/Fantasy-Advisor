"""Free RSS news retrieval and conservative decision-impact summaries."""

from datetime import datetime, timezone
import re

import feedparser


NBA_RSS_URL = "https://www.espn.com/espn/rss/nba/news"
INJURY_TERMS = {"injury", "injured", "out", "questionable", "doubtful", "return", "surgery"}


def fetch_nba_news(limit=60):
    feed = feedparser.parse(NBA_RSS_URL)
    if getattr(feed, "bozo", False) and not feed.entries:
        raise RuntimeError("The NBA news feed is temporarily unavailable.")
    items = []
    for entry in feed.entries[:limit]:
        published = entry.get("published", "Unknown time")
        items.append({
            "title": entry.get("title", "Untitled"),
            "summary": entry.get("summary", ""),
            "link": entry.get("link", ""),
            "published": published,
        })
    return items, datetime.now(timezone.utc)


def filter_relevant_news(items, player_names):
    relevant = []
    for item in items:
        haystack = f"{item['title']} {item['summary']}".casefold()
        matches = [name for name in player_names if name.casefold() in haystack]
        if matches:
            lowered = set(re.findall(r"[a-z]+", haystack))
            injury_related = bool(lowered & INJURY_TERMS)
            if injury_related:
                impact = "Recheck the named player's official status before locking today's lineup."
            else:
                impact = "Monitor this item; it does not by itself prove a lineup change is needed."
            relevant.append({
                **item,
                "players": matches,
                "impact": impact,
                "injury_related": injury_related,
            })
    return relevant
