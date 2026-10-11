from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import settings
from app.services.document_parser import ExtractedDocument


@dataclass(frozen=True)
class ChunkData:
    chunk_index: int  # position within the whole document, starting at 0
    page_number: int | None  # real page for PDFs, None for other formats
    content: str


def document_segments(parsed: ExtractedDocument) -> list[tuple[int | None, str]]:
    """One segment per PDF page, or one segment for the whole file otherwise."""
    if any(page.page_number is not None for page in parsed.pages):
        return [(page.page_number, page.text) for page in parsed.pages]
    return [(None, "\n\n".join(page.text for page in parsed.pages))]


def chunk_segments(
    segments: list[tuple[int | None, str]],
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[ChunkData]:
    """Split text with LangChain, keeping every chunk tied to its source page.

    Chunks never span pages, so a citation can always name the right page.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size or settings.chunk_size,
        chunk_overlap=settings.chunk_overlap if chunk_overlap is None else chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks: list[ChunkData] = []
    for page_number, text in segments:
        for piece in splitter.split_text(text):
            piece = piece.strip()
            if piece:
                chunks.append(ChunkData(len(chunks), page_number, piece))
    return chunks