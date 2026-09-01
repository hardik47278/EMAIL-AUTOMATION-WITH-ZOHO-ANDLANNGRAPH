import os
import io
import json
import base64

from groq import Groq
from pdf2image import convert_from_path
from dotenv import load_dotenv

load_dotenv()

MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

POPPLER_PATH = (
    r"C:\Users\HARDIK\Downloads\Release-26.02.0-0"
    r"\poppler-26.02.0\Library\bin"
)


def image_to_base64(img):
    img.thumbnail((1600, 1600))

    buffer = io.BytesIO()

    img.save(
        buffer,
        format="JPEG",
        quality=85,
    )

    return base64.b64encode(
        buffer.getvalue()
    ).decode("utf-8")


def groq_page_ocr(client, img_b64):
    completion = client.chat.completions.create(
        model=MODEL,
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
  "document_type":"",
  "summary":"",
  "full_text":""
}
""",
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url":
                            f"data:image/jpeg;base64,{img_b64}"
                        },
                    },
                ],
            }
        ],
    )

    return json.loads(
        completion.choices[0].message.content
    )


def groq_ocr(pdf_path):
    client = Groq(
        api_key=os.getenv("GROQ_API_KEY")
    )

    pages = convert_from_path(
        pdf_path,
        poppler_path=POPPLER_PATH,
        dpi=300,
    )

    all_text = []
    summaries = []

    document_type = ""

    for i, page in enumerate(pages):
        print(f"Reading page {i+1}")

        img_b64 = image_to_base64(page)

        result = groq_page_ocr(
            client,
            img_b64
        )

        if i == 0:
            document_type = result.get(
                "document_type",
                ""
            )

        summaries.append(
            result.get("summary", "")
        )

        all_text.append(
            result.get("full_text", "")
        )

    return {
        "document_type": document_type,
        "summary": "\n".join(summaries),
        "full_text": "\n\n".join(all_text),
    }


if __name__ == "__main__":
    result = groq_ocr("ocrtest.pdf")

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )