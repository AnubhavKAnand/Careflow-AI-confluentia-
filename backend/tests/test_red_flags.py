from app.schemas.extraction import Evidence, ExtractedValue, Vitals
from app.services.triage.red_flags import evaluate
from app.services.triage.text_match import scan


def _syms(*ids):
    return {i: [Evidence(quote=i)] for i in ids}


def ids(hits):
    return {h.rule_id for h in hits}


def test_cardiac_chest_pain_is_p1_and_subsumes_generic():
    hits = evaluate(_syms("chest_pain", "sweating"), Vitals())
    assert "cardiac_chest_pain" in ids(hits)
    assert "chest_pain" not in ids(hits)
    assert hits[0].priority == "P1"


def test_isolated_chest_pain_is_p2():
    hits = evaluate(_syms("chest_pain"), Vitals())
    assert ids(hits) == {"chest_pain"}


def test_low_spo2_vital_rule():
    v = Vitals(spo2=ExtractedValue(value=87, confidence=1))
    assert "hypoxia_severe" in ids(evaluate({}, v))
    v = Vitals(spo2=ExtractedValue(value=91, confidence=1))
    assert ids(evaluate({}, v)) == {"hypoxia"}


def test_pregnancy_rule_needs_pregnancy():
    assert "pregnancy_danger" not in ids(evaluate(_syms("vaginal_bleeding"), Vitals()))
    assert "pregnancy_danger" in ids(evaluate(_syms("vaginal_bleeding"), Vitals(), pregnant=True))


def test_infant_fever_age_gate():
    assert "infant_fever" in ids(evaluate(_syms("fever"), Vitals(), age_years=0))
    assert "infant_fever" not in ids(evaluate(_syms("fever"), Vitals(), age_years=30))


def test_scanner_hinglish_and_hindi():
    found = {m.canonical_id for m in scan("Seene mein dard hai aur pasina aa raha hai") if not m.negated}
    assert {"chest_pain", "sweating"} <= found
    found = {m.canonical_id for m in scan("सीने में दर्द और सांस फूलना") if not m.negated}
    assert {"chest_pain", "breathlessness"} <= found


def test_scanner_negation():
    m = {x.canonical_id: x.negated for x in scan("No chest pain, mild fever since 2 days")}
    assert m["chest_pain"] is True and m["fever"] is False
    m = {x.canonical_id: x.negated for x in scan("bukhar nahi hai")}
    assert m["fever"] is True
    # "fever is not coming down" must NOT read as "no fever"
    m = {x.canonical_id: x.negated for x in scan("bukhar nahi utar raha")}
    assert m["fever"] is False


def test_food_poisoning_is_not_poisoning():
    assert "poisoning" not in {m.canonical_id for m in scan("I think I have food poisoning")}
