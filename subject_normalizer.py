import re


def normalize_subject(subject: str) -> str:
    if not subject:
        return "no subject"

    subject = subject.lower()

    # remove re:, fwd:, fw:
    subject = re.sub(r"^(re:|fwd:|fw:)\s*", "", subject)

    # remove [tags]
    subject = re.sub(r"\[.*?\]", "", subject)

    # remove emojis / special chars (basic cleanup)
    subject = re.sub(r"[^\w\s]", " ", subject)

    # collapse multiple spaces
    subject = re.sub(r"\s+", " ", subject).strip()

    return subject