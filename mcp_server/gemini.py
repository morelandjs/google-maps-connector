"""Thin async client for the Gemini API (AI Studio key) used by `get_events`.

Same shape as google_maps.py: module-level constants, one error class, plain
async functions over httpx. Structured output uses Gemini's `responseSchema`,
which is an OpenAPI-3 subset — NOT full JSON Schema — so the schemas below are
hand-written dicts rather than Pydantic `model_json_schema()` dumps
(`additionalProperties`, `$ref`, etc. are rejected by the API).
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import httpx

GEMINI_GENERATE_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

# One cheap multimodal model for both event extraction and the link-pick
# call (paid tier — the free tier's 20 requests/day/model can't support the
# get_events flow). Overridable so a model deprecation is an env change, not
# a deploy; when the two envs differ, quota/overload errors on one model
# fall back to the other.
EXTRACT_MODEL = os.environ.get("GEMINI_EXTRACT_MODEL", "gemini-3.1-flash-lite")
CLASSIFY_MODEL = os.environ.get("GEMINI_CLASSIFY_MODEL", "gemini-3.1-flash-lite")

MAX_MARKDOWN_CHARS = 60_000
MAX_IMAGES_PER_SITE = 8

# Free-tier quotas are per-minute; bound in-process burst so a batched
# get_events call doesn't trip 429s instantly. Two at a time spreads an
# 8-site batch's ~16 calls across the RPM window instead of slamming it.
_CONCURRENCY = asyncio.Semaphore(int(os.environ.get("GEMINI_MAX_CONCURRENCY", "2")))
MAX_ATTEMPTS = 4
# RPM windows ask to retry in ~27-60s. Waiting out ONE window in-call turns
# a quota burst into a slower success instead of a per-site error; anything
# beyond this is treated as a daily cap and fails fast.
MAX_RETRY_DELAY_S = 65.0

EVENT_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "name": {"type": "STRING", "description": "Event name."},
        "start_date": {"type": "STRING", "description": "YYYY-MM-DD, or empty."},
        "start_time": {"type": "STRING", "description": "HH:MM:SS 24-hour, or empty."},
        "location": {"type": "STRING"},
        "price": {"type": "STRING", "description": "USD price like '$19.99', or empty."},
        "event_title_derived": {"type": "STRING"},
        "event_description_derived": {"type": "STRING"},
        "keywords": {"type": "STRING", "description": "5 comma-separated keywords."},
        "emoji": {"type": "STRING", "description": "Single emoji."},
    },
    "required": [
        "name",
        "start_date",
        "start_time",
        "location",
        "price",
        "event_title_derived",
        "event_description_derived",
        "keywords",
        "emoji",
    ],
}

EVENTS_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {"events": {"type": "ARRAY", "items": EVENT_SCHEMA}},
    "required": ["events"],
}

EVENTS_PAGE_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "event_page_url": {
            "type": "STRING",
            "description": "Chosen event-page URL, or empty string if none fits.",
        }
    },
    "required": ["event_page_url"],
}

IDENTIFY_EVENTS_PAGE_PROMPT = """You are given the homepage URL of a place and a list of URL links found on it.

Task
Pick the one link most likely to list public events, calendars, shows, or things to do on specific dates.

Ignore
- Links whose main purpose is booking private events, weddings, catering, or corporate event space.
- Links for any school below the college/university level.

Return exactly one JSON object:

{"event_page_url": "<chosen event-page URL or empty string>"}

If no link fits, leave the field blank."""

EXTRACT_EVENTS_PROMPT = """You are provided data from a website expected to contain scheduled events.
Your objective is to generate a list of all events appearing on the website. For each event that appears
in the submission data, extract the following information:

name: Event name.
start_date: Event start date in format `YYYY-MM-DD`.
start_time: Event start time in 24-hour format `HH:MM:SS`.
location: The venue or specific location of the event if mentioned.
price: Event price in USD if mentioned, e.g. '$19.99'.
event_title_derived: A more descriptive event title (max 70 characters) that conveys the event's purpose to someone unfamiliar with the venue or event.
event_description_derived: A concise (max 250 character) and informative description. Preserve original details and enhance with relevant context if available. Do not duplicate other fields such at date, price, etc.
keywords: A comma-separated list of 5 salient keywords characterizing the event, e.g. "music, metal, bar, dance, dark".
emoji: Return a single emoji character which best summarizes the event.

Additional instructions:
- Today's date is {today}. Use this to infer dates, e.g. when only day-of-week and time are mentioned.
{date_hint}- If an event such as a festival occurs over several days (unbroken), repeat the event for up to three days.
- If an event is recurring, e.g. every Tuesday, return only its next upcoming occurence.
- Ignore events that have already happened. Event pages often list past/archived events below the upcoming ones — skip them.
- If an event is listed within a calendar, use the calendar to define its event date.
- Ignore all school events, except for colleges and universities.
- Ignore postings for private event spaces, as well as wedding, corporate, and catering events.
- Ignore Resy links and food menus.
- If an event field cannot be determined, LEAVE IT BLANK.
- Write all free-text fields (name, location, event_title_derived, event_description_derived, keywords) in the language '{language}' (BCP-47 code), translating from the page's language when necessary. Keep proper nouns (venue names, artist names) as-is.
- ONLY return events that appear in the data.
- DO NOT hallucinate events that don't exist.

Return the events as a JSON array named `events`."""


class GeminiError(RuntimeError):
    """Raised when a Gemini API call fails or returns an unparseable body."""


def _retry_delay_from(resp: httpx.Response) -> float | None:
    """Extract google.rpc.RetryInfo's retryDelay ('12s') from an error body."""
    try:
        for detail in resp.json()["error"]["details"]:
            if detail.get("@type", "").endswith("RetryInfo"):
                return float(detail["retryDelay"].rstrip("s"))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        pass
    return None


def _thinking_config(model: str) -> dict[str, Any]:
    """Minimal-thinking config for the given model generation.

    Gemini 2.5 models think by default and accept `thinkingBudget: 0`;
    Gemini 3+ replaced the budget with `thinkingLevel`. Either way, thinking
    silently costs seconds per call and extraction doesn't need it.
    """
    if model.startswith("gemini-2."):
        return {"thinkingBudget": 0}
    return {"thinkingLevel": "low"}


def _parse_structured(text: str) -> Any:
    """Parse structured-output JSON, salvaging a truncated events array.

    If generation is cut off at maxOutputTokens the JSON ends mid-object.
    For the {"events": [...]} shape we can drop the incomplete trailing
    object and close the array — losing one event beats losing the site.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        cut = text.rfind("},")
        if cut != -1:
            try:
                return json.loads(text[: cut + 1] + "]}")
            except json.JSONDecodeError:
                pass
        raise


async def generate_json(
    *,
    api_key: str,
    model: str,
    parts: list[dict[str, Any]],
    response_schema: dict[str, Any],
    timeout: float = 30.0,
) -> Any:
    """POST one generateContent call and return the parsed structured output.

    Retries 429/5xx/transport errors with backoff, honoring the retryDelay
    Gemini sends in 429 bodies; a server-requested delay beyond
    MAX_RETRY_DELAY_S means the quota window is exhausted, so fail fast with
    a clear message instead. `thinkingBudget: 0` is load-bearing: 2.5-flash
    models think by default, which silently costs seconds per call.
    """
    body = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": response_schema,
            "temperature": 0.0,
            # Busy venue calendars produce long event lists; 8192 proved too
            # small in the field (truncated mid-string → unparseable JSON).
            "maxOutputTokens": 32768,
            "thinkingConfig": _thinking_config(model),
        },
    }
    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
    url = GEMINI_GENERATE_URL.format(model=model)

    resp: httpx.Response | None = None
    for attempt in range(MAX_ATTEMPTS):
        last = attempt == MAX_ATTEMPTS - 1
        try:
            async with _CONCURRENCY:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(url, json=body, headers=headers)
        except httpx.TransportError as exc:
            if last:
                raise GeminiError(f"{model} transport error: {exc}") from exc
            await asyncio.sleep(1.5 * 2**attempt)
            continue
        if resp.status_code in (429, 500, 502, 503) and not last:
            delay = _retry_delay_from(resp) or 1.5 * 2**attempt
            if delay > MAX_RETRY_DELAY_S:
                raise GeminiError(
                    f"{model} quota exhausted (server asked to retry in "
                    f"{delay:.0f}s). Free-tier limits are per-minute and "
                    "per-day; try again later or switch models via "
                    "GEMINI_EXTRACT_MODEL/GEMINI_CLASSIFY_MODEL."
                )
            await asyncio.sleep(delay)
            continue
        break

    assert resp is not None
    if resp.status_code != 200:
        raise GeminiError(
            f"{model} returned {resp.status_code}: {resp.text[:300]}"
        )

    try:
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        return _parse_structured(text)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise GeminiError(f"unparseable {model} response: {exc}") from exc


async def _generate_with_fallback(
    *,
    api_key: str,
    primary: str,
    fallback: str,
    parts: list[dict[str, Any]],
    response_schema: dict[str, Any],
    timeout: float,
) -> Any:
    """Call the primary model, borrowing the fallback's quota if the primary's
    is exhausted. Free-tier quotas are per-model, so flash and flash-lite are
    independent buckets — one being drained shouldn't fail the tool call."""
    try:
        return await generate_json(
            api_key=api_key,
            model=primary,
            parts=parts,
            response_schema=response_schema,
            timeout=timeout,
        )
    except GeminiError as exc:
        # Quota exhaustion and persistent 503 overload are both per-model
        # conditions — the other model is an independent capacity pool.
        retryable = "quota exhausted" in str(exc) or "returned 503" in str(exc)
        if not retryable or fallback == primary:
            raise
        return await generate_json(
            api_key=api_key,
            model=fallback,
            parts=parts,
            response_schema=response_schema,
            timeout=timeout,
        )


async def identify_events_page(
    *,
    api_key: str,
    homepage: str,
    links: list[str],
    timeout: float = 10.0,
) -> str | None:
    """Pick the events-page URL from a homepage's links, or None if none fits."""
    parts = [
        {"text": IDENTIFY_EVENTS_PAGE_PROMPT},
        {"text": f"Homepage: {homepage}\nLinks:\n" + "\n".join(links)},
    ]
    result = await _generate_with_fallback(
        api_key=api_key,
        primary=CLASSIFY_MODEL,
        fallback=EXTRACT_MODEL,
        parts=parts,
        response_schema=EVENTS_PAGE_RESPONSE_SCHEMA,
        timeout=timeout,
    )
    url = (result or {}).get("event_page_url", "")
    return url.strip() or None


async def extract_events(
    *,
    api_key: str,
    markdown: str,
    images_webp_b64: list[str],
    today: str,
    date_hint: str | None = None,
    timeout: float = 45.0,
    language: str = "en",
) -> list[dict[str, Any]]:
    """Extract structured events from an events page's markdown + images.

    Translation happens here for free: the model reads the page in whatever
    language it's written in and writes the extracted fields in `language`.
    """
    hint = ""
    if date_hint:
        hint = f"- {date_hint}\n"
    prompt = EXTRACT_EVENTS_PROMPT.format(
        today=today, date_hint=hint, language=language
    )

    parts: list[dict[str, Any]] = [
        {"text": prompt},
        {
            "text": "Parse all events appearing in the following markdown:\n"
            + markdown[:MAX_MARKDOWN_CHARS]
        },
    ]
    for b64 in images_webp_b64[:MAX_IMAGES_PER_SITE]:
        parts.append({"inlineData": {"mimeType": "image/webp", "data": b64}})

    result = await _generate_with_fallback(
        api_key=api_key,
        primary=EXTRACT_MODEL,
        fallback=CLASSIFY_MODEL,
        parts=parts,
        response_schema=EVENTS_RESPONSE_SCHEMA,
        timeout=timeout,
    )
    events = (result or {}).get("events", [])
    return events if isinstance(events, list) else []
