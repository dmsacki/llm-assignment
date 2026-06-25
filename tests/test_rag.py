import tempfile
from pathlib import Path
from unittest import mock

import pytest

import backend.rag
from backend.rag import load_faq_chunks, retrieve_relevant_chunks


@pytest.fixture(autouse=True)
def reset_rag_caches():
    """Fixture to reset RAG global caches before and after each test."""
    original_faq_cache = backend.rag._FAQ_CHUNKS_CACHE
    original_scraped_cache = backend.rag._SCRAPED_CHUNKS_CACHE
    backend.rag._FAQ_CHUNKS_CACHE = None
    backend.rag._SCRAPED_CHUNKS_CACHE = None
    yield
    backend.rag._FAQ_CHUNKS_CACHE = original_faq_cache
    backend.rag._SCRAPED_CHUNKS_CACHE = original_scraped_cache


@pytest.fixture
def temp_faq_file():
    """Fixture to create a temporary FAQ markdown file for testing."""
    faq_content = """
## Course Registration
- Course registration is done through ARIS 3.

## Examination Rules
- Exam rules are strict.

## Library Services
- Library is open Monday to Friday.

## ICT Support
- Contact ICT helpdesk for issues.

## Hostel Application
- Apply for hostels via USAB.

## Fee Payment
- Pay fees via ARIS 3.

## Academic Calendar
- Two semesters per year.

## Student Conduct
- Follow the student by-laws.
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(faq_content)
        temp_path = Path(f.name)
    yield temp_path
    temp_path.unlink()


def test_load_faq_chunks_parses_sections_correctly(temp_faq_file):
    with mock.patch("backend.rag.settings") as mock_settings:
        mock_settings.resolved_faq_path.return_value = temp_faq_file
        chunks = load_faq_chunks()
        assert len(chunks) == 8
        titles = {chunk["title"] for chunk in chunks}
        assert "Course Registration" in titles
        assert "Library Services" in titles


def test_retrieve_relevant_chunks_returns_library_services_for_library_question(temp_faq_file):
    with mock.patch("backend.rag.settings") as mock_settings:
        mock_settings.resolved_faq_path.return_value = temp_faq_file
        mock_settings.resolved_scraper_cache_path.return_value = Path(tempfile.mkdtemp()) / "nonexistent.json"
        chunks = retrieve_relevant_chunks("What are the library hours and borrowing rules?")
        assert chunks
        assert any(chunk["title"] == "Library Services" for chunk in chunks)


def test_retrieve_relevant_chunks_returns_hostel_application_for_hostel_question(temp_faq_file):
    with mock.patch("backend.rag.settings") as mock_settings:
        mock_settings.resolved_faq_path.return_value = temp_faq_file
        mock_settings.resolved_scraper_cache_path.return_value = Path(tempfile.mkdtemp()) / "nonexistent.json"
        chunks = retrieve_relevant_chunks("How do I apply for hostel accommodation?")
        assert chunks
        assert any(chunk["title"] == "Hostel Application" for chunk in chunks)


def test_retrieve_relevant_chunks_returns_empty_for_unrelated_question(temp_faq_file):
    with mock.patch("backend.rag.settings") as mock_settings:
        mock_settings.resolved_faq_path.return_value = temp_faq_file
        mock_settings.resolved_scraper_cache_path.return_value = Path(tempfile.mkdtemp()) / "nonexistent.json"
        chunks = retrieve_relevant_chunks("What is the weather like on Mars?")
        assert chunks == []


def test_retrieve_relevant_chunks_handles_synonyms_like_myuni(temp_faq_file):
    # 'myuni' is a common user term; ensure synonym mapping finds ARIS3/course registration
    with mock.patch("backend.rag.settings") as mock_settings:
        mock_settings.resolved_faq_path.return_value = temp_faq_file
        mock_settings.resolved_scraper_cache_path.return_value = Path(tempfile.mkdtemp()) / "nonexistent.json"
        chunks = retrieve_relevant_chunks("How do I register using myuni?")
        assert chunks
        assert any(chunk["title"] == "Course Registration" for chunk in chunks)


def test_retrieve_relevant_chunks_returns_hostel_info_for_coict_query(temp_faq_file):
    # CoICT hostel pricing query should return Hostel Application chunk
    with mock.patch("backend.rag.settings") as mock_settings:
        mock_settings.resolved_faq_path.return_value = temp_faq_file
        mock_settings.resolved_scraper_cache_path.return_value = Path(tempfile.mkdtemp()) / "nonexistent.json"
        chunks = retrieve_relevant_chunks("I want the exact price for CoICT hostels")
        assert chunks
        assert any(chunk["title"] == "Hostel Application" for chunk in chunks)
