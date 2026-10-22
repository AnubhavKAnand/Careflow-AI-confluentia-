from datetime import date

from app.models.case import Source
from app.models.patient import Patient
from app.schemas.extraction import Evidence, ExtractedValue, Extraction, Symptom, Vitals
from app.services.triage.engine import compute_triage
from app.services.validation import validate
from app.services.validation import conflicts as C
from app.services.validation.followups import ai_followups
from app.services.validation import followups as F
from app.services.llm.base import LLMProvider


def sym(cid, negated=False):
    return Symptom(name=cid, canonical_id=cid, negated=negated, confidence=0.9,
                   evidence=Evidence(source_id=1, quote=cid, start=0, end=1, grounded=True))


def msg(text, sid=1, kind="patient_message", lang="en"):
    return Source(id=sid, case_id=1, kind=kind, original_text=text, language=lang)


def test_chest_pain_checklist_finds_gaps_and_asks_in_hinglish():
    ex = Extraction(symptoms=[sym("chest_pain")], age_years=ExtractedValue(value=58, confidence=1),
                    sex=ExtractedValue(value="male", confidence=1))
    p = Patient(name="R", age_years=58, sex="male", preferred_language="hi-en")
    rep, _ = validate(ex, [msg("seene mein dard", lang="hi-en")], p, {"chest_pain"})
    ids = {m.id for m in rep.missing}
    assert {"cp_vitals", "cp_radiation", "cp_sweating", "cp_breath"} <= ids
    assert "vitals" not in ids  # generic vitals item suppressed when a specific one is missing
    assert rep.missing[0].priority == "critical"
    q = next(f for f in rep.followups if f.id == "q:cp_sweating")
    assert q.language == "hi_latn" and "pasina" in q.text and q.answer_type == "yes_no" and q.symptom == "sweating"
    staff = next(f for f in rep.followups if f.id == "q:cp_vitals")
    assert staff.language == "en" and staff.target == "staff"
    assert 0 < rep.completeness < 1


def test_denied_symptom_counts_as_known():
    ex = Extraction(symptoms=[sym("chest_pain"), sym("sweating", negated=True)])
    rep, _ = validate(ex, [msg("chest pain, no sweating")], None, {"chest_pain"})
    assert "cp_sweating" not in {m.id for m in rep.missing}


def test_hindi_patient_gets_devanagari():
    ex = Extraction(symptoms=[sym("fever")])
    rep, _ = validate(ex, [msg("बुखार है", lang="hi")], Patient(name="K", preferred_language="hi"), set())
    q = next(f for f in rep.followups if f.target == "patient")
    assert q.language == "hi" and any("ऀ" <= ch <= "ॿ" for ch in q.text)


def test_wrong_patient_report_is_critical_and_lifts_priority():
    report = msg("Patient Name: Ramesh Kumar\nAge / Sex: 45 Years / Male\nHaemoglobin 13.0", sid=2, kind="report")
    ex = Extraction(symptoms=[sym("runny_nose")])
    p = Patient(name="Sita Devi", age_years=30, sex="female")
    rep, _ = validate(ex, [msg("cold"), report], p, set())
    c = next(x for x in rep.conflicts if x.kind == "wrong_patient")
    assert c.severity == "critical"
    assert compute_triage(ex, rep).priority == "P3"


def test_matching_name_with_honorific_is_fine():
    report = msg("Patient Name: Mrs. Sita Devi", sid=2, kind="report")
    assert not C.wrong_patient(Patient(name="Sita Devi"), [report])


def test_stale_and_future_reports():
    old = msg("Report Date: 01-01-2026", sid=2, kind="report")
    fut = msg("Report Date: 01-12-2026", sid=3, kind="report")
    kinds = {c.kind for c in C.report_dates([old, fut], today=date(2026, 10, 19))}
    assert kinds == {"stale_report", "report_date"}


def test_symptom_stated_in_one_source_denied_in_another():
    out = C.cross_source_symptoms([msg("I have fever since 2 days", 1), msg("No fever.", 2, kind="voice")])
    assert out and out[0].kind == "symptom"


def test_denied_fever_with_measured_temperature():
    ex = Extraction(symptoms=[sym("fever", negated=True)],
                    vitals=Vitals(temperature_c=ExtractedValue(value=38.6, confidence=1)))
    assert C.denied_vs_measured(ex)


def test_pregnancy_in_registered_male_is_critical():
    ex = Extraction(sex=ExtractedValue(value="male", confidence=1),
                    pregnancy_status=ExtractedValue(value="pregnant", confidence=0.8))
    assert C.demographic_consistency(ex)[0].severity == "critical"


def test_allergy_medication_clash():
    ex = Extraction(allergies=[ExtractedValue(value="penicillin", confidence=0.9)],
                    medications=[ExtractedValue(value="Amoxicillin 500 mg", confidence=0.9)])
    assert C.allergy_medication(ex)


class FakeQ(LLMProvider):
    name = "fakeq"

    @property
    def model_id(self):
        return "fake:q"

    def generate_json(self, system, user):
        return {"questions": [{"en": "Did the pain start during physical effort?", "local": "Kya dard mehnat karte waqt shuru hua?",
                               "why": "exertional onset"}]}


def test_ai_followups_tagged_and_localised(monkeypatch):
    monkeypatch.setattr(F, "provider_chain", lambda: [FakeQ()])
    monkeypatch.setattr(F.get_settings(), "llm_provider", "fakeq")
    qs, model = ai_followups(Extraction(symptoms=[sym("chest_pain")]), [], "hi_latn")
    assert model == "fake:q" and qs[0].origin == "ai" and qs[0].text.startswith("Kya") and qs[0].priority == "nice"
