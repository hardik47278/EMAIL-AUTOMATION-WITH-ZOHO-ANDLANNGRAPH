import io
import json
import easyocr
import fitz  # PyMuPDF
import numpy as np
from PIL import Image

# -------------------------
# CONFIG
# -------------------------
LANGUAGES = ['en']  # add 'ch_sim', 'hi' etc if needed
DPI       = 200
GPU       = True    # set False if you get CUDA errors


# -------------------------
# PDF → images
# -------------------------
def pdf_to_images(pdf_path):
    doc    = fitz.open(pdf_path)
    images = []

    for page in doc:
        pix = page.get_pixmap(dpi=DPI)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        images.append(img)

    print(f"✅ Converted PDF to {len(images)} page(s)")
    return images


# -------------------------
# OCR single page
# -------------------------
def ocr_page(reader, image):
    # EasyOCR needs numpy array
    img_np  = np.array(image)
    results = reader.readtext(img_np, detail=1)

    # results = [ ([[x1,y1],[x2,y2],[x3,y3],[x4,y4]], text, confidence) ]
    lines = []
    for (bbox, text, confidence) in results:
        if confidence > 0.3:   # skip very low confidence
            lines.append(text)

    return "\n".join(lines)


# -------------------------
# FULL PDF OCR
# -------------------------
def ocr_pdf(pdf_path):
    print(f"\n📄 Loading EasyOCR (GPU={GPU})...")
    reader = easyocr.Reader(LANGUAGES, gpu=GPU)

    images    = pdf_to_images(pdf_path)
    all_pages = []

    for i, img in enumerate(images):
        print(f"🔍 Processing page {i+1}/{len(images)}...")
        text = ocr_page(reader, img)
        all_pages.append({
            "page":      i + 1,
            "full_text": text,
        })
        print(f"   ✅ Page {i+1} done — {len(text)} chars extracted")

    return {
        "total_pages": len(images),
        "pages":       all_pages,
        "full_text":   "\n\n===== PAGE BREAK =====\n\n".join(
                           p["full_text"] for p in all_pages
                       ),
    }


# -------------------------
# RUN
# -------------------------
if __name__ == "__main__":
    PDF_PATH = "ff.pdf"

    result = ocr_pdf(PDF_PATH)

    # Print per page
    for page in result["pages"]:
        print(f"\n{'='*50}")
        print(f"PAGE {page['page']}")
        print('='*50)
        print(page["full_text"])

    # Save full text
    with open("output_easyocr.txt", "w", encoding="utf-8") as f:
        f.write(result["full_text"])

    # Save JSON
    with open("output_easyocr.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Done! {result['total_pages']} pages processed")
    print(f"📁 Saved: output_easyocr.txt  &  output_easyocr.json")