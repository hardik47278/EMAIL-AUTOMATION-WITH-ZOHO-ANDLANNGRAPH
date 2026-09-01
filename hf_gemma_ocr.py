import os
import json
import torch

from dotenv import load_dotenv
from pdf2image import convert_from_path
from transformers import (
    AutoProcessor,
    Gemma3ForConditionalGeneration,
)

# -----------------------------
# config
# -----------------------------
load_dotenv()

MODEL_ID = "google/gemma-3-4b-it"

# windows poppler path
POPPLER_PATH = (
    r"C:\Users\HARDIK\Downloads\Release-26.02.0-0"
    r"\poppler-26.02.0\Library\bin"
)


# -----------------------------
# load model once
# -----------------------------
print("Loading Gemma...")

model = Gemma3ForConditionalGeneration.from_pretrained(
    MODEL_ID,
    token=os.getenv("HF_TOKEN"),
    device_map="auto",
    torch_dtype="auto",
).eval()

processor = AutoProcessor.from_pretrained(
    MODEL_ID,
    token=os.getenv("HF_TOKEN"),
)

print("Gemma ready.")


# -----------------------------
# OCR single page
# -----------------------------
def ocr_page(image):
    messages = [
        {
            "role": "system",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "Extract every visible text from this page exactly. "
                        "Preserve line breaks. "
                        "Do not summarize."
                    ),
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "image": image,
                },
                {
                    "type": "text",
                    "text": "OCR this page.",
                },
            ],
        },
    ]

    inputs = processor.apply_chat_template(
        messages,
        add_generation_prompt=True,
        tokenize=True,
        return_dict=True,
        return_tensors="pt",
    ).to(model.device)

    input_len = inputs["input_ids"].shape[-1]

    with torch.inference_mode():
        output = model.generate(
            **inputs,
            max_new_tokens=2048,
            do_sample=False,
        )

    text = processor.decode(
        output[0][input_len:],
        skip_special_tokens=True,
    )

    return text.strip()


# -----------------------------
# summarize
# -----------------------------
def summarize_document(full_text):
    prompt = f"""
Read OCR text below.

Return valid JSON:

{{
  "document_type":"",
  "summary":""
}}

OCR:

{full_text[:12000]}
"""

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": prompt,
                }
            ],
        }
    ]

    inputs = processor.apply_chat_template(
        messages,
        add_generation_prompt=True,
        tokenize=True,
        return_dict=True,
        return_tensors="pt",
    ).to(model.device)

    input_len = inputs["input_ids"].shape[-1]

    with torch.inference_mode():
        output = model.generate(
            **inputs,
            max_new_tokens=400,
            do_sample=False,
        )

    text = processor.decode(
        output[0][input_len:],
        skip_special_tokens=True,
    )

    try:
        return json.loads(text)
    except Exception:
        return {
            "document_type": "unknown",
            "summary": text,
        }


# -----------------------------
# main OCR
# -----------------------------
def gemma_ocr(pdf_path):
    print("Converting PDF...")

    pages = convert_from_path(
        pdf_path,
        dpi=300,
        poppler_path=POPPLER_PATH,
    )

    all_text = []

    for idx, page in enumerate(pages, start=1):
        print(f"OCR page {idx}/{len(pages)}")

        page.thumbnail((1600, 1600))

        text = ocr_page(page)

        all_text.append(
            f"\n--- PAGE {idx} ---\n{text}"
        )

    full_text = "\n".join(all_text)

    summary_json = summarize_document(full_text)

    return {
        "document_type": summary_json.get(
            "document_type",
            "unknown",
        ),
        "summary": summary_json.get(
            "summary",
            "",
        ),
        "full_text": full_text,
    }

if __name__ == "__main__":
    result = gemma_ocr("ocrtest.pdf")

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )