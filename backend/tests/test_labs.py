from app.services.extraction.labs_regex import extract_labs


def labs(text):
    return {h.lab: h for h in extract_labs(text)}


def test_indian_platelet_formats():
    assert labs("Platelet Count : 18,000 /cumm")["platelets"].value == 18000
    assert labs("Platelets 0.4 lakh")["platelets"].value == 40000
    assert labs("Platelet count 2,10,000 /cumm")["platelets"].value == 210000
    assert labs("PLT 45 x10^3/uL")["platelets"].value == 45000


def test_missing_unit_lowers_confidence():
    h = labs("Platelet 1.2")["platelets"]
    assert h.value == 120000 and h.confidence < 0.6 and h.note


def test_common_chemistry():
    found = labs("Random Blood Sugar 48 mg/dL\nSerum Potassium 6.4 mmol/L\nS. Creatinine 1.1 mg/dl\nHb 6.8 gm%")
    assert found["glucose"].value == 48 and found["potassium"].value == 6.4
    assert found["creatinine"].value == 1.1 and found["hemoglobin"].value == 6.8


def test_hba1c_not_confused_with_haemoglobin():
    found = labs("Glycated Haemoglobin (HbA1c) 9.1 %\nHaemoglobin 12.1 g/dl")
    assert found["hba1c"].value == 9.1 and found["hemoglobin"].value == 12.1


def test_glucose_mmol_converted():
    assert labs("Blood glucose 2.5 mmol/L")["glucose"].value == 45


def test_qualitative():
    found = labs("Troponin I : Positive\nDengue NS1 Antigen   Negative")
    assert found["troponin"].value == "positive" and found["dengue_ns1"].value == "negative"


def test_implausible_flagged():
    assert labs("Haemoglobin 61 g/dL")["hemoglobin"].plausible is False
