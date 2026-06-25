import asyncio
import json
import re
import urllib.robotparser
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from backend.config import settings
from backend.logging_config import get_logger

logger = get_logger()

_URL_MAP: Dict[str, List[str]] = {
    "course_registration": [
        "https://www.udsm.ac.tz/directorate-undergraduate-studies",
        "https://www.udsm.ac.tz/directorate-postgraduate-studies",
    ],
    "exams": [
        "https://www.udsm.ac.tz/directorate-undergraduate-studies",
    ],
    "library": [
        "https://www.udsm.ac.tz/udsm-library",
    ],
    "ict": [
        "https://www.udsm.ac.tz/directorate-ict",
        "https://www.udsm.ac.tz/it-Services",
    ],
    "hostel": [
        "https://www.udsm.ac.tz/directorate-students-services",
    ],
    "fees": [
        "https://www.udsm.ac.tz/directorate-finance",
    ],
    "calendar": [
        "https://www.udsm.ac.tz/undergraduate",
    ],
    "student_conduct": [
        "https://www.udsm.ac.tz/udsm-policies-and-guidelinesinstruments",
        "https://www.udsm.ac.tz/directorate-students-services",
        "https://www.udsm.ac.tz/counselling-unit",
    ],
}

# Cache for robots.txt parsers
_robots_parsers: Dict[str, urllib.robotparser.RobotFileParser] = {}


def _get_robots_parser(base_url: str) -> Optional[urllib.robotparser.RobotFileParser]:
    """Get or create a robots.txt parser for a given base URL."""
    if base_url in _robots_parsers:
        return _robots_parsers[base_url]

    robots_url = urljoin(base_url, "/robots.txt")
    parser = urllib.robotparser.RobotFileParser()

    try:
        parser.set_url(robots_url)
        parser.read()
        _robots_parsers[base_url] = parser
        logger.info("Loaded robots.txt from %s", robots_url)
        return parser
    except Exception as exc:
        logger.warning("Failed to load robots.txt from %s: %s", robots_url, exc)
        # If robots.txt can't be loaded, return None and let the caller decide
        return None


def _is_allowed_by_robots(url: str) -> bool:
    """Check if scraping a URL is allowed by robots.txt."""
    if not settings.scraper_check_robots_txt:
        return True

    parsed_url = urlparse(url)
    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
    parser = _get_robots_parser(base_url)

    if parser is None:
        # If we couldn't load robots.txt, err on the side of caution
        logger.warning("Could not check robots.txt for %s, scraping anyway", url)
        return True

    allowed = parser.can_fetch("*", url)
    if not allowed:
        logger.info("Scraping %s is disallowed by robots.txt", url)
    return allowed


def _extract_main_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(["script", "style", "nav", "header", "footer", "noscript"]):
        tag.decompose()

    for selector in [
        "div.topbar",
        "div.slideshow_content",
        "div.gva-navigation",
        "div.after-offcanvas",
        "div.footer",
        "ul.inline",
    ]:
        for el in soup.select(selector):
            el.decompose()

    main = soup.select_one(
        "div.main-content, "  # generic Drupal
        "div.block-content, "
        "div.content.block-content, "
        "div.region-content"
    )

    if main is None:
        main = soup.select_one("div[role='main']") or soup.body

    if main is None:
        return ""

    text = main.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _chunk_text(text: str, source_url: str) -> List[Dict[str, str]]:
    """Improved chunking function with configurable limits and better splitting."""
    chunks: List[Dict[str, str]] = []

    # Split into potential section-based chunks first
    section_chunks = re.split(r"\n(?=[A-Z][A-Za-z0-9\s\-_,;:.]{2,100}\n)", text)

    for section in section_chunks:
        section = section.strip()
        if not section:
            continue

        lines = section.split("\n")
        title = lines[0].strip()[:120] if lines else "Untitled"
        content = "\n".join(line.strip() for line in lines if line.strip()).strip()

        # Check if content needs to be split further into max_chars chunks
        if len(content) > settings.scraper_chunk_max_chars:
            # Split into multiple chunks respecting word boundaries
            words = content.split()
            current_chunk = []
            current_length = 0

            for word in words:
                word_length = len(word) + 1  # +1 for space
                if current_length + word_length > settings.scraper_chunk_max_chars:
                    if current_chunk:
                        chunk_content = " ".join(current_chunk).strip()
                        if len(chunk_content) >= settings.scraper_chunk_min_chars:
                            chunks.append({
                                "title": title,
                                "content": chunk_content,
                                "source_url": source_url,
                            })
                    current_chunk = [word]
                    current_length = len(word)
                else:
                    current_chunk.append(word)
                    current_length += word_length

            # Add the last chunk
            if current_chunk:
                chunk_content = " ".join(current_chunk).strip()
                if len(chunk_content) >= settings.scraper_chunk_min_chars:
                    chunks.append({
                        "title": title,
                        "content": chunk_content,
                        "source_url": source_url,
                    })
        else:
            if len(content) >= settings.scraper_chunk_min_chars:
                chunks.append({
                    "title": title,
                    "content": content,
                    "source_url": source_url,
                })

    return chunks


async def _fetch_with_retry(
    client: httpx.AsyncClient,
    url: str,
    max_retries: int,
    backoff_factor: float
) -> Optional[httpx.Response]:
    """Fetch a URL with retries and exponential backoff."""
    retry_count = 0

    while retry_count <= max_retries:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as exc:
            # Retry on 5xx errors, don't retry on 4xx
            if 500 <= exc.response.status_code < 600 and retry_count < max_retries:
                retry_count += 1
                wait_time = backoff_factor * (2 ** (retry_count - 1))
                logger.warning(
                    "HTTP error %s for %s, retrying in %ss (attempt %d/%d)",
                    exc.response.status_code, url, wait_time, retry_count, max_retries
                )
                await asyncio.sleep(wait_time)
            else:
                logger.error("HTTP error %s for %s: %s", exc.response.status_code, url, exc)
                raise
        except (httpx.RequestError, httpx.TimeoutException) as exc:
            if retry_count < max_retries:
                retry_count += 1
                wait_time = backoff_factor * (2 ** (retry_count - 1))
                logger.warning(
                    "Request failed for %s, retrying in %ss (attempt %d/%d): %s",
                    url, wait_time, retry_count, max_retries, exc
                )
                await asyncio.sleep(wait_time)
            else:
                logger.error("Request failed for %s after %d retries: %s", url, max_retries, exc)
                raise

    return None


async def scrape_all() -> List[Dict[str, str]]:
    all_chunks: List[Dict[str, str]] = []

    async with httpx.AsyncClient(
        timeout=settings.scraper_timeout_seconds,
        follow_redirects=True,
        headers={"User-Agent": "UDSM-Support-Assistant/1.0"},
    ) as client:
        seen_urls: set = set()
        tasks = []
        for domain, urls in _URL_MAP.items():
            for url in urls:
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                tasks.append((domain, url))

        # Semaphore to limit concurrent requests (optional but good practice)
        concurrency_sem = asyncio.Semaphore(5)

        async def fetch(domain: str, url: str):
            async with concurrency_sem:
                try:
                    # Check robots.txt first
                    if not _is_allowed_by_robots(url):
                        logger.warning("Skipping %s: disallowed by robots.txt", url)
                        return []

                    # Add delay between requests
                    if settings.scraper_delay_seconds > 0:
                        await asyncio.sleep(settings.scraper_delay_seconds)

                    logger.info("Starting to scrape %s", url)
                    resp = await _fetch_with_retry(
                        client,
                        url,
                        settings.scraper_max_retries,
                        settings.scraper_backoff_factor
                    )

                    if resp is None:
                        return []

                    text = _extract_main_text(resp.text)
                    chunks = _chunk_text(text, url)
                    for c in chunks:
                        c["domain"] = domain
                    logger.info("Scraped %s (%s) → %d chunks", url, domain, len(chunks))
                    return chunks
                except Exception as exc:
                    logger.warning("Failed to scrape %s: %s", url, exc, exc_info=True)
                    return []

        results = await asyncio.gather(*[fetch(domain, url) for domain, url in tasks])
        for result in results:
            all_chunks.extend(result)

    return all_chunks


def save_cache(chunks: List[Dict[str, str]]) -> None:
    path = settings.resolved_scraper_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(chunks, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Saved %d chunks to cache at %s", len(chunks), path)


async def scrape_and_cache() -> List[Dict[str, str]]:
    chunks = await scrape_all()
    save_cache(chunks)
    return chunks