import base64
import os


def save_attachment(service, msg_id, attachment_id, filename):
    attachment = service.users().messages().attachments().get(
        userId="me",
        messageId=msg_id,
        id=attachment_id
    ).execute()

    data = attachment.get("data")
    file_data = base64.urlsafe_b64decode(data)

    os.makedirs("downloads", exist_ok=True)

    path = f"downloads/{msg_id}_{filename}"

    with open(path, "wb") as f:
        f.write(file_data)

    return path