"""Compact prompt shape, JSON-schema output, grounding gates and coverage additions."""
from app.models.case import Source
from app.models.patient import Patient
from app.services.extraction import extractor, prompts
from app.services.extraction.vitals_regex import extract_vitals
from app.services.llm.base import LLMProvider
from app.services.triage.red_flags import evaluate
from app.schemas.extraction import Vitals
from app.services.triage.text_match import canonicalize

MSG = "Kal raat se tez bukhar hai, aaj saans phool rahi hai. Oxygen 90 dikha raha tha."


class SchemaModel(LLMProvider):
    name = "fake"
    supports_schema = True

    def __init__(self, response):
        self.response, self.schemas = response, []

    @property
    def model_id(self):
        return "fake:schema"

    def generate_json(self, system, user, schema=None):
        self.schemas.append(schema)
        return self.response


def _run(monkeypatch, provider, patient=None):
    monkeypatch.setattr(extractor, "provider_chain", lambda: [provider])
    monkeypatch.setattr(extractor.get_settings(), "llm_provider", "fake")
    src = [Source(id=1, case_id=1, kind="patient_message", original_text=MSG)]
    return extractor.extract(src, patient)[0]


def test_compact_shape_with_symptom_ids(monkeypatch):
    resp = {"chief_complaint": "fever", "age_years": None, "sex": None, "pregnant": None,
            "symptoms": [{"id": "fever", "name": "high fever", "negated": False, "quote": "tez bukhar"},
                         {"id": "other", "name": "tiredness", "negated": False, "quote": "thak gaya"}],
            "vitals": {"spo2": 90}, "labs": [], "urgency_signals": [], "uncertainties": []}
    m = SchemaModel(resp)
    ex = _run(monkeypatch, m)
    assert m.schemas[0] is not None and "fever" in m.schemas[0]["properties"]["symptoms"]["items"]["properties"]["id"]["enum"]
    fever = next(s for s in ex.symptoms if s.canonical_id == "fever")
    assert fever.evidence.grounded and fever.confidence > 0.5
    assert ex.vitals.spo2.value == 90
    assert ex.timeline, "timeline is filled deterministically on the model path"


def test_ungrounded_urgency_signal_is_not_used(monkeypatch):
    resp = {"symptoms": [], "urgency_signals": [
        {"signal": "symptoms getting rapidly worse", "quote": "symptoms getting rapidly worse"},
        {"signal": "oxygen dropping", "quote": "Oxygen 90"}]}
    ex = _run(monkeypatch, SchemaModel(resp))
    assert [u.signal for u in ex.urgency_signals] == ["oxygen dropping"]
    assert any("rapidly worse" in u for u in ex.uncertainties)


def test_model_only_demographic_conflict_needs_a_quote(monkeypatch):
    resp = {"age_years": 25, "sex": "male", "symptoms": []}  # invented, nothing in the text
    ex = _run(monkeypatch, SchemaModel(resp), Patient(name="X", age_years=60, sex="female"))
    assert not [d for d in ex.discrepancies if d.field in ("age_years", "sex")]
    assert ex.age_years.value == 60


def test_old_shape_still_accepted_without_schema(monkeypatch):
    class Plain(LLMProvider):
        name = "plain"
        model_id = "fake:plain"

        def generate_json(self, system, user):
            return {"symptoms": [{"name": "Fever", "confidence": 0.9, "evidence": {"quote": "tez bukhar"}}]}

    ex = _run(monkeypatch, Plain())
    assert any(s.canonical_id == "fever" for s in ex.symptoms)


def test_prompt_has_no_parrotable_example():
    assert "rapidly worse" not in prompts.EXTRACTION_SYSTEM
    assert "chest_pain" in prompts.build_user_prompt([])


def test_token_subset_canonicalize():
    assert canonicalize("speech became slurred") == "slurred_speech"
    assert canonicalize("weakness of left arm") == "one_sided_weakness"
    assert canonicalize("random words here") is None


def test_loose_fever_temperature():
    t = lambda s: [h.value for h in extract_vitals(s) if h.field == "temperature_c"]
    assert t("fever 103 since night") == [39.4]
    assert t("fever 10 days") == []


def test_palpitations_rules():
    ev = lambda ids: {h.rule_id for h in evaluate({i: [] for i in ids}, Vitals())}
    assert ev(["palpitations"]) == {"palpitations"}
    assert ev(["palpitations", "dizziness"]) == {"palpitations_unstable"}


def test_signal_naming_a_symptom_is_promoted_only_if_the_quote_supports_it(monkeypatch):
    resp = {"symptoms": [], "urgency_signals": [
        {"signal": "seizure (Seizure / fits)", "quote": "Oxygen 90"},        # echo of the symptom list
        {"signal": "breathlessness", "quote": "saans phool rahi hai"},       # already detected by the scanner
        {"signal": "fainting", "quote": "tez bukhar"}]}                      # quote says nothing about fainting
    ex = _run(monkeypatch, SchemaModel(resp))
    ids = {s.canonical_id for s in ex.symptoms}
    assert "seizure" not in ids and "fainting" not in ids and not ex.urgency_signals


def test_signal_promoted_when_quote_matches(monkeypatch):
    msg_resp = {"symptoms": [], "urgency_signals": [{"signal": "fever", "quote": "tez bukhar"}]}
    m = SchemaModel(msg_resp)
    ex = _run(monkeypatch, m)
    assert any(s.canonical_id == "fever" for s in ex.symptoms) and not ex.urgency_signals


def test_model_id_overruled_by_its_own_words(monkeypatch):
    resp = {"symptoms": [{"id": "palpitations", "name": "breathlessness", "negated": False, "quote": "saans phool rahi hai"}]}
    ex = _run(monkeypatch, SchemaModel(resp))
    assert "palpitations" not in {s.canonical_id for s in ex.symptoms}


def test_unsupported_model_id_is_dropped_to_free_text(monkeypatch):
    resp = {"symptoms": [{"id": "seizure", "name": "fits", "negated": False, "quote": "Oxygen 90 dikha raha tha"}]}
    ex = _run(monkeypatch, SchemaModel(resp))
    assert "seizure" not in {s.canonical_id for s in ex.symptoms}
    assert any("doesn't say" in u for u in ex.uncertainties)


def test_model_negation_must_match_the_quote(monkeypatch):
    resp = {"symptoms": [{"id": "fever", "name": "fever", "negated": True, "quote": "tez bukhar"}]}
    ex = _run(monkeypatch, SchemaModel(resp))
    assert not [d for d in ex.discrepancies if d.field == "symptom.fever"]
    assert any(s.canonical_id == "fever" and not s.negated for s in ex.symptoms)


def test_parroted_free_text_signal_and_junk_uncertainties_removed(monkeypatch):
    resp = {"symptoms": [], "urgency_signals": [{"signal": "cannot walk", "quote": "tez bukhar"}],
            "uncertainties": ["snake bite", "head_injury", "cannot_walk", "Not clear since when the fever started"]}
    ex = _run(monkeypatch, SchemaModel(resp))
    assert not ex.urgency_signals
    assert "Not clear since when the fever started" in ex.uncertainties
    assert not {"snake bite", "head_injury", "cannot_walk"} & set(ex.uncertainties)
