"""Model path: loose JSON from a (fake) model is normalised, merged with deterministic checks and grounded."""
from app.models.case import Source
from app.models.patient import Patient
from app.services.extraction import extractor
from app.services.llm.base import LLMError, LLMProvider


class FakeModel(LLMProvider):
    name = "fake"

    def __init__(self, response=None, fail=False):
        self.response, self.fail = response, fail

    @property
    def model_id(self):
        return "fake:test"

    def generate_json(self, system, user):
        if self.fail:
            raise LLMError("boom")
        return self.response


MSG = "Kal raat se tez bukhar hai, aaj saans phool rahi hai. Oxygen 90 dikha raha tha. Age 40 saal."


def _sources():
    return [Source(id=1, case_id=1, kind="patient_message", original_text=MSG)]


def _run(monkeypatch, provider):
    monkeypatch.setattr(extractor, "provider_chain", lambda: [provider])
    monkeypatch.setattr(extractor.get_settings(), "llm_provider", "fake")
    return extractor.extract(_sources(), Patient(name="X", age_years=40, sex="female"))[0]


def test_model_output_is_normalised_and_grounded(monkeypatch):
    resp = {
        "chief_complaint": "High fever and breathlessness",  # bare string instead of value field
        "symptoms": [
            {"name": "Fever", "severity": "severe", "confidence": 0.9, "evidence": {"source_id": 1, "quote": "tez bukhar"}},
            {"name": "Shortness of breath", "confidence": "0.85", "evidence": "saans phool rahi hai"},  # string evidence
            {"name": "Headache", "confidence": 0.8, "evidence": {"source_id": 1, "quote": "sir dard bahut"}},  # hallucinated
        ],
        "vitals": {"spo2": {"value": "90%", "confidence": 0.9, "evidence": {"source_id": 1, "quote": "Oxygen 90"}}},
        "urgency_signals": ["breathing difficulty started today"],
    }
    ex = _run(monkeypatch, FakeModel(resp))
    assert ex.provider == "fake:test" and not ex.fallback_used
    by = {s.canonical_id: s for s in ex.symptoms}
    assert by["fever"].evidence.grounded and MSG[by["fever"].evidence.start:by["fever"].evidence.end] == "tez bukhar"
    assert by["breathlessness"].evidence.grounded
    # quote not in the source -> ungrounded and confidence halved
    assert by["headache"].evidence.grounded is False and by["headache"].confidence == 0.4
    assert ex.vitals.spo2.value == 90
    assert ex.age_years.value == 40


def test_vital_disagreement_recorded(monkeypatch):
    resp = {"symptoms": [], "vitals": {"spo2": {"value": 96, "confidence": 0.9, "evidence": {"quote": "Oxygen 90"}}}}
    ex = _run(monkeypatch, FakeModel(resp))
    assert ex.vitals.spo2.value == 90  # deterministic parser wins
    assert any(d.field == "vitals.spo2" for d in ex.discrepancies)


def test_missed_symptom_added_by_scanner(monkeypatch):
    resp = {"symptoms": [{"name": "Fever", "confidence": 0.9, "evidence": {"quote": "tez bukhar"}}]}
    ex = _run(monkeypatch, FakeModel(resp))
    lex = [s for s in ex.symptoms if s.canonical_id == "breathlessness"]
    assert lex and lex[0].evidence.origin == "lexicon"


def test_model_failure_falls_back_to_rules(monkeypatch):
    ex = _run(monkeypatch, FakeModel(fail=True))
    assert ex.fallback_used and ex.provider == "rules"
    assert ex.provider_errors and "boom" in ex.provider_errors[0]
    assert {"fever", "breathlessness"} <= {s.canonical_id for s in ex.symptoms}


def test_model_lab_misread_is_overruled_and_recorded(monkeypatch):
    src = Source(id=1, case_id=1, kind="report", original_text="Platelet Count : 18,000 /cumm (1.5 - 4.5 lakh)")
    resp = {"labs": [{"name": "Platelet Count", "value": "1,80,000", "unit": "/cumm", "reference_range": "1.5 - 4.5 lakh",
                      "confidence": 0.9, "evidence": {"source_id": 1, "quote": "Platelet Count : 18,000"}}]}
    monkeypatch.setattr(extractor, "provider_chain", lambda: [FakeModel(resp)])
    monkeypatch.setattr(extractor.get_settings(), "llm_provider", "fake")
    ex = extractor.extract([src], None)[0]
    plt = next(lab for lab in ex.labs if lab.canonical_id == "platelets")
    assert plt.value == 18000 and plt.reference_range == "1.5 - 4.5 lakh"
    assert any(d.field == "labs.platelets" for d in ex.discrepancies)
