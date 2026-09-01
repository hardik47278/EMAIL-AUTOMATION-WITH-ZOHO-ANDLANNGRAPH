import fitz
import torch
import io
import os
from PIL import Image
from transformers import AutoTokenizer, AutoModel

# create temp folder for windows
os.makedirs("C:/temp", exist_ok=True)

model_name = "ucaslcl/GOT-OCR2_0"

print("Loading model...")
tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
model = AutoModel.from_pretrained(
    model_name,
    trust_remote_code=True,
    dtype=torch.float16,
    device_map="auto"
).eval()
print("Model loaded!")


def pdf_to_images(pdf_path):
    doc = fitz.open(pdf_path)
    images = []
    for page in doc:
        pix = page.get_pixmap(dpi=200)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        images.append(img)
    return images


def extract_text_from_pdf(pdf_path):
    images = pdf_to_images(pdf_path)
    full_text = ""

    print(f"Total pages: {len(images)}")

    for i, img in enumerate(images):
        temp_path = f"C:/temp/page_{i+1}.png"
        img.save(temp_path)

        try:
            result = model.chat(
                tokenizer,
                temp_path,
                ocr_type="ocr"
            )
        except Exception as e:
            print(f"[Page {i+1}] Error: {e}")
            result = ""

        full_text += f"\n\n===== PAGE {i+1} =====\n{result}"
        print(f"[Page {i+1}] done")

        # cleanup temp file
        os.remove(temp_path)

    return full_text


if __name__ == "__main__":
    pdf_path = "ocrtest.pdf"
    result = extract_text_from_pdf(pdf_path)
    print(result)

    # save output to text file
    with open("output.txt", "w", encoding="utf-8") as f:
        f.write(result)
    print("\nSaved to output.txt")