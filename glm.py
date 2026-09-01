import fitz  # PyMuPDF
from PIL import Image
from transformers import AutoProcessor, AutoModelForImageTextToText
import torch

MODEL = "zai-org/GLM-OCR"

processor = AutoProcessor.from_pretrained(MODEL)
model = AutoModelForImageTextToText.from_pretrained(
    MODEL,
    device_map="auto",
    dtype=torch.float16  # fixed: torch_dtype → dtype
)


# -------------------------
# PDF → images
# -------------------------
def pdf_to_images(pdf_path):
    doc = fitz.open(pdf_path)
    images = []

    for page in doc:
        pix = page.get_pixmap(dpi=200)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        images.append(img)

    return images


# -------------------------
# OCR single page
# -------------------------
def ocr_page(image):
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": image},
                {"type": "text", "text": "Text Recognition:"}
            ]
        }
    ]

    # FIXED: apply_chat_template returns a Tensor, not a dict
    # So we must use processor() separately to get a proper dict
    text = processor.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True
    )

    inputs = processor(
        text=[text],
        images=[image],
        return_tensors="pt",
        padding=True
    )

    # FIXED: move each tensor to device individually
    inputs = {k: v.to(model.device) for k, v in inputs.items()}

    outputs = model.generate(**inputs, max_new_tokens=2048)

    # FIXED: use inputs["input_ids"] safely from dict
    decoded = processor.decode(
        outputs[0][inputs["input_ids"].shape[1]:],
        skip_special_tokens=True
    )

    return decoded


# -------------------------
# PDF OCR MAIN
# -------------------------
def extract_text_from_pdf(pdf_path):
    images = pdf_to_images(pdf_path)

    full_text = ""

    for i, img in enumerate(images):
        print(f"Processing page {i+1}/{len(images)}")
        text = ocr_page(img)
        full_text += f"\n\n===== PAGE {i+1} =====\n{text}"

    return full_text


# -------------------------
# RUN
# -------------------------
if __name__ == "__main__":
    result = extract_text_from_pdf("ocrtest.pdf")

    print("\n\n===== FINAL OUTPUT =====\n")
    print(result)

    with open("output.txt", "w", encoding="utf-8") as f:
        f.write(result)

    print("\nSaved to output.txt")