import dateparser
from langchain_core.tools import tool
from calender_integration import list_events, create_event, get_free_slots

@tool
def check_slot_tool(date: str) -> dict:
    """
    Check if a date has free or busy slots
    on the user's Google Calendar.
    Input  : date in YYYY-MM-DD format
    Output : dict with busy slots and is_free flag
    Use this when an email mentions a date
    and you need to check availability.
    """

    try:
        busy = get_free_slots(date)

        return {
            "date"      : date,
            "busy_slots": busy,
            "is_free"   : len(busy) == 0,
            "error"     : None
        }

    except Exception as e:
        return {
            "date"      : date,
            "busy_slots": [],
            "is_free"   : None,
            "error"     : str(e)
        }


@tool
def list_events_tool(max_results: int = 5) -> dict:
    """
    List upcoming events from the user's Google Calendar.
    Input  : max_results — how many events to return (default 5)
    Output : list of upcoming events with title and time
    Use this when you need to show what is already
    scheduled or check if sender has an existing meeting.
    """

    try:
        events = list_events(max_results)

        formatted = []

        for event in events:
            formatted.append({
                "title"   : event.get("summary", "No Title"),
                "start"   : event["start"].get(
                                "dateTime",
                                event["start"].get("date")
                            ),
                "event_id": event.get("id")
            })

        return {
            "total" : len(formatted),
            "events": formatted,
            "error" : None
        }

    except Exception as e:
        return {
            "total" : 0,
            "events": [],
            "error" : str(e)
        }


@tool
def create_event_tool(
    summary    : str,
    date       : str,
    start_time : str,
    end_time   : str,
    description: str = ""
) -> dict:
    """
    Create a new event on the user's Google Calendar.
    Input  : summary, date YYYY-MM-DD,
             start_time HH:MM, end_time HH:MM,
             description optional
    Output : created event details with link
    Use this ONLY after human has approved the booking.
    Never call this without human approval.
    """

    try:
        created = create_event(
            summary     = summary,
            date        = date,
            start_time  = start_time,
            end_time    = end_time,
            description = description
        )

        return {
            "success"   : True,
            "event_id"  : created.get("id"),
            "event_link": created.get("htmlLink"),
            "summary"   : created.get("summary"),
            "start"     : created["start"].get("dateTime"),
            "end"       : created["end"].get("dateTime"),
            "error"     : None
        }

    except Exception as e:
        return {
            "success"   : False,
            "event_id"  : None,
            "event_link": None,
            "summary"   : None,
            "start"     : None,
            "end"       : None,
            "error"     : str(e)
        }

@tool
def extract_date_tool(text: str) -> dict:
    """
    Extract any date or time mentioned in email body.
    Input  : raw email body text
    Output : extracted date and time or None
    Use this on every email body to check
    if sender mentioned a meeting date or time.
    """

    try:
        result = dateparser.parse(
            text,
            settings={
                "PREFER_DATES_FROM"       : "future",
                "TIMEZONE"                : "Asia/Kolkata",
                "RETURN_AS_TIMEZONE_AWARE": True
            }
        )

        if not result:
            return {
                "found"         : False,
                "extracted_date": None,
                "extracted_time": None,
                "raw"           : None,
                "error"         : None
            }

        return {
            "found"         : True,
            "extracted_date": result.strftime("%Y-%m-%d"),
            "extracted_time": result.strftime("%H:%M"),
            "raw"           : str(result),
            "error"         : None
        }

    except Exception as e:
        return {
            "found"         : False,
            "extracted_date": None,
            "extracted_time": None,
            "raw"           : None,
            "error"         : str(e)
        }