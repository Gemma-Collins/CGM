import pandas as pd

from health_aggregator.importers import nutrition_pdf


def test_extract_entries_associates_heading_with_following_numbers():
    text = """
    Grilled Chicken Salad
    Carbs: 12g
    Calories: 320 kcal

    Oatmeal with Berries
    Total Carbohydrate 45 g
    Energy 210
    """
    entries = nutrition_pdf._extract_nutrition_entries(text)
    assert len(entries) == 2
    assert entries[0] == {"food_name": "Grilled Chicken Salad", "carbs_g": 12.0, "calories_kcal": 320.0}
    assert entries[1] == {"food_name": "Oatmeal with Berries", "carbs_g": 45.0, "calories_kcal": 210.0}


def test_extract_entries_same_line_carbs_and_calories():
    text = "Toast\nCarbs: 20g, Calories: 150kcal"
    entries = nutrition_pdf._extract_nutrition_entries(text)
    assert entries == [{"food_name": "Toast", "carbs_g": 20.0, "calories_kcal": 150.0}]


def test_extract_entries_carbs_without_calories_still_recorded():
    text = "Apple\nCarbs: 25g"
    entries = nutrition_pdf._extract_nutrition_entries(text)
    assert entries == [{"food_name": "Apple", "carbs_g": 25.0, "calories_kcal": None}]


def test_extract_entries_uses_unknown_when_no_heading_found():
    text = "Carbs: 10g"
    entries = nutrition_pdf._extract_nutrition_entries(text)
    assert entries[0]["food_name"] == "unknown"


def test_extract_entries_handles_no_matches():
    assert nutrition_pdf._extract_nutrition_entries("Just some unrelated text.") == []


def test_looks_like_heading_rejects_lines_with_nutrition_numbers():
    assert nutrition_pdf._looks_like_heading("Carbs: 10g") is False
    assert nutrition_pdf._looks_like_heading("Grilled Chicken Salad") is True
    assert nutrition_pdf._looks_like_heading("") is False


def test_parse_pdf_extracts_and_timestamps_entries(tmp_path):
    fpdf = __import__("fpdf").FPDF
    pdf = fpdf()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    for line in ["Grilled Chicken Salad", "Carbs: 12g", "Calories: 320 kcal"]:
        pdf.cell(0, 10, text=line, new_x="LMARGIN", new_y="NEXT")
    pdf_path = tmp_path / "nutrition.pdf"
    pdf.output(str(pdf_path))

    df = nutrition_pdf.parse_pdf(str(pdf_path), date="2026-08-15")

    assert len(df) == 1
    assert df.iloc[0]["food_name"] == "Grilled Chicken Salad"
    assert df.iloc[0]["carbs_g"] == 12.0
    assert df.iloc[0]["calories_kcal"] == 320.0
    assert df.iloc[0]["timestamp"] == pd.Timestamp("2026-08-15")
    assert df.iloc[0]["source"] == "nutrition_pdf"


def test_parse_pdf_defaults_to_noon_today_when_no_date_given(tmp_path):
    fpdf = __import__("fpdf").FPDF
    pdf = fpdf()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.cell(0, 10, text="Carbs: 5g", new_x="LMARGIN", new_y="NEXT")
    pdf_path = tmp_path / "nutrition.pdf"
    pdf.output(str(pdf_path))

    df = nutrition_pdf.parse_pdf(str(pdf_path))

    assert df.iloc[0]["timestamp"] == pd.Timestamp.now().normalize() + pd.Timedelta(hours=12)


def test_parse_pdf_returns_empty_frame_when_nothing_extracted(tmp_path):
    fpdf = __import__("fpdf").FPDF
    pdf = fpdf()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.cell(0, 10, text="Just a title page with no numbers", new_x="LMARGIN", new_y="NEXT")
    pdf_path = tmp_path / "empty.pdf"
    pdf.output(str(pdf_path))

    df = nutrition_pdf.parse_pdf(str(pdf_path))
    assert df.empty
