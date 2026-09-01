import os
import io
import json
import base64
import time
import logging

from groq import Groq, RateLimitError, APIStatusError, APIConnectionError
from pdf2image import convert_from_path
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)

# -------------------------
# CONFIG
# -------------------------
PRIMARY_MODEL   = "meta-llama/llama-4-scout-17b-16e-instruct"
FALLBACK_MODELS = [
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
]

POPPLER_PATH = (
    r"C:\Users\HARDIK\Downloads\Release-26.02.0-0"
    r"\poppler-26.02.0\Library\bin"
)

MAX_RETRIES    = 3
RETRY_DELAY    = 5   # seconds between retries
BACKOFF_FACTOR = 2   # delay doubles each retry


# -------------------------
# IMAGE HELPER
# -------------------------
def image_to_base64(img):
    img.thumbnail((1600, 1600))
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


# -------------------------
# SINGLE MODEL CALL (with retries)
# -------------------------
def call_model(client, img_b64, model, page_num):
    delay = RETRY_DELAY

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            log.info(f"Page {page_num} | Model: {model} | Attempt {attempt}/{MAX_RETRIES}")

            completion = client.chat.completions.create(
                model=model,
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": """
Read this PDF page carefully.

Return JSON:

{
  "document_type": "",
  "summary": "",
  "full_text": ""
}
""",
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{img_b64}"
                                },
                            },
                        ],
                    }
                ],
            )

            raw = completion.choices[0].message.content
            result = json.loads(raw)
            log.info(f"Page {page_num} | Model: {model} | Success ✅")
            return result

        except RateLimitError as e:
            # Rate limited — wait longer before retry
            wait = delay * (BACKOFF_FACTOR ** (attempt - 1))
            log.warning(f"Page {page_num} | Rate limit hit on '{model}'. Waiting {wait}s... ({e})")
            time.sleep(wait)

        except APIConnectionError as e:
            wait = delay * (BACKOFF_FACTOR ** (attempt - 1))
            log.warning(f"Page {page_num} | Connection error on '{model}'. Waiting {wait}s... ({e})")
            time.sleep(wait)

        except APIStatusError as e:
            # 4xx/5xx errors — some are retryable (503), some are not (400)
            if e.status_code in (500, 502, 503, 504):
                wait = delay * (BACKOFF_FACTOR ** (attempt - 1))
                log.warning(f"Page {page_num} | Server error {e.status_code} on '{model}'. Waiting {wait}s...")
                time.sleep(wait)
            else:
                # 400/401/404 etc — no point retrying
                log.error(f"Page {page_num} | Non-retryable error {e.status_code} on '{model}': {e}")
                raise

        except json.JSONDecodeError as e:
            log.warning(f"Page {page_num} | JSON parse error on '{model}' attempt {attempt}: {e}")
            if attempt == MAX_RETRIES:
                raise

    # All retries exhausted for this model
    raise RuntimeError(f"All {MAX_RETRIES} retries failed for model '{model}' on page {page_num}")


# -------------------------
# OCR ONE PAGE (with model fallback)
# -------------------------
def groq_page_ocr(client, img_b64, page_num):
    all_models = [PRIMARY_MODEL] + FALLBACK_MODELS
    last_error = None

    for model in all_models:
        try:
            return call_model(client, img_b64, model, page_num)

        except RuntimeError as e:
            log.warning(f"Page {page_num} | Model '{model}' exhausted. Trying next fallback...")
            last_error = e

        except APIStatusError as e:
            log.warning(f"Page {page_num} | Model '{model}' returned {e.status_code}. Trying next fallback...")
            last_error = e

    # All models failed — return a safe empty result so PDF processing continues
    log.error(f"Page {page_num} | ALL models failed. Returning empty result. Last error: {last_error}")
    return {
        "document_type": "",
        "summary": f"[Page {page_num} failed to process]",
        "full_text": f"[Page {page_num} could not be extracted. Error: {last_error}]",
    }


# -------------------------
# FULL PDF OCR
# -------------------------
def groq_ocr(pdf_path):
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    log.info(f"Converting PDF to images: {pdf_path}")
    pages = convert_from_path(
        pdf_path,
        poppler_path=POPPLER_PATH,
        dpi=300,
    )
    log.info(f"Total pages: {len(pages)}")

    all_text     = []
    summaries    = []
    document_type = ""
    failed_pages  = []

    for i, page in enumerate(pages):
        page_num = i + 1
        print(f"\n📄 Processing page {page_num}/{len(pages)}...")

        img_b64 = image_to_base64(page)
        result  = groq_page_ocr(client, img_b64, page_num)

        if i == 0:
            document_type = result.get("document_type", "")

        summary   = result.get("summary", "")
        full_text = result.get("full_text", "")

        summaries.append(summary)
        all_text.append(full_text)

        # Track failed pages
        if full_text.startswith("[Page") and "could not be extracted" in full_text:
            failed_pages.append(page_num)

    if failed_pages:
        log.warning(f"Failed pages: {failed_pages}")

    return {
        "document_type": document_type,
        "summary":       "\n".join(summaries),
        "full_text":     "\n\n".join(all_text),
        "failed_pages":  failed_pages,
        "total_pages":   len(pages),
    }


# -------------------------
# RUN
# -------------------------
if __name__ == "__main__":
    result = groq_ocr("ocrtest.pdf")

    print("\n\n===== FINAL OUTPUT =====\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))

    with open("output.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print("\n✅ Saved to output.json")

    if result["failed_pages"]:
        print(f"⚠️  Failed pages: {result['failed_pages']}")
    else:
        print(f"🎉 All {result['total_pages']} pages extracted successfully!")