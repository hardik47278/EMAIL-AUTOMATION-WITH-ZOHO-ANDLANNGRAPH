from pypdf import PdfReader
from langsmith import traceable


# -----------------------------
# Extract text from PDF ONLY
# -----------------------------
@traceable(name="extract_pdf_text")
def extract_pdf_text(file_path):
    reader = PdfReader(file_path)
    text = ""

    for page in reader.pages:
        text += page.extract_text() or ""

    return text.strip()