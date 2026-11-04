"""Turn an uploaded brief (PDF, DOCX, TXT/MD) into plain text."""
import io
import re


class UnsupportedFile(ValueError):
    pass


def extract_text(filename: str, content: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    elif name.endswith(".docx"):
        import docx

        document = docx.Document(io.BytesIO(content))
        parts = [p.text for p in document.paragraphs]
        for table in document.tables:
            for row in table.rows:
                parts.append(" | ".join(cell.text for cell in row.cells))
        text = "\n".join(parts)
    elif name.endswith((".txt", ".md", ".markdown")):
        text = content.decode("utf-8", errors="replace")
    else:
        raise UnsupportedFile("Supported formats: PDF, DOCX, TXT, MD")
    return normalise(text)


def normalise(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\t", " ")
    text = re.sub(r"[  ]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
