from pathlib import Path

from ..models import RawBlock


def load_document(path: str | Path, ocr_min_chars: int = 50) -> list[RawBlock]:
    p = Path(path)
    if p.suffix.lower() == ".csv":
        from .csv import CSVLoader

        return CSVLoader().load(p)
    else:
        from .pdf import PDFLoader

        return PDFLoader(ocr_min_chars=ocr_min_chars).load(p)
