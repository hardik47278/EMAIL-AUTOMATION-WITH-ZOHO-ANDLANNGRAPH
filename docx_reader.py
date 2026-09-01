from docx import Document
from langsmith import traceable



@traceable(name="extract_docx_text")
def extract_docx_text(file_path):
    doc = Document(file_path)

    text = []

    for para in doc.paragraphs:
        if para.text.strip():
            text.append(para.text)

    return "\n".join(text).strip()