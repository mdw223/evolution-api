"""Shared LLM prompts for event classification and extraction."""

CLASSIFY_PROMPT = """You are filtering WhatsApp group messages for a Muslim community events calendar.

Decide if the message announces a community event (program, class, fundraiser, janazah notice, halaqa, iftar, sports, registration, etc.).

Reply with JSON only:
{{"is_event": true or false, "confidence": 0.0 to 1.0}}

Message:
{text}
"""

EXTRACT_PROMPT = """Extract event details from this WhatsApp message for a community calendar database.

Reply with JSON only using these keys (use null when unknown):
{{
  "eventName": "string (required if event)",
  "eventDate": "YYYY-MM-DD (required if event)",
  "eventHostOrganization": "string or null",
  "eventDescription": "string or null",
  "eventLocation": "string or null",
  "eventStartTime": "HH:MM:SS 24h or null",
  "eventEndTime": "HH:MM:SS 24h or null"
}}

Today's date for relative references: {today}

Message:
{text}
"""

GEMINI_VISION_EXTRACT_PROMPT = """Extract event details from this flyer image and any OCR text for a Muslim community calendar.

OCR text from image:
{ocr_text}

Reply with JSON only:
{{
  "is_event": true or false,
  "confidence": 0.0 to 1.0,
  "eventName": "string or null",
  "eventDate": "YYYY-MM-DD or null",
  "eventHostOrganization": "string or null",
  "eventDescription": "string or null",
  "eventLocation": "string or null",
  "eventStartTime": "HH:MM:SS or null",
  "eventEndTime": "HH:MM:SS or null"
}}

Today's date: {today}
"""
