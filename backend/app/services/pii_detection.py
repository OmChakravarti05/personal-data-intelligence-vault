from dataclasses import dataclass
from functools import lru_cache

from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
from presidio_analyzer.nlp_engine import NlpEngineProvider

DEFAULT_CATEGORIES = (
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "CREDIT_CARD",
    "US_SSN",
    "PAN_NUMBER",
    "AADHAAR_NUMBER",
    "IBAN_CODE",
    "IP_ADDRESS",
    "PERSON",
)
DEFAULT_MIN_SCORE = 0.4
_BLOCK_SIZE = 100_000  # keeps each piece safely under spaCy's length limit

_NLP_CONFIG = {
    "nlp_engine_name": "spacy",
    "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
}


@dataclass(frozen=True)
class PIIMatch:
    """Where PII was found. It deliberately holds no copy of the value itself."""

    category: str
    start: int
    end: int
    score: float


@lru_cache
def _analyzer() -> AnalyzerEngine:
    nlp_engine = NlpEngineProvider(nlp_configuration=_NLP_CONFIG).create_engine()
    engine = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["en"])
    engine.registry.add_recognizer(
        PatternRecognizer(
            supported_entity="PAN_NUMBER",
            patterns=[Pattern("pan", r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", 0.6)],
            context=["pan", "permanent account number"],
            supported_language="en",
        )
    )
    engine.registry.add_recognizer(
        PatternRecognizer(
            supported_entity="AADHAAR_NUMBER",
            patterns=[Pattern("aadhaar", r"\b[2-9][0-9]{3}\s?[0-9]{4}\s?[0-9]{4}\b", 0.5)],
            context=["aadhaar", "aadhar", "uid"],
            supported_language="en",
        )
    )
    return engine


def _blocks(text: str):
    """Yield (offset, block), splitting at line breaks where possible."""
    start, total = 0, len(text)
    while start < total:
        end = min(start + _BLOCK_SIZE, total)
        if end < total:
            newline = text.rfind("\n", start, end)
            if newline > start:
                end = newline + 1
        yield start, text[start:end]
        start = end


def _resolve_overlaps(matches: list[PIIMatch]) -> list[PIIMatch]:
    """When two detections overlap, keep the more confident (then longer) one."""
    ranked = sorted(matches, key=lambda m: (-m.score, -(m.end - m.start), m.start))
    kept: list[PIIMatch] = []
    for match in ranked:
        if all(match.end <= k.start or match.start >= k.end for k in kept):
            kept.append(match)
    return sorted(kept, key=lambda m: m.start)


def detect_pii(
    text: str,
    categories: tuple[str, ...] | list[str] = DEFAULT_CATEGORIES,
    min_score: float = DEFAULT_MIN_SCORE,
) -> list[PIIMatch]:
    """Find possible PII. Results are probabilistic: expect false positives and misses."""
    if not text.strip():
        return []
    analyzer = _analyzer()
    found: list[PIIMatch] = []
    for offset, block in _blocks(text):
        for result in analyzer.analyze(
            text=block,
            language="en",
            entities=list(categories),
            score_threshold=min_score,
        ):
            found.append(
                PIIMatch(
                    category=result.entity_type,
                    start=offset + result.start,
                    end=offset + result.end,
                    score=round(float(result.score), 3),
                )
            )
    return _resolve_overlaps(found)


def redact_text(text: str, matches: list[PIIMatch]) -> str:
    """Replace each detected span with a [CATEGORY] placeholder."""
    redacted = text
    for match in sorted(matches, key=lambda m: m.start, reverse=True):
        redacted = redacted[: match.start] + f"[{match.category}]" + redacted[match.end :]
    return redacted