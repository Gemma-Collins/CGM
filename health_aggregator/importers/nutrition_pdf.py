"""Extract carb/calorie entries from a PDF (nutrition facts sheet, meal
plan, dietitian handout, etc.) - a second way to get carb data in besides
Cronometer, for whenever nutrition info only exists as a PDF.

PDF layouts vary too much to parse reliably in general, so this looks for
the pattern any such document tends to share: a labeled number ("Carbs:
45g", "Total Carbohydrate 45 g", "Calories 210") on its own line, with the
nearest preceding plain-text line (no numbers) used as the food/meal name.
It's a best-effort heuristic, not a general PDF-table parser - check the
extracted rows against the source document, especially for multi-column
layouts pdfplumber may flatten in an unexpected order.
"""

import re

import pandas as pd

from health_aggregator.models import CARB_COLUMNS, empty_frame, ensure_schema

_CARB_RE = re.compile(r"(?:total\s+)?carb(?:ohydrate)?s?\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*g\b", re.IGNORECASE)
_CALORIE_RE = re.compile(r"(?:calories|energy)\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*(?:kcal|cal)?\b", re.IGNORECASE)
_HEADING_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 '\-/(),.]*$")


def _looks_like_heading(line: str) -> bool:
    if not line or len(line) > 60:
        return False
    if _CARB_RE.search(line) or _CALORIE_RE.search(line):
        return False
    return bool(_HEADING_RE.match(line))


def _extract_nutrition_entries(text: str) -> list:
    """Pure text -> [{food_name, carbs_g, calories_kcal}, ...]. Separated
    from PDF reading so this logic is testable without a real PDF file."""
    entries = []
    current_name = "unknown"
    pending_carbs = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        carb_match = _CARB_RE.search(line)
        cal_match = _CALORIE_RE.search(line)

        if carb_match:
            if pending_carbs is not None:
                entries.append({"food_name": current_name, "carbs_g": pending_carbs, "calories_kcal": None})
            pending_carbs = float(carb_match.group(1))
            if cal_match:
                entries.append({"food_name": current_name, "carbs_g": pending_carbs, "calories_kcal": float(cal_match.group(1))})
                pending_carbs = None
        elif cal_match and pending_carbs is not None:
            entries.append({"food_name": current_name, "carbs_g": pending_carbs, "calories_kcal": float(cal_match.group(1))})
            pending_carbs = None
        elif _looks_like_heading(line):
            current_name = line

    if pending_carbs is not None:
        entries.append({"food_name": current_name, "carbs_g": pending_carbs, "calories_kcal": None})

    return entries


def parse_pdf(path: str, date=None) -> pd.DataFrame:
    """Extract nutrition entries from a PDF. `date` (a date/Timestamp/ISO
    string) is needed since PDFs rarely carry a reliable "when eaten"
    timestamp - defaults to noon today if omitted."""
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    entries = _extract_nutrition_entries(text)
    if not entries:
        return empty_frame(CARB_COLUMNS)

    timestamp = pd.Timestamp(date) if date is not None else pd.Timestamp.now().normalize() + pd.Timedelta(hours=12)
    df = pd.DataFrame(entries)
    df["timestamp"] = timestamp
    df["source"] = "nutrition_pdf"
    return ensure_schema(df, CARB_COLUMNS)
