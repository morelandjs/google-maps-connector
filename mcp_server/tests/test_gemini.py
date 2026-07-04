import json

import httpx
import pytest
import respx

import gemini
from gemini import (
    CLASSIFY_MODEL,
    EVENTS_PAGE_RESPONSE_SCHEMA,
    EVENTS_RESPONSE_SCHEMA,
    EXTRACT_MODEL,
    GEMINI_GENERATE_URL,
    MAX_IMAGES_PER_SITE,
    MAX_MARKDOWN_CHARS,
    GeminiError,
    extract_events,
    generate_json,
    identify_events_page,
)

EXTRACT_URL = GEMINI_GENERATE_URL.format(model=EXTRACT_MODEL)
CLASSIFY_URL = GEMINI_GENERATE_URL.format(model=CLASSIFY_MODEL)


def _gemini_response(payload) -> httpx.Response:
    """Wrap a structured-output payload the way generateContent returns it."""
    return httpx.Response(
        200,
        json={
            "candidates": [
                {"content": {"parts": [{"text": json.dumps(payload)}]}}
            ]
        },
    )


@pytest.fixture
def no_retry_sleep(monkeypatch):
    async def _instant(_seconds):
        return None

    monkeypatch.setattr(gemini.asyncio, "sleep", _instant)


@respx.mock
async def test_generate_json_sends_schema_key_and_config():
    route = respx.post(EXTRACT_URL).mock(return_value=_gemini_response({"ok": True}))

    result = await generate_json(
        api_key="TEST_GEMINI_KEY",
        model=EXTRACT_MODEL,
        parts=[{"text": "hi"}],
        response_schema=EVENTS_RESPONSE_SCHEMA,
    )

    assert result == {"ok": True}
    req = route.calls.last.request
    assert req.headers["x-goog-api-key"] == "TEST_GEMINI_KEY"
    body = json.loads(req.content)
    config = body["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert config["responseSchema"] == EVENTS_RESPONSE_SCHEMA
    assert config["thinkingConfig"] == gemini._thinking_config(EXTRACT_MODEL)
    assert body["contents"][0]["parts"] == [{"text": "hi"}]


def test_thinking_config_is_model_generation_aware():
    # Gemini 2.5 wants thinkingBudget: 0; Gemini 3+ replaced it with levels.
    assert gemini._thinking_config("gemini-2.5-flash") == {"thinkingBudget": 0}
    assert gemini._thinking_config("gemini-3.1-flash-lite") == {
        "thinkingLevel": "low"
    }


@respx.mock
async def test_generate_json_retries_once_on_429(no_retry_sleep):
    route = respx.post(EXTRACT_URL).mock(
        side_effect=[
            httpx.Response(429, text="slow down"),
            _gemini_response({"ok": 1}),
        ]
    )
    result = await generate_json(
        api_key="K",
        model=EXTRACT_MODEL,
        parts=[{"text": "x"}],
        response_schema=EVENTS_RESPONSE_SCHEMA,
    )
    assert result == {"ok": 1}
    assert route.call_count == 2


@respx.mock
async def test_generate_json_raises_after_exhausting_retries(no_retry_sleep):
    route = respx.post(EXTRACT_URL).mock(
        return_value=httpx.Response(503, text="down")
    )
    with pytest.raises(GeminiError):
        await generate_json(
            api_key="K",
            model=EXTRACT_MODEL,
            parts=[{"text": "x"}],
            response_schema=EVENTS_RESPONSE_SCHEMA,
        )
    assert route.call_count == gemini.MAX_ATTEMPTS


def _quota_429(retry_delay: str) -> httpx.Response:
    return httpx.Response(
        429,
        json={
            "error": {
                "code": 429,
                "message": "You exceeded your current quota",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.RetryInfo",
                        "retryDelay": retry_delay,
                    }
                ],
            }
        },
    )


@respx.mock
async def test_generate_json_honors_server_retry_delay(monkeypatch):
    delays = []

    async def record_sleep(seconds):
        delays.append(seconds)

    monkeypatch.setattr(gemini.asyncio, "sleep", record_sleep)
    respx.post(EXTRACT_URL).mock(
        side_effect=[_quota_429("2s"), _gemini_response({"ok": 1})]
    )
    result = await generate_json(
        api_key="K",
        model=EXTRACT_MODEL,
        parts=[{"text": "x"}],
        response_schema=EVENTS_RESPONSE_SCHEMA,
    )
    assert result == {"ok": 1}
    assert delays == [2.0]


@respx.mock
async def test_generate_json_fails_fast_on_depleted_credits(no_retry_sleep):
    """A billing/credit-depletion 429 won't self-heal — raise immediately
    (no retries) with an actionable message, distinct from quota."""
    route = respx.post(EXTRACT_URL).mock(
        return_value=httpx.Response(
            429,
            json={
                "error": {
                    "code": 429,
                    "status": "RESOURCE_EXHAUSTED",
                    "message": "Your prepayment credits are depleted. Please "
                    "go to AI Studio to manage billing.",
                }
            },
        )
    )
    with pytest.raises(gemini.GeminiBillingError, match="credits are depleted"):
        await generate_json(
            api_key="K",
            model=EXTRACT_MODEL,
            parts=[{"text": "x"}],
            response_schema=EVENTS_RESPONSE_SCHEMA,
        )
    assert route.call_count == 1  # no wasted retries


@respx.mock
async def test_generate_json_fails_fast_when_quota_window_exhausted(no_retry_sleep):
    route = respx.post(EXTRACT_URL).mock(return_value=_quota_429("3600s"))
    with pytest.raises(GeminiError, match="quota exhausted"):
        await generate_json(
            api_key="K",
            model=EXTRACT_MODEL,
            parts=[{"text": "x"}],
            response_schema=EVENTS_RESPONSE_SCHEMA,
        )
    assert route.call_count == 1  # no pointless retries against a daily cap


@respx.mock
async def test_generate_json_raises_on_400_without_retry():
    route = respx.post(EXTRACT_URL).mock(
        return_value=httpx.Response(400, text="bad schema")
    )
    with pytest.raises(GeminiError):
        await generate_json(
            api_key="K",
            model=EXTRACT_MODEL,
            parts=[{"text": "x"}],
            response_schema=EVENTS_RESPONSE_SCHEMA,
        )
    assert route.call_count == 1


@respx.mock
async def test_generate_json_raises_on_malformed_candidate():
    respx.post(EXTRACT_URL).mock(
        return_value=httpx.Response(200, json={"candidates": []})
    )
    with pytest.raises(GeminiError):
        await generate_json(
            api_key="K",
            model=EXTRACT_MODEL,
            parts=[{"text": "x"}],
            response_schema=EVENTS_RESPONSE_SCHEMA,
        )


@pytest.fixture
def distinct_models(monkeypatch):
    """Fallback only exists when the two model envs differ; the defaults are
    now the same model, so tests pin two distinct ones."""
    monkeypatch.setattr(gemini, "EXTRACT_MODEL", "model-a")
    monkeypatch.setattr(gemini, "CLASSIFY_MODEL", "model-b")
    return (
        GEMINI_GENERATE_URL.format(model="model-a"),
        GEMINI_GENERATE_URL.format(model="model-b"),
    )


@respx.mock
async def test_extract_falls_back_to_classify_model_on_quota(
    no_retry_sleep, distinct_models
):
    """Distinct models have separate quota buckets — borrow the other
    model's quota instead of failing the tool call."""
    extract_url, classify_url = distinct_models
    respx.post(extract_url).mock(return_value=_quota_429("3600s"))
    fallback = respx.post(classify_url).mock(
        return_value=_gemini_response({"events": [{"name": "Jazz"}]})
    )
    events = await extract_events(
        api_key="K", markdown="md", images_webp_b64=[], today="2026-07-01"
    )
    assert events == [{"name": "Jazz"}]
    assert fallback.called


@respx.mock
async def test_extract_falls_back_on_persistent_503_overload(
    no_retry_sleep, distinct_models
):
    """'Model experiencing high demand' is per-model too — seen live when
    gemini-2.5-flash 503'd through all retries while flash-lite was fine."""
    extract_url, classify_url = distinct_models
    respx.post(extract_url).mock(return_value=httpx.Response(503, text="high demand"))
    fallback = respx.post(classify_url).mock(
        return_value=_gemini_response({"events": [{"name": "Jazz"}]})
    )
    events = await extract_events(
        api_key="K", markdown="md", images_webp_b64=[], today="2026-07-01"
    )
    assert events == [{"name": "Jazz"}]
    assert fallback.called


@respx.mock
async def test_no_fallback_when_models_identical(no_retry_sleep):
    """With one model configured, quota errors surface directly (no
    pointless self-retry against the same bucket)."""
    route = respx.post(EXTRACT_URL).mock(return_value=_quota_429("3600s"))
    with pytest.raises(GeminiError, match="quota exhausted"):
        await extract_events(
            api_key="K", markdown="md", images_webp_b64=[], today="2026-07-01"
        )
    assert route.call_count == 1


@respx.mock
async def test_identify_events_page_returns_url():
    route = respx.post(CLASSIFY_URL).mock(
        return_value=_gemini_response(
            {"event_page_url": "https://venue.test/events"}
        )
    )
    url = await identify_events_page(
        api_key="K",
        homepage="https://venue.test",
        links=["https://venue.test/menu", "https://venue.test/events"],
    )
    assert url == "https://venue.test/events"
    body = json.loads(route.calls.last.request.content)
    assert body["generationConfig"]["responseSchema"] == EVENTS_PAGE_RESPONSE_SCHEMA
    assert "https://venue.test/events" in body["contents"][0]["parts"][1]["text"]


@respx.mock
async def test_identify_events_page_returns_none_on_blank():
    respx.post(CLASSIFY_URL).mock(
        return_value=_gemini_response({"event_page_url": "  "})
    )
    url = await identify_events_page(
        api_key="K", homepage="https://venue.test", links=["https://venue.test/menu"]
    )
    assert url is None


@respx.mock
async def test_extract_events_truncates_markdown_and_caps_images():
    route = respx.post(EXTRACT_URL).mock(
        return_value=_gemini_response({"events": [{"name": "Jazz Night"}]})
    )
    events = await extract_events(
        api_key="K",
        markdown="m" * (MAX_MARKDOWN_CHARS + 5000),
        images_webp_b64=["QUJD"] * (MAX_IMAGES_PER_SITE + 4),
        today="2026-07-01",
        date_hint="Prioritize events between 2026-07-04 and 2026-07-05.",
    )
    assert events == [{"name": "Jazz Night"}]

    body = json.loads(route.calls.last.request.content)
    parts = body["contents"][0]["parts"]
    # prompt + markdown + capped images
    assert len(parts) == 2 + MAX_IMAGES_PER_SITE
    assert "2026-07-01" in parts[0]["text"]
    assert "Prioritize events between" in parts[0]["text"]
    assert len(parts[1]["text"]) <= MAX_MARKDOWN_CHARS + 100
    assert parts[2]["inlineData"]["mimeType"] == "image/webp"


@respx.mock
async def test_generate_json_salvages_truncated_events_array():
    """Generation cut off at maxOutputTokens → drop the partial trailing event."""
    truncated = (
        '{"events": [{"name": "Complete Event"}, {"name": "Cut off mid-str'
    )
    respx.post(EXTRACT_URL).mock(
        return_value=httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": truncated}]}}]},
        )
    )
    result = await generate_json(
        api_key="K",
        model=EXTRACT_MODEL,
        parts=[{"text": "x"}],
        response_schema=EVENTS_RESPONSE_SCHEMA,
    )
    assert result == {"events": [{"name": "Complete Event"}]}


@respx.mock
async def test_extract_events_requests_output_in_configured_language():
    """Paris venue, English user: the prompt must direct translation."""
    route = respx.post(EXTRACT_URL).mock(
        return_value=_gemini_response({"events": []})
    )
    await extract_events(
        api_key="K",
        markdown="## Concert de jazz\nvendredi 10 juillet",
        images_webp_b64=[],
        today="2026-07-04",
        language="en",
    )
    prompt = json.loads(route.calls.last.request.content)["contents"][0]["parts"][0][
        "text"
    ]
    assert "in the language 'en'" in prompt
    assert "translating from the page's language" in prompt


@respx.mock
async def test_extract_events_returns_empty_list_on_missing_events():
    respx.post(EXTRACT_URL).mock(return_value=_gemini_response({"events": "junk"}))
    events = await extract_events(
        api_key="K", markdown="md", images_webp_b64=[], today="2026-07-01"
    )
    assert events == []
