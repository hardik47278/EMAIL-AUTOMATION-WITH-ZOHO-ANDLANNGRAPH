import os
import fitz
import base64
import time
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

openrouter = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)

PROMPT = "Extract all text from this page exactly as it appears. Return only the extracted text, nothing else."


def pdf_to_images(pdf_path):
    doc = fitz.open(pdf_path)
    images = []
    for page in doc:
        pix = page.get_pixmap(dpi=200)
        b64 = base64.b64encode(pix.tobytes("png")).decode()
        images.append(b64)
    return images


def extract_page(b64_img, page_no, max_retries=10):
    for attempt in range(1, max_retries + 1):
        try:
            print(f"  [Page {page_no}] Attempt {attempt}/{max_retries}...")
            response = openrouter.chat.completions.create(
                model="google/gemma-4-31b-it:free",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_img}"}},
                        {"type": "text", "text": PROMPT}
                    ]
                }],
                max_tokens=2048
            )
            text = response.choices[0].message.content or ""
            print(f"  [Page {page_no}] ✓ Success on attempt {attempt}")
            return text

        except Exception as e:
            err = str(e)
            if "429" in err:
                wait = 30 * attempt  # 30s, 60s, 90s ... increases each retry
                print(f"  [Page {page_no}] ⏳ Rate limited. Waiting {wait}s...")
                time.sleep(wait)
            else:
                print(f"  [Page {page_no}] ✗ Error: {err[:100]}")
                time.sleep(5)

    print(f"  [Page {page_no}] Failed after {max_retries} attempts")
    return ""


def extract_text_from_pdf(pdf_path):
    print(f"Opening: {pdf_path}")
    images = pdf_to_images(pdf_path)
    print(f"Total pages: {len(images)}\n")
    full_text = ""

    for i, b64_img in enumerate(images):
        page_text = extract_page(b64_img, i + 1)
        full_text += f"\n\n===== PAGE {i+1} =====\n{page_text}"
        time.sleep(10)  # 10s gap between pages

    return full_text


if __name__ == "__main__":
    result = extract_text_from_pdf("ocrtest.pdf")
    print("\n\n===== FULL OUTPUT =====")
    print(result)

    with open("output.txt", "w", encoding="utf-8") as f:
        f.write(result)
    print("\nSaved to output.txt")