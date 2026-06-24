"""Simple retrieval-augmented generation support for the assistant.

This module implements a tiny, dependency-free retriever over a small
FAQ document. It performs token overlap scoring with a few pragmatic
improvements to reduce hallucinations:
- simple synonym normalization (e.g. "myuni" -> "aris3")
- small title-boost so exact-topic matches are preferred

The loader caches the parsed chunks at module-level so the file is only
read once per process.
"""

import re
from pathlib import Path
from typing import Dict, List

from backend.config import settings

_FAQ_CHUNKS_CACHE: List[Dict[str, str]] | None = None

# Tiny set of stopwords to ignore during token matching.
_STOPWORDS = {
    "the",
    "and",
    "or",
    "is",
    "a",
    "an",
    "to",
    "of",
    "for",
    "in",
    "on",
    "at",
    "by",
    "with",
    "from",
    "that",
    "this",
    "as",
    "are",
    "be",
    "was",
    "were",
}

# Synonyms map to canonical tokens so user phrasing like "myuni" will match
# references to ARIS 3 found in the FAQ.
_SYNONYMS = {
    "myuni": "aris3",
    "my-uni": "aris3",
    "aris": "aris3",
    "aris3": "aris3",
}


def _normalize_token(token: str) -> str:
    """Normalize a single token (lowercase, map synonyms).

    Keeps tokens short and predictable so matching is simpler.
    """
    token = token.lower()
    return _SYNONYMS.get(token, token)


def _tokenize(text: str) -> List[str]:
    """Split text into lowercase tokens, map synonyms, and drop stopwords."""
    raw = re.split(r"[^a-z0-9]+", text.lower())
    tokens: List[str] = []
    for t in raw:
        if not t:
            continue
        norm = _normalize_token(t)
        if norm and norm not in _STOPWORDS:
            tokens.append(norm)
    return tokens


def load_faq_chunks() -> List[Dict[str, str]]:
    """Load FAQ chunks from the markdown file and cache them for the process."""
    global _FAQ_CHUNKS_CACHE
    if _FAQ_CHUNKS_CACHE is not None:
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
    return _FAQ_CHUNKS_CACHE


def retrieve_relevant_chunks(question: str, top_k: int = 2) -> List[Dict[str, str]]:
    """Return the most relevant FAQ chunks for the given question.

    Scoring is a simple token-overlap measure with an additional small
    boost when the chunk title matches tokens in the question. Returns
    at most ``top_k`` chunks with score > 0.
    """
    question_tokens = set(_tokenize(question))
    if not question_tokens:
        return []

    chunks = load_faq_chunks()
    scored_chunks: List[tuple[int, Dict[str, str]]] = []

    for chunk in chunks:
        chunk_tokens = set(_tokenize(chunk["title"] + " " + chunk["content"]))
        overlap = sum(1 for token in chunk_tokens if token in question_tokens)

        # Small title-boost to prefer exact-topic matches (helps reduce
        # ambiguous retrieval where multiple sections share common words).
        title_tokens = set(_tokenize(chunk["title"]))
        title_boost = 2 if title_tokens & question_tokens else 0

        score = overlap + title_boost
        if score > 0:
            scored_chunks.append((score, chunk))

    scored_chunks.sort(key=lambda item: item[0], reverse=True)
    return [chunk for _, chunk in scored_chunks[:top_k]]
