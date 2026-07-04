"""Playwright scraping helpers for `get_events`.

Ported from stealth-search's src/etl/browser_utils.py with two deliberate
changes for the Cloud Run runtime:

- headless=True with --no-sandbox: Chromium's own sandbox cannot start inside
  Cloud Run's gVisor sandbox, and there is no display server. Stealth-search
  ran a visible browser as an anti-bot tactic; here bot-walled sites are
  detected (CloudflareBlocked) and reported to the caller instead.
- Failures raise instead of logging-and-returning-empty, so the pipeline can
  attach a per-place status to every candidate.
"""

from __future__ import annotations

import asyncio
import base64
import io
import re
from contextlib import asynccontextmanager
from typing import AsyncIterator
from urllib.parse import parse_qs, urlparse

import httpx
import html2text
from PIL import Image
from playwright.async_api import BrowserContext, async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeout

# One modern, plausible UA. A randomized-UA dependency isn't worth it at
# ~10 sites per call.
CHROME_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

BROWSER_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
]

ALLOWED_IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
DISALLOWED_IMAGE_DOMAINS = {"lh3.googleusercontent.com"}
MAX_IMAGE_SIZE_BYTES = 20 * 1024**2
MAX_IMAGE_URL_WIDTH = 5000
IMAGE_THUMBNAIL_DIM = 512
CLOUDFLARE_TIMEOUT_MS = 15000

DATA_URI_IMG_RE = re.compile(
    r'<img\b[^>]*src=["\']data:[^"\']+["\'][^>]*>', flags=re.IGNORECASE
)


class CloudflareBlocked(RuntimeError):
    """The page is stuck behind a bot-challenge interstitial."""


# Title fragments of known bot-challenge interstitials (Cloudflare and
# friends). Many auto-pass after a few seconds even headlessly — the waiter
# below polls until the title changes, and only raises if it never does.
CHALLENGE_TITLE_PATTERNS = (
    "robot challenge screen",
    "just a moment",
    "checking your browser",
    "attention required",
    "verify you are human",
)


@asynccontextmanager
async def browser_context() -> AsyncIterator[BrowserContext]:
    """Launch one headless Chromium and yield a context configured for scraping."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=BROWSER_ARGS)
        context = await browser.new_context(
            user_agent=CHROME_UA,
            java_script_enabled=True,
            bypass_csp=True,
            accept_downloads=False,
        )
        try:
            yield context
        finally:
            try:
                await context.close()
                await browser.close()
            except Exception:
                pass  # already closed due to crash


async def _wait_out_cloudflare(page) -> None:
    """Wait for a bot-challenge interstitial to clear; raise if it never does."""
    try:
        await page.wait_for_function(
            """(patterns) => {
                const title = document.title.toLowerCase();
                return !patterns.some(p => title.includes(p));
            }""",
            arg=list(CHALLENGE_TITLE_PATTERNS),
            timeout=CLOUDFLARE_TIMEOUT_MS,
        )
        await page.wait_for_load_state("domcontentloaded", timeout=1000)
    except PlaywrightTimeout:
        title = (await page.title()).lower()
        if any(p in title for p in CHALLENGE_TITLE_PATTERNS):
            raise CloudflareBlocked(page.url) from None


async def extract_links(context: BrowserContext, page_url: str) -> list[str]:
    """Harvest every anchor href from a page (deduped, order not guaranteed)."""
    page = await context.new_page()
    try:
        await page.goto(page_url, wait_until="domcontentloaded", timeout=10000)
        await _wait_out_cloudflare(page)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(500)
        links = await page.evaluate(
            "() => Array.from(document.querySelectorAll('a[href]')).map(a => a.href)"
        )
        return list(set(links))
    finally:
        await page.close()


async def extract_markdown_and_images(
    context: BrowserContext, url: str, max_images: int = 100
) -> tuple[str, list[str]]:
    """Render a page to markdown plus the image URLs found on it.

    Image URLs are unvalidated here; callers filter with validate_image_url /
    download_and_downscale_image.
    """
    page = await context.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=10000)
        await _wait_out_cloudflare(page)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(1000)

        html = await page.content()
        html = DATA_URI_IMG_RE.sub("", html)

        text_maker = html2text.HTML2Text()
        text_maker.ignore_links = True
        markdown = text_maker.handle(html)

        image_urls = await page.evaluate(
            "() => Array.from(document.images).map(img => img.src)"
        )
        return markdown, list(dict.fromkeys(image_urls))[:max_images]
    finally:
        await page.close()


async def validate_image_url(url: str, client: httpx.AsyncClient) -> bool:
    """HEAD-check that a URL points to a usable, reasonably sized image."""
    parsed = urlparse(url)
    if parsed.netloc in DISALLOWED_IMAGE_DOMAINS or url.startswith("data:"):
        return False

    widths = parse_qs(parsed.query).get("w") or []
    if any(int(w) > MAX_IMAGE_URL_WIDTH for w in widths if w.isdigit()):
        return False

    try:
        resp = await client.head(url, headers={"User-Agent": CHROME_UA})
        if resp.status_code != 200:
            return False
        if resp.headers.get("Content-Type", "").lower().split(";")[0] not in (
            ALLOWED_IMAGE_MIME_TYPES
        ):
            return False
        clen = resp.headers.get("Content-Length")
        if clen and int(clen) > MAX_IMAGE_SIZE_BYTES:
            return False
        return True
    except (httpx.HTTPError, ValueError):
        return False


def _downscale_to_webp(data: bytes) -> bytes:
    image = Image.open(io.BytesIO(data))
    image.thumbnail((IMAGE_THUMBNAIL_DIM, IMAGE_THUMBNAIL_DIM), Image.LANCZOS)
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA")
    out = io.BytesIO()
    image.save(out, format="WEBP", quality=85)
    return out.getvalue()


async def download_and_downscale_image(
    url: str, client: httpx.AsyncClient
) -> str | None:
    """Fetch an image and return it as base64 WebP (≤512px), or None on failure."""
    try:
        resp = await client.get(url, headers={"User-Agent": CHROME_UA})
        if resp.status_code != 200:
            return None
        webp = await asyncio.to_thread(_downscale_to_webp, resp.content)
        return base64.b64encode(webp).decode("ascii")
    except Exception:
        return None
