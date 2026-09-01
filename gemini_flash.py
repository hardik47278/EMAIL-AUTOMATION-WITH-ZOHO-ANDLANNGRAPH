import os
import fitz
import time
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


def generate_with_retry(img_bytes, retries=3, wait=30):
    for attempt in range(retries):
        try:
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=[
                    types.Part.from_bytes(data=img_bytes, mime_type="image/png"),
                    "Extract all text from this document page. Return exact OCR output."
                ]
            )
            return response.text or ""
        except Exception as e:
            if "429" in str(e):
                print(f"  Rate limited. Waiting {wait}s before retry {attempt+1}/{retries}...")
                time.sleep(wait)
            else:
                print(f"  Error: {e}")
                return ""
    return ""


def extract_text_from_pdf(pdf_path):
    images = pdf_to_images(pdf_path)
    full_text = ""
    print(f"Total pages: {len(images)}")

    for i, img_bytes in enumerate(images):
        print(f"[Page {i+1}] processing...")
        page_text = generate_with_retry(img_bytes)
        full_text += f"\n\n===== PAGE {i+1} =====\n{page_text}"
        print(f"[Page {i+1}] done")
        time.sleep(4)  # 4s gap between pages to avoid rate limit

    return full_text


if __name__ == "__main__":
    result = extract_text_from_pdf("ocrtest.pdf")
    print(result)
    with open("output.txt", "w", encoding="utf-8") as f:
        f.write(result)
    print("\nSaved to output.txt")