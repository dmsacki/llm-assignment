import tempfile
from pathlib import Path
from unittest import mock

import pytest
import httpx

from backend.scraper import (
    _extract_main_text,
    _chunk_text,
    _is_allowed_by_robots
)
from backend.config import settings


def test_extract_main_text():
    html = """
    <html>
        <head><title>Test</title></head>
        <body>
            <header>This is header</header>
            <nav>This is nav</nav>
            <div class="main-content">
                <h1>Test Title</h1>
                <p>This is the main content paragraph.</p>
                <p>Another paragraph with more information.</p>
            </div>
            <footer>This is footer</footer>
        </body>
    </html>
    """
    text = _extract_main_text(html)
    assert "Test Title" in text
    assert "main content paragraph" in text
    assert "header" not in text
    assert "nav" not in text
    assert "footer" not in text


def test_chunk_text_simple():
    text = """
Test Section 1
This is some test content for the first section. It should be long enough to be a valid chunk.
    """.strip()
    chunks = _chunk_text(text, "http://example.com")
    assert len(chunks) == 1
    assert chunks[0]["title"] == "Test Section 1"
    assert "test content" in chunks[0]["content"]


def test_chunk_text_long_section():
    # Create a long section that should be split into multiple chunks
    long_word = "word " * 300  # Makes a very long string
    text = f"""
Long Section
{long_word}
    """.strip()
    
    # Override settings for test
    with mock.patch("backend.scraper.settings") as mock_settings:
        mock_settings.scraper_chunk_max_chars = 200
        mock_settings.scraper_chunk_min_chars = 50
        chunks = _chunk_text(text, "http://example.com")
        assert len(chunks) > 1  # Should be split into multiple chunks
        for chunk in chunks:
            assert len(chunk["content"]) <= 200
            assert len(chunk["content"]) >= 50


def test_chunk_text_too_short():
    text = """
Short Section
Too short.
    """.strip()
    with mock.patch("backend.scraper.settings") as mock_settings:
        mock_settings.scraper_chunk_min_chars = 100
        chunks = _chunk_text(text, "http://example.com")
        assert len(chunks) == 0


def test_robots_txt_check_disabled():
    with mock.patch("backend.scraper.settings") as mock_settings:
        mock_settings.scraper_check_robots_txt = False
        assert _is_allowed_by_robots("http://example.com/disallowed") is True


@pytest.mark.asyncio
async def test_scraper_integration():
    # Just a simple test to ensure the scraper can import and run basic functions
    # This test won't actually scrape the real site
    with mock.patch("backend.scraper._is_allowed_by_robots", return_value=False):
        from backend.scraper import scrape_all
        chunks = await scrape_all()
        # Since we mocked _is_allowed_by_robots to return False, chunks should be empty
        assert isinstance(chunks, list)