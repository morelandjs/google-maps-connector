"""Scrape+extract behind the `get_events` tool.

Per website: harvest homepage links → pick the events page (heuristic
short-circuit, Gemini flash-lite fallback) → scrape it to markdown + images →
extract structured events with Gemini flash. A batch of websites shares ONE
headless Chromium, with each site's pages opened as tabs in the same browser
context under a semaphore — the parallelism model ported from stealth-search's
`fetch_batch_markdown_and_images_async` (browser_utils.py), which is far
cheaper than launching a browser per site. The calling agent still owns
discovery (`search_nearby_places` supplies the website URLs) and downstream
filtering/joining/ranking; per-site failures come back as error entries so one
bot-walled site never sinks the rest of the batch.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import Any
from urllib.parse import urlparse, urldefrag

import httpx

import gemini
import scraper

# Sized so a batch can absorb one full Gemini rate-limit window (~60s wait)
# and still finish scraping+extracting. Stay under Cloud Run's 300s timeout.
DEFAULT_BUDGET_S = float(os.environ.get("CHECK_EVENTS_BUDGET_S", "210"))

# Sites where headless scraping always fails (bot walls / app shells); cheaper
# to reject up front and tell the agent why.
SOCIAL_DOMAINS = {
    "instagram.com",
    "facebook.com",
    "m.facebook.com",
    "twitter.com",
    "x.com",
    "linktr.ee",
    "tiktok.com",
    "youtube.com",
}

EVENT_PATH_KEYWORDS = (
    "event",
    "calendar",
    "shows",
    "whats-on",
    "whats_on",
    "whatson",
    "upcoming",
    "happenings",
    "live-music",
    "gigs",
    "schedule",
    "tickets",
    "performances",
    "programs",
)

# An exact match on one of these paths is unambiguous — skip the LLM pick.
EXACT_EVENT_PATHS = {
    "/events",
    "/event",
    "/calendar",
    "/whats-on",
    "/whatson",
    "/shows",
    "/upcoming-events",
    "/happenings",
}

MAX_LINKS_FOR_LLM = 100
MAX_HEURISTIC_CANDIDATES = 40
MAX_IMAGE_URLS_CONSIDERED = 30
IMAGE_FETCH_CONCURRENCY = 16

# Concurrent Playwright pages (tabs) within the one shared browser — same
# max_parallel=8 stealth-search used for its batch scrapes.
PAGE_CONCURRENCY = 8

# Stage wall-clock caps (seconds); the global Deadline may shorten them.
# The Gemini stages must absorb quota-backoff waits (up to ~65s per retry
# when a rate-limit window is being waited out), so their caps are much
# larger than a single request needs.
LINKS_STAGE_CAP = 15.0
CLASSIFY_STAGE_CAP = 100.0
SCRAPE_STAGE_CAP = 20.0
IMAGES_STAGE_CAP = 15.0
EXTRACT_STAGE_CAP = 160.0

# At most this many Chromium instances per process; pairs with the Cloud Run
# --concurrency setting to keep memory bounded when the agent maps
# get_events across several websites in parallel.
_BROWSER_SLOTS = asyncio.Semaphore(2)


class DeadlineExceeded(RuntimeError):
    """The tool's global time budget ran out."""


class StageTimeout(RuntimeError):
    """One pipeline stage exceeded its own cap (the global budget remains)."""


class SocialMediaSite(ValueError):
    """The URL points at a social-media/link-tree host, not a venue website."""


class Deadline:
    """Global wall-clock budget shared by every stage of one tool call."""

    def __init__(self, budget_s: float) -> None:
        self._loop = asyncio.get_running_loop()
        self._start = self._loop.time()
        self._end = self._start + budget_s
        self.budget_s = budget_s
        self.hit = False

    def remaining(self, cap: float | None = None) -> float:
        rem = self._end - self._loop.time()
        if cap is not None:
            rem = min(rem, cap)
        return max(rem, 0.0)

    def elapsed(self) -> float:
        return self._loop.time() - self._start

    async def run(self, coro, *, cap: float | None = None):
        """Await coro within min(remaining, cap); DeadlineExceeded when out of budget."""
        if self.remaining() <= 0.5:  # not worth starting
            coro.close()
            self.hit = True
            raise DeadlineExceeded(f"time budget ({self.budget_s:.0f}s) exhausted")
        timeout = self.remaining(cap)
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.TimeoutError:
            if self.remaining() <= 0:
                self.hit = True
                raise DeadlineExceeded(
                    f"time budget ({self.budget_s:.0f}s) exhausted"
                ) from None
            raise StageTimeout(f"stage timed out after {timeout:.0f}s") from None


def _hostname(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host.removeprefix("www.")


def _is_social(url: str) -> bool:
    host = _hostname(url)
    return any(host == d or host.endswith("." + d) for d in SOCIAL_DOMAINS)


def _same_site_links(website: str, links: list[str]) -> list[str]:
    """Keep http(s) links on the website's host, defragmented and deduped."""
    site_host = _hostname(website)
    kept: list[str] = []
    for link in links:
        parsed = urlparse(link)
        if parsed.scheme not in ("http", "https"):
            continue
        host = _hostname(link)
        if host != site_host and not host.endswith("." + site_host):
            continue
        kept.append(urldefrag(link)[0])
    return list(dict.fromkeys(kept))


def pick_event_link(website: str, links: list[str]) -> tuple[str | None, list[str]]:
    """Choose the events page heuristically when unambiguous.

    Returns (short_circuit_url, llm_candidates). If short_circuit_url is set
    the LLM call can be skipped; otherwise llm_candidates (possibly empty) is
    the list to classify — heuristic keyword hits first, then the shortest
    remaining links up to MAX_LINKS_FOR_LLM (short URLs skew toward main nav).
    """
    same_site = _same_site_links(website, links)

    hits = [
        link
        for link in same_site
        if any(kw in urlparse(link).path.lower() for kw in EVENT_PATH_KEYWORDS)
    ]

    exact = [
        link
        for link in hits
        if urlparse(link).path.lower().rstrip("/") in EXACT_EVENT_PATHS
    ]
    if exact:
        return min(exact, key=len), []

    hits = sorted(hits, key=len)[:MAX_HEURISTIC_CANDIDATES]
    rest = sorted((l for l in same_site if l not in set(hits)), key=len)
    candidates = (hits + rest)[:MAX_LINKS_FOR_LLM]
    return None, candidates


def _to_typesense_event(event: dict[str, Any], event_page_url: str) -> dict[str, Any]:
    """Map a raw extraction onto Vibrant's TypeSense event fields.

    Only the event-page-derived subset of the TypeSense `events` collection —
    place/about fields (place_id, address, neighborhood, place_description,
    geopoint, ...) are the caller's to join.
    """
    def clean(field: str) -> str:
        # Gemini's structured output sometimes wraps short string fields in
        # stray quotes/tabs (seen on `emoji`: '"\t🍳"'). Strip the wrapping.
        return (event.get(field) or "").strip().strip("\"'").strip()

    start_date = clean("start_date")
    try:
        start_date_numeric = int(
            datetime.strptime(start_date, "%Y-%m-%d").strftime("%Y%m%d")
        )
    except ValueError:
        start_date_numeric = None
    return {
        "event_title_derived": clean("event_title_derived"),
        "event_description_derived": clean("event_description_derived"),
        "start_date": start_date,
        "start_date_numeric": start_date_numeric,
        "start_time": clean("start_time"),
        "price": clean("price"),
        "keywords": clean("keywords"),
        "emoji": clean("emoji"),
        "event_page_url": event_page_url,
    }


async def _gather_images(
    image_urls: list[str], client: httpx.AsyncClient
) -> list[str]:
    """Validate then download+downscale images, keeping the first N that pass."""
    sem = asyncio.Semaphore(IMAGE_FETCH_CONCURRENCY)

    async def _validate(url: str) -> bool:
        async with sem:
            return await scraper.validate_image_url(url, client)

    considered = image_urls[:MAX_IMAGE_URLS_CONSIDERED]
    verdicts = await asyncio.gather(*(_validate(u) for u in considered))
    valid = [u for u, ok in zip(considered, verdicts) if ok]
    valid = valid[: gemini.MAX_IMAGES_PER_SITE]

    async def _download(url: str) -> str | None:
        async with sem:
            return await scraper.download_and_downscale_image(url, client)

    downloaded = await asyncio.gather(*(_download(u) for u in valid))
    return [b64 for b64 in downloaded if b64]


def _validate_website(website: str) -> None:
    parsed = urlparse(website)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"Not an http(s) URL: {website!r}")
    if _is_social(website):
        raise SocialMediaSite(
            f"{website} is a social-media/link-tree page; headless scraping of "
            "these always fails. Use the venue's own website."
        )


async def _check_single(
    website: str,
    context,
    deadline: Deadline,
    http_client: httpx.AsyncClient,
    page_sem: asyncio.Semaphore,
    *,
    gemini_api_key: str,
    today: str,
    language: str = "en",
) -> list[dict[str, Any]]:
    """Run the full pipeline for one website inside the shared browser.

    Returns [] when the site has no discoverable events page (a legitimate
    outcome, not an error). Raises SocialMediaSite / scraper.CloudflareBlocked
    / gemini.GeminiError / DeadlineExceeded / StageTimeout for conditions the
    caller should hear about.
    """
    async with page_sem:
        links = await deadline.run(
            scraper.extract_links(context, website), cap=LINKS_STAGE_CAP
        )

    event_url, candidates = pick_event_link(website, links)
    if event_url is None:
        if not candidates:
            return []
        event_url = await deadline.run(
            gemini.identify_events_page(
                api_key=gemini_api_key, homepage=website, links=candidates
            ),
            cap=CLASSIFY_STAGE_CAP,
        )
        if not event_url:
            return []

    async with page_sem:
        markdown, image_urls = await deadline.run(
            scraper.extract_markdown_and_images(context, event_url),
            cap=SCRAPE_STAGE_CAP,
        )

    images_b64 = await deadline.run(
        _gather_images(image_urls, http_client), cap=IMAGES_STAGE_CAP
    )

    events = await deadline.run(
        gemini.extract_events(
            api_key=gemini_api_key,
            markdown=markdown,
            images_webp_b64=images_b64,
            today=today,
            language=language,
        ),
        cap=EXTRACT_STAGE_CAP,
    )

    mapped = [_to_typesense_event(e, event_url) for e in events]
    # Venue event pages often include an archive; the prompt asks the model to
    # skip past events, but this filter is the guarantee. Undated events
    # (blank start_date) are kept — the caller decides what to do with them.
    today_numeric = int(today.replace("-", ""))
    return [
        e
        for e in mapped
        if e["start_date_numeric"] is None or e["start_date_numeric"] >= today_numeric
    ]


def _error_message(website: str, exc: BaseException) -> str:
    """One agent-facing sentence explaining why a site couldn't be checked."""
    if isinstance(exc, (SocialMediaSite, ValueError)):
        return str(exc)
    if isinstance(exc, scraper.CloudflareBlocked):
        return (
            f"{website} is behind a bot-challenge wall and could not be "
            "scraped headlessly. Report this venue as unchecked rather than "
            "assuming it has no events."
        )
    if isinstance(exc, gemini.GeminiError):
        return f"Event extraction failed for {website}: {exc}"
    if isinstance(exc, (DeadlineExceeded, StageTimeout)):
        return (
            f"{website} took too long to process ({exc}). The site may be "
            "slow or very large; report it as unchecked."
        )
    return f"Failed to check {website}: {type(exc).__name__}: {str(exc)[:200]}"


async def check_websites_for_events(
    websites: list[str],
    *,
    gemini_api_key: str,
    today: str,
    language: str = "en",
    budget_s: float = DEFAULT_BUDGET_S,
) -> dict[str, Any]:
    """Check a batch of venue websites concurrently and return per-site results.

    Returns {website: events_list | {"error": reason}} keyed by the URLs as
    given. All sites share one headless Chromium: each site's page loads run
    as tabs in the same browser context, bounded by PAGE_CONCURRENCY — the
    stealth-search batch-scrape model. One shared Deadline covers the whole
    batch; sites that don't finish in time get an error entry instead of
    failing the call.
    """
    results: dict[str, Any] = {}
    to_check: list[str] = []
    seen: set[str] = set()
    for website in websites:
        if website in seen:
            continue
        seen.add(website)
        try:
            _validate_website(website)
            to_check.append(website)
        except (SocialMediaSite, ValueError) as exc:
            results[website] = {"error": _error_message(website, exc)}

    if not to_check:
        return results

    deadline = Deadline(budget_s)
    page_sem = asyncio.Semaphore(PAGE_CONCURRENCY)

    async with _BROWSER_SLOTS:
        async with scraper.browser_context() as context:
            async with httpx.AsyncClient(
                follow_redirects=True, timeout=5.0
            ) as http_client:
                outcomes = await asyncio.gather(
                    *(
                        _check_single(
                            website,
                            context,
                            deadline,
                            http_client,
                            page_sem,
                            gemini_api_key=gemini_api_key,
                            today=today,
                            language=language,
                        )
                        for website in to_check
                    ),
                    return_exceptions=True,
                )

    for website, outcome in zip(to_check, outcomes):
        if isinstance(outcome, BaseException):
            results[website] = {"error": _error_message(website, outcome)}
        else:
            results[website] = outcome
    return results
