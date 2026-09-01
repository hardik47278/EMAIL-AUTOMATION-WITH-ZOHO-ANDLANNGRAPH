from bs4 import BeautifulSoup
import re

def clean_html_email(raw_body: str) -> str:
    """
    Converts raw Gmail HTML/text email into clean readable text.
    """

    # =========================
    # 1. Detect HTML content
    # =========================
    if "<html" in raw_body.lower() or "<body" in raw_body.lower():
        soup = BeautifulSoup(raw_body, "html.parser")

        # =========================
        # 2. Remove unwanted tags
        # =========================
        for tag in soup(["script", "style", "noscript", "meta", "head"]):
            tag.decompose()

        # =========================
        # 3. Extract visible text
        # =========================
        text = soup.get_text(separator="\n")
    else:
        # already plain text
        text = raw_body

    # =========================
    # 4. Remove URLs (tracking links)
    # =========================
    text = re.sub(r"http\S+|www\.\S+", "", text)

    # =========================
    # 5. Remove excessive whitespace
    # =========================
    text = re.sub(r"\n\s*\n+", "\n\n", text)  # multiple blank lines
    text = re.sub(r"[ \t]+", " ", text)       # extra spaces

    # =========================
    # 6. Clean each line
    # =========================
    lines = []
    for line in text.split("\n"):
        line = line.strip()
        if line:  # skip empty lines
            lines.append(line)

    # =========================
    # 7. Final output
    # =========================
    return "\n".join(lines)