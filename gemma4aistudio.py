import os
import fitz
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("GOOGLE_API_KEY")

client = genai.Client(api_key=API_KEY)

def pdf_to_images(pdf_path):
    doc = fitz.open(pdf_path)
    images = []
    for page in doc:
        pix = page.get_pixmap(dpi=200)
        images.append(pix.tobytes("png"))
    return images


def extract_text_from_pdf(pdf_path):
    images = pdf_to_images(pdf_path)
    full_text = ""

    for i, img_bytes in enumerate(images):
        try:
            response = client.models.generate_content(
                model="gemma-4-31b-it",
                contents=[
                    types.Part.from_bytes(data=img_bytes, mime_type="image/png"),
                    "Extract all text from this document page. Return exact OCR output."
                ]
            )
            page_text = response.text or ""
        except Exception as e:
            print(f"[Page {i+1}] Error: {e}")
            page_text = ""

        full_text += f"\n\n===== PAGE {i+1} =====\n{page_text}"
        print(f"[Page {i+1}] done")

    return full_text


if __name__ == "__main__":
    result = extract_text_from_pdf("ocrtest.pdf")
    print(result)