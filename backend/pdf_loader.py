import re
from pathlib import Path
from typing import Dict, List

import fitz  # PyMuPDF

from backend.config import settings
from backend.logging_config import get_logger

logger = get_logger()

# Cache PDF chunks so we don't reprocess every time
_pdf_chunks_cache: List[Dict[str, str]] | None = None


def _extract_text_from_pdf(pdf_path: Path) -> str:
    """Extract clean text from a PDF file using PyMuPDF (WITHOUT page markers)."""
    text = ""
    try:
        doc = fitz.open(pdf_path)
        for page_num, page in enumerate(doc, 1):
            page_text = page.get_text("text")
            # Clean up text: normalize whitespace, remove extra newlines
            page_text = re.sub(r"\n{3,}", "\n\n", page_text)
            page_text = re.sub(r"[ \t]+", " ", page_text)
            # Don't add page markers - we want continuous text!
            text += f"\n{page_text}"
        page_count = len(doc)
        doc.close()
        logger.info("Extracted text from %s (%d pages)", pdf_path.name, page_count)
    except Exception as exc:
        logger.error("Failed to extract text from %s: %s", pdf_path, exc, exc_info=True)
        return ""
    return text


def _chunk_pdf_text(text: str, pdf_name: str) -> List[Dict[str, str]]:
    """Super simple PDF chunking: split into ~max_chars char chunks on double newlines."""
    all_chunks: List[Dict[str, str]] = []
    
    # Split into paragraphs (split on double newlines)
    paragraphs = re.split(r"\n{2,}", text)
    current_chunk = []
    current_length = 0
    part = 1
    
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
            
        para_length = len(para) + 2  # +2 for the double newlines
        
        if current_length + para_length > settings.scraper_chunk_max_chars and current_chunk:
            # Make chunk
            chunk_content = "\n\n".join(current_chunk)
            # Find first line of chunk as title
            first_line = chunk_content.split("\n")[0].strip()
            title = first_line[:120] if first_line else f"{pdf_name} - Section {part}"
            all_chunks.append({
                "title": title,
                "content": chunk_content,
                "source": pdf_name,
            })
            part += 1
            current_chunk = [para]
            current_length = len(para)
        else:
            current_chunk.append(para)
            current_length += para_length
    
    # Add the last chunk
    if current_chunk:
        chunk_content = "\n\n".join(current_chunk)
        first_line = chunk_content.split("\n")[0].strip()
        title = first_line[:120] if first_line else f"{pdf_name} - Section {part}"
        all_chunks.append({
            "title": title,
            "content": chunk_content,
            "source": pdf_name,
        })
    
    return all_chunks


def reset_pdf_cache():
    """Reset the PDF chunks cache to force reloading."""
    global _pdf_chunks_cache
    _pdf_chunks_cache = None
    logger.info("PDF cache has been reset")


def load_pdf_chunks() -> List[Dict[str, str]]:
    """Load and chunk all PDF files from the configured PDF directory."""
    global _pdf_chunks_cache
    if _pdf_chunks_cache is not None:
        logger.info("Returning cached PDF chunks (%d chunks)", len(_pdf_chunks_cache))
        return _pdf_chunks_cache

    pdf_dir = settings.resolved_pdf_directory()
    if not pdf_dir.exists():
        logger.info("PDF directory %s does not exist, creating it", pdf_dir)
        pdf_dir.mkdir(parents=True, exist_ok=True)
        _pdf_chunks_cache = []
        return _pdf_chunks_cache

    all_chunks: List[Dict[str, str]] = []
    pdf_files = list(pdf_dir.glob("*.pdf"))

    if not pdf_files:
        logger.info("No PDF files found in %s", pdf_dir)
        _pdf_chunks_cache = []
        return _pdf_chunks_cache

    logger.info("Found %d PDF file(s) in %s", len(pdf_files), pdf_dir)

    for pdf_path in pdf_files:
        pdf_text = _extract_text_from_pdf(pdf_path)
        if pdf_text:
            pdf_chunks = _chunk_pdf_text(pdf_text, pdf_path.name)
            all_chunks.extend(pdf_chunks)
            logger.info("Created %d chunks from %s", len(pdf_chunks), pdf_path.name)

    _pdf_chunks_cache = all_chunks
    logger.info("Total PDF chunks loaded: %d", len(_pdf_chunks_cache))
    return _pdf_chunks_cache
