"""
Google Calendar API — Connect, Read & Write
Run auth.py ONCE first to generate token.json, then use calendar.py freely.
"""

import os
import datetime
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/calendar']


def authenticate():
    """
    First run: opens browser for Google login → saves token.json
    After that: silently refreshes token from token.json
    Requires: credentials.json in same folder
    """
    creds = None

  
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)

    # Refresh or re-authenticate if needed
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials/credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as f:
            f.write(creds.to_json())

    return creds


def get_service():
    creds = authenticate()
    return build('calendar', 'v3', credentials=creds)


def list_events(max_results=10):
    """List the next N upcoming events from your primary calendar."""
    service = get_service()
    now = datetime.datetime.utcnow().isoformat() + 'Z'  # 'Z' = UTC

    events_result = service.events().list(
        calendarId='primary',
        timeMin=now,
        maxResults=max_results,
        singleEvents=True,
        orderBy='startTime'
    ).execute()

    events = events_result.get('items', [])

    if not events:
        print('No upcoming events found.')
        return []

    for event in events:
        start = event['start'].get('dateTime', event['start'].get('date'))
        print(f"{start} — {event['summary']}")

    return events


def create_event(summary, date, start_time, end_time, description="", timezone="Asia/Kolkata"):
    """
    Create a calendar event.
    date       : 'YYYY-MM-DD'
    start_time : 'HH:MM'  e.g. '14:00'
    end_time   : 'HH:MM'  e.g. '15:00'
    """
    service = get_service()

    event = {
        'summary': summary,
        'description': description,
        'start': {
            'dateTime': f'{date}T{start_time}:00',
            'timeZone': timezone,
        },
        'end': {
            'dateTime': f'{date}T{end_time}:00',
            'timeZone': timezone,
        },
    }

    created = service.events().insert(calendarId='primary', body=event).execute()
    print(f"✅ Event created: {created.get('htmlLink')}")
    return created


def get_free_slots(date, timezone="Asia/Kolkata"):
    """
    Returns list of busy time ranges on a given date.
    date: 'YYYY-MM-DD'
    """
    service = get_service()

    start = f'{date}T00:00:00+05:30'
    end   = f'{date}T23:59:59+05:30'

    body = {
        "timeMin": start,
        "timeMax": end,
        "timeZone": timezone,
        "items": [{"id": "primary"}]
    }

    result = service.freebusy().query(body=body).execute()
    busy = result['calendars']['primary']['busy']

    print(f"Busy slots on {date}:")
    for slot in busy:
        print(f"  {slot['start']} → {slot['end']}")

    return busy


def delete_event(event_id):
    """Delete an event by its ID."""
    service = get_service()
    service.events().delete(calendarId='primary', eventId=event_id).execute()
    print(f"🗑️ Event {event_id} deleted.")

if __name__ == "__main__":
    print("=== Upcoming Events ===")
    list_events(5)

    print("\n=== Create Test Event ===")
    create_event(
        summary="Test Appointment",
        date="2026-06-01",
        start_time="14:00",
        end_time="15:00",
        description="Created via Google Calendar API"
    )
    
    print("\n=== Free/Busy Check ===")
    get_free_slots("2026-06-01")