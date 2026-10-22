"""Safety invariants of the triage engine."""
from app.schemas.extraction import Evidence, ExtractedValue, Extraction, Symptom, UrgencySignal, Vitals
from app.services.triage.engine import compute_triage


def sym(cid, name=None, negated=False, conf=0.9):
    return Symptom(name=name or cid, canonical_id=cid, negated=negated, confidence=conf,
                   evidence=Evidence(source_id=1, quote=name or cid, start=0, end=1, grounded=True))


def ok_vitals():
    return Vitals(**{k: ExtractedValue(value=v, confidence=1, evidence=Evidence(grounded=True, origin="form"))
                     for k, v in dict(spo2=98, pulse=76, resp_rate=16, systolic_bp=124, temperature_c=37.0,
                                      consciousness="A", on_oxygen=False).items()})


def test_routine_case_stays_p4():
    ex = Extraction(symptoms=[sym("runny_nose"), sym("sore_throat")], vitals=ok_vitals(),
                    chief_complaint=ExtractedValue(value="Sore throat", confidence=0.9))
    t = compute_triage(ex)
    assert t.priority == "P4"
    assert t.needs_human_review is True


def test_red_flag_wins_over_normal_vitals():
    ex = Extraction(symptoms=[sym("chest_pain"), sym("sweating")], vitals=ok_vitals())
    assert compute_triage(ex).priority == "P1"


def test_negated_symptoms_do_not_fire():
    ex = Extraction(symptoms=[sym("chest_pain", negated=True), sym("runny_nose")], vitals=ok_vitals())
    assert compute_triage(ex).priority == "P4"


def test_ai_signal_raises_to_p3_but_not_higher():
    ex = Extraction(symptoms=[sym("runny_nose")], vitals=ok_vitals(),
                    urgency_signals=[UrgencySignal(signal="symptoms worsening rapidly")])
    assert compute_triage(ex).priority == "P3"


def test_ai_signal_cannot_lower_red_flag():
    ex = Extraction(symptoms=[sym("snake_bite")], vitals=ok_vitals(),
                    urgency_signals=[UrgencySignal(signal="patient seems calm")])
    assert compute_triage(ex).priority == "P1"


def test_uncertainty_lifts_routine_to_p3():
    ex = Extraction(symptoms=[sym("runny_nose", conf=0.3)])
    t = compute_triage(ex)
    assert t.priority == "P3"
    assert t.data_quality.uncertain


def test_empty_extraction_is_never_routine():
    assert compute_triage(Extraction()).priority == "P3"


def test_reasons_carry_evidence():
    ex = Extraction(symptoms=[sym("chest_pain", "seene mein dard"), sym("sweating", "pasina")], vitals=ok_vitals())
    t = compute_triage(ex)
    flag_reason = next(r for r in t.reasons if r.kind == "red_flag")
    assert flag_reason.evidence and flag_reason.reference
