from app.schemas.extraction import ExtractedValue, Vitals
from app.services.extraction.vitals_regex import extract_vitals
from app.services.triage.vitals_score import compute_news2, news2_priority


def V(**kw):
    return Vitals(**{k: ExtractedValue(value=v, confidence=1) for k, v in kw.items()})


def test_normal_vitals_score_zero():
    n = compute_news2(V(resp_rate=16, spo2=98, systolic_bp=125, pulse=75, temperature_c=37, consciousness="A", on_oxygen=False))
    assert n.total == 0 and n.band == "none" and not n.partial
    assert news2_priority(n) is None


def test_high_band():
    n = compute_news2(V(resp_rate=28, spo2=87, systolic_bp=104, pulse=118, temperature_c=38.9, consciousness="A"))
    # rr 3 + spo2 3 + sbp 1 + pulse 2 + temp 1 = 10
    assert n.total == 10 and n.band == "high" and n.partial
    assert news2_priority(n) == "P1"


def test_single_red_parameter_is_low_medium():
    n = compute_news2(V(consciousness="C"))
    assert n.total == 3 and n.band == "low-medium"


def test_not_applicable_in_children():
    n = compute_news2(V(pulse=140), age_years=4)
    assert not n.applicable


def test_regex_parses_fahrenheit_and_bp():
    hits = {h.field: h.value for h in extract_vitals("temp 102 F, BP 90/60, SpO2 88%")}
    assert hits["temperature_c"] == 38.9
    assert hits["systolic_bp"] == 90 and hits["diastolic_bp"] == 60
    assert hits["spo2"] == 88


def test_implausible_values_marked():
    hits = extract_vitals("SpO2 188")
    assert hits and not hits[0].plausible
