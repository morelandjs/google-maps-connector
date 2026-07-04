import asyncio
from contextlib import asynccontextmanager

import pytest

import gemini
import scraper
from events_pipeline import (
    Deadline,
    DeadlineExceeded,
    StageTimeout,
    _to_typesense_event,
    check_websites_for_events,
    pick_event_link,
)

RAW_EVENT = {
    "name": "Jazz Night",
    "start_date": "2026-07-03",
    "start_time": "20:00:00",
    "location": "Main stage",
    "price": "$15",
    "event_title_derived": "Jazz Night at the Venue",
    "event_description_derived": "Live jazz.",
    "keywords": "jazz, music, live, bar, night",
    "emoji": "🎷",
}

EXPECTED_EVENT = {
    "event_title_derived": "Jazz Night at the Venue",
    "event_description_derived": "Live jazz.",
    "start_date": "2026-07-03",
    "start_date_numeric": 20260703,
    "start_time": "20:00:00",
    "price": "$15",
    "keywords": "jazz, music, live, bar, night",
    "emoji": "🎷",
    "event_page_url": "https://venue.test/events",
}


async def check_one(website, **kwargs):
    """Single-site convenience wrapper over the batch entry point."""
    result = await check_websites_for_events(
        [website], gemini_api_key="K", today="2026-07-01", **kwargs
    )
    return result[website]


@pytest.fixture
def fake_browser(monkeypatch):
    """Replace the Playwright lifecycle with a no-op context object."""
    launches = {"count": 0}

    @asynccontextmanager
    async def fake_context():
        launches["count"] += 1
        yield object()

    monkeypatch.setattr(scraper, "browser_context", fake_context)
    return launches


@pytest.fixture
def happy_scrape(monkeypatch, fake_browser):
    """Scraper + Gemini fakes for venues whose /events page has one event."""

    async def fake_links(context, url):
        return [f"{url.rstrip('/')}/events", f"{url.rstrip('/')}/menu"]

    async def fake_markdown(context, url):
        return "## Jazz Night\nFriday 8pm", []

    async def fake_extract(**kwargs):
        return [dict(RAW_EVENT)]

    monkeypatch.setattr(scraper, "extract_links", fake_links)
    monkeypatch.setattr(scraper, "extract_markdown_and_images", fake_markdown)
    monkeypatch.setattr(gemini, "extract_events", fake_extract)
    return fake_browser


async def test_happy_path_returns_typesense_shaped_events(happy_scrape):
    events = await check_one("https://venue.test")
    assert events == [EXPECTED_EVENT]


async def test_batch_shares_one_browser_and_isolates_failures(
    monkeypatch, happy_scrape
):
    """One Chromium for the whole batch (stealth-search's tab parallelism),
    and a bot-walled site becomes an error entry, not a batch failure."""
    launches = happy_scrape
    original_links = scraper.extract_links

    async def sometimes_blocked(context, url):
        if "blocked" in url:
            raise scraper.CloudflareBlocked(url)
        return await original_links(context, url)

    monkeypatch.setattr(scraper, "extract_links", sometimes_blocked)

    result = await check_websites_for_events(
        [
            "https://venue.test",
            "https://blocked.test",
            "https://www.instagram.com/venue",
            "https://venue.test",  # duplicate — checked once
        ],
        gemini_api_key="K",
        today="2026-07-01",
    )

    assert set(result) == {
        "https://venue.test",
        "https://blocked.test",
        "https://www.instagram.com/venue",
    }
    assert result["https://venue.test"] == [EXPECTED_EVENT]
    assert "bot-challenge" in result["https://blocked.test"]["error"]
    assert "social-media" in result["https://www.instagram.com/venue"]["error"]
    assert launches["count"] == 1  # sites shared a single browser launch


async def test_past_events_filtered_out(monkeypatch, happy_scrape):
    """Venue archives must not leak: seen live on focalpoint.beer, whose
    events page lists months of past events below the upcoming ones."""

    async def fake_extract(**kwargs):
        return [
            dict(RAW_EVENT),  # 2026-07-03, upcoming
            {**RAW_EVENT, "start_date": "2025-12-16"},  # archive
            {**RAW_EVENT, "start_date": "2026-06-28"},  # last week
            {**RAW_EVENT, "start_date": ""},  # undated — kept
        ]

    monkeypatch.setattr(gemini, "extract_events", fake_extract)
    events = await check_one("https://venue.test")
    assert [e["start_date"] for e in events] == ["2026-07-03", ""]


async def test_invalid_urls_error_without_launching_browser(fake_browser):
    result = await check_websites_for_events(
        ["mailto:hi@venue.test", "https://www.instagram.com/venue"],
        gemini_api_key="K",
        today="2026-07-01",
    )
    assert "http" in result["mailto:hi@venue.test"]["error"]
    assert "social-media" in result["https://www.instagram.com/venue"]["error"]
    assert fake_browser["count"] == 0


async def test_deadline_exhaustion_becomes_error_entry(monkeypatch, fake_browser):
    async def slow_links(context, url):
        await asyncio.sleep(5)
        return []

    monkeypatch.setattr(scraper, "extract_links", slow_links)
    result = await check_websites_for_events(
        ["https://venue.test"], gemini_api_key="K", today="2026-07-01", budget_s=0.6
    )
    assert "too long" in result["https://venue.test"]["error"]


async def test_no_events_page_returns_empty(monkeypatch, fake_browser):
    async def fake_links(context, url):
        # keyword hit but not an exact path → needs the LLM
        return [f"{url}/live-music-history", f"{url}/menu"]

    async def classify(**kwargs):
        return None

    monkeypatch.setattr(scraper, "extract_links", fake_links)
    monkeypatch.setattr(gemini, "identify_events_page", classify)

    assert await check_one("https://venue.test") == []


async def test_no_candidate_links_returns_empty(monkeypatch, fake_browser):
    async def fake_links(context, url):
        return ["https://external.example.com/events", "mailto:hi@venue.test"]

    monkeypatch.setattr(scraper, "extract_links", fake_links)
    assert await check_one("https://venue.test") == []


async def test_heuristic_short_circuit_skips_classify(monkeypatch, happy_scrape):
    called = False

    async def classify(**kwargs):
        nonlocal called
        called = True
        return None

    monkeypatch.setattr(gemini, "identify_events_page", classify)
    events = await check_one("https://venue.test")
    assert len(events) == 1
    assert called is False


def test_to_typesense_event_strips_gemini_quote_artifacts():
    # Seen live: Gemini wraps short fields in stray quotes/tabs.
    event = _to_typesense_event(
        {**RAW_EVENT, "emoji": '"\t🍳"', "price": ' "$15" '},
        "https://venue.test/events",
    )
    assert event["emoji"] == "🍳"
    assert event["price"] == "$15"


def test_to_typesense_event_handles_blank_date():
    event = _to_typesense_event(
        {**RAW_EVENT, "start_date": ""}, "https://venue.test/events"
    )
    assert event["start_date"] == ""
    assert event["start_date_numeric"] is None
    # place/about fields must not leak into the event shape
    assert "name" not in event and "location" not in event


def test_pick_event_link_exact_short_circuit():
    url, candidates = pick_event_link(
        "https://venue.test",
        [
            "https://venue.test/events/",
            "https://venue.test/menu",
            "https://external.example.com/events",
            "mailto:hi@venue.test",
        ],
    )
    assert url == "https://venue.test/events/"
    assert candidates == []


def test_pick_event_link_candidates_prefer_keyword_hits():
    links = ["https://venue.test/all-happenings-2026", "https://venue.test/a"]
    url, candidates = pick_event_link("https://venue.test", links)
    assert url is None
    assert candidates[0] == "https://venue.test/all-happenings-2026"


async def test_deadline_run_distinguishes_stage_cap_from_global():
    deadline = Deadline(budget_s=30)

    async def slow():
        await asyncio.sleep(1)

    with pytest.raises(StageTimeout, match="stage timed out"):
        await deadline.run(slow(), cap=0.05)
    assert deadline.hit is False

    tight = Deadline(budget_s=0.05)
    await asyncio.sleep(0.06)
    with pytest.raises(DeadlineExceeded):
        await tight.run(slow())
    assert tight.hit is True
