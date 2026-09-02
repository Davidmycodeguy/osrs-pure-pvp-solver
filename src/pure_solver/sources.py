"""OSRS Wiki source access: fetch a pinned MediaWiki revision (or every result of a search) with a descriptive
User-Agent, and persist the raw record so a ruleset can be re-audited offline.
"""

from __future__ import annotations

import hashlib
import json
import urllib.parse
import urllib.request
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import DataUnavailableError

WIKI_API = "https://oldschool.runescape.wiki/api.php"
USER_AGENT = "osrs-f2p-pure-solver/0.1.0 (+https://github.com/Davidmycodeguy/pure)"


def fetch_wiki_revision(title: str, timeout_seconds: int = 30) -> dict[str, Any]:
    """Fetch a pinned MediaWiki revision with a descriptive User-Agent."""
    parameters = urllib.parse.urlencode(
        {
            "action": "query",
            "format": "json",
            "prop": "revisions",
            "rvprop": "ids|timestamp|content",
            "rvslots": "main",
            "titles": title,
        }
    )
    request = urllib.request.Request(f"{WIKI_API}?{parameters}", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            document = json.load(response)
    except OSError as error:
        raise DataUnavailableError(f"Could not retrieve OSRS Wiki page {title!r}") from error
    page = next(iter(document.get("query", {}).get("pages", {}).values()), None)
    revisions = page and page.get("revisions")
    if not page or not revisions:
        raise DataUnavailableError(f"OSRS Wiki API returned no revision for {title!r}")
    revision = revisions[0]
    content = revision.get("slots", {}).get("main", {}).get("*")
    if not isinstance(content, str):
        raise DataUnavailableError(f"OSRS Wiki revision for {title!r} had no readable main content")
    return {
        "source_id": f"osrs-wiki:{page['pageid']}:{revision['revid']}",
        "title": page["title"],
        "url": _revision_url(page, revision),
        "revision": str(revision["revid"]),
        "retrieved_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source_timestamp": revision["timestamp"],
        "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "content": content,
    }


def _revision_url(page: dict, revision: dict) -> str:
    """Permanent link to one OSRS Wiki revision."""
    title = urllib.parse.quote(page["title"].replace(" ", "_"))
    return f"https://oldschool.runescape.wiki/w/{title}?oldid={revision['revid']}"


def fetch_wiki_search_revisions(
    search_query: str,
    *,
    maximum_records: int | None = None,
    timeout_seconds: int = 30,
) -> Iterator[dict[str, Any]]:
    """Stream current pinned revisions for every result of a MediaWiki search."""
    continuation: dict[str, str] = {}
    emitted = 0
    while True:
        parameters: dict[str, str | int] = {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": search_query,
            "gsrnamespace": 0,
            "gsrlimit": "max",
            "prop": "revisions",
            "rvprop": "ids|timestamp|content",
            "rvslots": "main",
        }
        parameters.update(continuation)
        request = urllib.request.Request(
            f"{WIKI_API}?{urllib.parse.urlencode(parameters)}",
            headers={"User-Agent": USER_AGENT},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                document = json.load(response)
        except OSError as error:
            raise DataUnavailableError(f"Could not execute OSRS Wiki search {search_query!r}") from error
        pages = document.get("query", {}).get("pages", {})
        for page in sorted(pages.values(), key=lambda value: value["title"].casefold()):
            revisions = page.get("revisions")
            if not revisions:
                continue
            revision = revisions[0]
            content = revision.get("slots", {}).get("main", {}).get("*")
            if not isinstance(content, str):
                continue
            yield {
                "source_id": f"osrs-wiki:{page['pageid']}:{revision['revid']}",
                "title": page["title"],
                "url": _revision_url(page, revision),
                "revision": str(revision["revid"]),
                "retrieved_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "source_timestamp": revision["timestamp"],
                "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "content": content,
            }
            emitted += 1
            if maximum_records is not None and emitted >= maximum_records:
                return
        if "continue" not in document:
            return
        continuation = {str(key): str(value) for key, value in document["continue"].items()}


def write_source_record(record: dict[str, Any], destination: str | Path) -> Path:
    """Persist raw source content so a ruleset can be independently re-audited."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return destination
