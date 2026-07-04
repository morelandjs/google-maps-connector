"""Scraper tests against local fixture HTML via file:// URLs — no network.

These launch a real headless Chromium, so they skip automatically when the
Playwright browser isn't installed (`playwright install chromium`), mirroring
the RUN_LIVE_TESTS gating pattern.
"""

import base64
import io
from pathlib import Path

import httpx
import pytest

import scraper

FIXTURES = Path(__file__).parent / "fixtures" / "venue_site"


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            return Path(p.chromium.executable_path).exists()
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _chromium_available(),
    reason="Playwright Chromium not installed (run: playwright install chromium)",
)


def _file_url(name: str) -> str:
    return (FIXTURES / name).as_uri()


# Function-scoped on purpose: a module-scoped async fixture runs on a
# different event loop than the tests under pytest-asyncio's auto mode, and
# cross-loop Playwright calls hang forever.
@pytest.fixture
async def context():
    async with scraper.browser_context() as ctx:
        yield ctx


async def test_extract_links_harvests_all_anchors(context):
    links = await scraper.extract_links(context, _file_url("index.html"))
    assert any(link.endswith("events.html") for link in links)
    assert any(link.endswith("menu.html") for link in links)
    assert any("external.example.com" in link for link in links)
    assert any(link.startswith("mailto:") for link in links)


async def test_extract_markdown_and_images(context):
    markdown, image_urls = await scraper.extract_markdown_and_images(
        context, _file_url("events.html")
    )
    assert "Jazz Night with the Fixture Quartet" in markdown
    assert "Comedy Open Mic" in markdown
    # data-URI images are stripped from the HTML before markdown conversion
    assert "base64" not in markdown
    # document.images still reports the real poster
    assert any(url.endswith("poster.png") for url in image_urls)


@pytest.mark.parametrize(
    "fixture", ["cloudflare.html", "checking_browser.html"]
)
async def test_challenge_page_raises(context, monkeypatch, fixture):
    monkeypatch.setattr(scraper, "CLOUDFLARE_TIMEOUT_MS", 500)
    with pytest.raises(scraper.CloudflareBlocked):
        await scraper.extract_links(context, _file_url(fixture))


async def test_validate_image_url_rules():
    async with httpx.AsyncClient() as client:
        assert not await scraper.validate_image_url("data:image/png;base64,xx", client)
        assert not await scraper.validate_image_url(
            "https://lh3.googleusercontent.com/img.png", client
        )
        assert not await scraper.validate_image_url(
            "https://cdn.test/img.png?w=9000", client
        )


async def test_download_and_downscale_image(monkeypatch):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (2000, 1000), color=(200, 30, 30)).save(buf, format="PNG")
    png_bytes = buf.getvalue()

    async def fake_get(self, url, **kwargs):
        return httpx.Response(200, content=png_bytes)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    async with httpx.AsyncClient() as client:
        b64 = await scraper.download_and_downscale_image(
            "https://cdn.test/poster.png", client
        )

    assert b64 is not None
    webp = Image.open(io.BytesIO(base64.b64decode(b64)))
    assert webp.format == "WEBP"
    assert max(webp.size) <= scraper.IMAGE_THUMBNAIL_DIM


async def test_download_returns_none_on_http_error(monkeypatch):
    async def fake_get(self, url, **kwargs):
        return httpx.Response(404)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    async with httpx.AsyncClient() as client:
        assert (
            await scraper.download_and_downscale_image("https://cdn.test/x.png", client)
            is None
        )
