import re
from pathlib import Path
from typing import Dict, List

from backend.config import settings
from backend.logging_config import get_logger
from backend.pdf_loader import load_pdf_chunks

logger = get_logger()

_FAQ_CHUNKS_CACHE: List[Dict[str, str]] | None = None
_SCRAPED_CHUNKS_CACHE: List[Dict[str, str]] | None = None

_STOPWORDS = {
    "the", "and", "or", "is", "a", "an", "to", "of", "for", "in",
    "on", "at", "by", "with", "from", "that", "this", "as", "are",
    "be", "was", "were", "i", "we", "you", "he", "she", "it", "they",
    "me", "my", "your", "his", "her", "its", "our", "their",
    "what", "who", "whom", "which", "where", "when", "why", "how",
    "if", "then", "than", "so", "do", "does", "did", "done",
    "has", "have", "had", "can", "could", "will", "would", "shall",
    "should", "may", "might", "must", "not", "no", "nor",
}

_SYNONYMS = {
    "myuni": "aris3",
    "my-uni": "aris3",
    "aris": "aris3",
    "aris3": "aris3",
    "fee": "fees",
    "fees": "fees",
    "tuition": "tuition",
    "course": "course",
    "courses": "course",
    "program": "program",
    "programs": "program",
    "exam": "examination",
    "exams": "examination",
    "cheat": "cheating",
    "miss": "misses",
    "overdue": "fine",
    "book": "books",
    "register": "registration",
    "registered": "registration",
    "enroll": "registration",
    "enrol": "registration",
    "enrollment": "registration",
}


def _normalize_token(token: str) -> str:
    token = token.lower()
    normalized = _SYNONYMS.get(token, token)
    if normalized != token:
        return normalized
    if normalized.endswith("s") and len(normalized) > 3:
        normalized = normalized[:-1]
    return _SYNONYMS.get(normalized, normalized)


def _tokenize(text: str) -> List[str]:
    raw = re.split(r"[^a-z0-9]+", text.lower())
    tokens: List[str] = []
    for t in raw:
        if not t:
            continue
        norm = _normalize_token(t)
        if norm and norm not in _STOPWORDS:
            tokens.append(norm)
    return tokens


def load_scraped_chunks() -> List[Dict[str, str]]:
    global _SCRAPED_CHUNKS_CACHE
    if _SCRAPED_CHUNKS_CACHE is not None:
        logger.info("Returning cached scraped chunks (%d chunks)", len(_SCRAPED_CHUNKS_CACHE))
        return _SCRAPED_CHUNKS_CACHE

    path = settings.resolved_scraper_cache_path()
    if not path.exists():
        _SCRAPED_CHUNKS_CACHE = []
        logger.info("No scraped chunks found at %s", path)
        return _SCRAPED_CHUNKS_CACHE

    import json
    data = json.loads(path.read_text(encoding="utf-8"))
    for c in data:
        c.pop("source_url", None)
    _SCRAPED_CHUNKS_CACHE = data
    logger.info("Loaded %d scraped chunks", len(_SCRAPED_CHUNKS_CACHE))
    return _SCRAPED_CHUNKS_CACHE


def load_faq_chunks() -> List[Dict[str, str]]:
    global _FAQ_CHUNKS_CACHE
    if _FAQ_CHUNKS_CACHE is not None:
        logger.info("Returning cached FAQ chunks (%d chunks)", len(_FAQ_CHUNKS_CACHE))
        return _FAQ_CHUNKS_CACHE

    path = settings.resolved_faq_path()
    text = Path(path).read_text(encoding="utf-8")

    sections = re.split(r"^##\s+", text, flags=re.MULTILINE)
    chunks: List[Dict[str, str]] = []

    for section in sections[1:]:
        lines = section.strip().splitlines()
        if not lines:
            continue
        title = lines[0].strip()
        content = "\n".join(line.rstrip() for line in lines[1:]).strip()
        chunks.append({"title": title, "content": content})

    _FAQ_CHUNKS_CACHE = chunks
    logger.info("Loaded %d FAQ chunks", len(_FAQ_CHUNKS_CACHE))
    return _FAQ_CHUNKS_CACHE


def _score_overlap(chunk: Dict[str, str], question_tokens: set) -> int:
    # Include source in token source to help with prospectus-specific scoring
    token_source = (
        chunk.get("title", "") 
        + " " 
        + chunk.get("content", "") 
        + " " 
        + chunk.get("source", "")
    )
    chunk_tokens = set(_tokenize(token_source))
    overlap = sum(1 for token in chunk_tokens if token in question_tokens)
    title_tokens = set(_tokenize(chunk.get("title", "")))
    title_boost = 2 if title_tokens & question_tokens else 0
    
    # Boost prospectus chunks A LOT, especially those with fees/tuition/coict
    prospectus_boost = 0
    if chunk.get("source") == "prospectus.pdf":
        content_lower = chunk.get("content", "").lower()
        prospectus_boost += 5
        if "tuition" in content_lower or "fee" in content_lower or "coict" in content_lower:
            prospectus_boost += 10
    
    return overlap + title_boost + prospectus_boost


def _retrieve_from(
    chunks: List[Dict[str, str]], question: str, top_k: int
) -> List[Dict[str, str]]:
    question_tokens = set(_tokenize(question))
    logger.info("Question tokens for scoring: %s", sorted(question_tokens))
    
    if not question_tokens:
        return []

    scored = [(_score_overlap(c, question_tokens), c) for c in chunks]
    scored.sort(key=lambda x: x[0], reverse=True)
    
    # Log top 10 scores for debugging
    top_scored = scored[:10]
    logger.info("Top %d chunk scores:", len(top_scored))
    for i, (score, chunk) in enumerate(top_scored):
        logger.info("  %d. Score: %d | Title: %s | Source: %s", 
                    i+1, score, chunk.get("title", "N/A"), chunk.get("source", "N/A"))
    
    return [c for s, c in scored if s > 0][:top_k]


def retrieve_relevant_chunks(question: str, top_k: int = 15) -> List[Dict[str, str]]:
    logger.info("Retrieving relevant chunks for question: %s", question)
    
    scraped = load_scraped_chunks()
    faq = load_faq_chunks()
    pdf_chunks = load_pdf_chunks()

    all_chunks = list(scraped)
    seen_titles = {c.get("title", "") for c in scraped}
    for c in faq:
        if c.get("title", "") not in seen_titles:
            all_chunks.append(c)
            seen_titles.add(c.get("title", ""))
    # Add PDF chunks (no deduplication needed since source is different)
    all_chunks.extend(pdf_chunks)
    
    logger.info("Total chunks available: %d", len(all_chunks))

    if not all_chunks:
        return []

    relevant = _retrieve_from(all_chunks, question, top_k)
    logger.info("Retrieved %d relevant chunks", len(relevant))
    return relevant
