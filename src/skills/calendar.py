import datetime

def calendar_query(text):
    """Process calendar-related queries."""
    now = datetime.datetime.now()
    if "time" in text.lower():
        return now.strftime("The current time is %I:%M %p.")
    if "date" in text.lower():
        return now.strftime("Today's date is %B %d, %Y.")
    if "day" in text.lower():
        return now.strftime("Today is %A.")
    else:
        raise ValueError("Unsupported calendar query.")