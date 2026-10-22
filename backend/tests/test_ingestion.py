"""Voice notes, translation and source-quality handling (models faked; no network)."""
import json

from app.services.ingestion import processor, translation
from app.services.ingestion.audio import AudioResult, Segment, _finish
from app.services.llm.base import LLMProvider

PATIENT = {"name": "Voice Test", "age_years": 52, "sex": "male"}


def _audio(segments, lang="hi-en", lang_conf=0.9):
    return _finish(AudioResult(segments=[Segment(*s) for s in segments], language=lang,
                               language_confidence=lang_conf, engine="faster-whisper:fake"))


def _post_voice(client, name="note.webm"):
    return client.post("/api/cases/intake",
                       data={"payload": json.dumps({"patient": PATIENT, "consent_given": True})},
                       files=[("files", (name, b"fake-audio-bytes", "audio/webm"))])


def test_voice_note_transcript_drives_triage_with_timestamps(client, monkeypatch):
    monkeypatch.setattr(processor, "process_audio", lambda p, m: _audio([
        ("Doctor sahab, subah se seene mein dard hai", 0.0, 3.2, 0.91),
        ("aur bahut pasina aa raha hai", 3.2, 5.8, 0.88),
    ]))
    d = _post_voice(client).json()
    assert d["triage"]["priority"] == "P1"
    voice = next(s for s in d["sources"] if s["kind"] == "voice")
    assert voice["has_file"] and voice["reading"]["segments"][1]["start_s"] == 3.2
    sweat = next(s for s in d["extraction"]["symptoms"] if s["canonical_id"] == "sweating")
    assert sweat["evidence"]["locator"] == {"start_s": 3.2, "end_s": 5.8}
    # original file can be played back
    r = client.get(f"/api/sources/{voice['id']}/file")
    assert r.status_code == 200 and r.content == b"fake-audio-bytes"


def test_unclear_audio_is_flagged_and_caps_confidence(client, monkeypatch):
    monkeypatch.setattr(processor, "process_audio", lambda p, m: _audio([
        ("mujhe khansi hai", 0.0, 2.0, 0.42),
    ]))
    d = _post_voice(client).json()
    kinds = {f["kind"] for f in d["extraction"]["source_flags"]}
    assert "low_asr_confidence" in kinds
    cough = next(s for s in d["extraction"]["symptoms"] if s["canonical_id"] == "cough")
    assert cough["confidence"] <= 0.42
    assert d["triage"]["data_quality"]["uncertain"] and d["triage"]["priority"] == "P3"


def test_failed_transcription_is_critical_not_ignored(client, monkeypatch):
    monkeypatch.setattr(processor, "process_audio", lambda p, m: AudioResult(attempts=[{"engine": "whisper", "error": "x"}]))
    d = _post_voice(client).json()
    assert any(f["kind"] == "unreadable" and f["severity"] == "critical" for f in d["extraction"]["source_flags"])
    assert d["triage"]["priority"] == "P3"


class FakeTranslator(LLMProvider):
    name = "fake"

    @property
    def model_id(self):
        return "fake:translator"

    def generate_json(self, system, user):
        return {"translation": "Since yesterday my child has been having fits and high fever.", "confidence": 0.86,
                "uncertain_phrases": []}


def test_regional_language_translated_and_scanned(client, monkeypatch):
    # Tamil-script message: not covered by the lexicon, so the English translation is the safety net
    monkeypatch.setattr(translation, "provider_chain", lambda: [FakeTranslator()])
    monkeypatch.setattr(translation.get_settings(), "llm_provider", "fake")
    body = {"patient": {"name": "Tamil Test", "age_years": 4, "sex": "female"}, "consent_given": True,
            "message": "நேற்று முதல் என் குழந்தைக்கு வலிப்பு மற்றும் அதிக காய்ச்சல்"}
    d = client.post("/api/cases", json=body).json()
    src = d["sources"][0]
    assert src["language"] == "ta" and src["translated_text"].startswith("Since yesterday")
    seizure = next(s for s in d["extraction"]["symptoms"] if s["canonical_id"] == "seizure")
    assert seizure["evidence"]["in_translation"] is True
    assert d["triage"]["priority"] == "P1"


def test_untranslatable_regional_language_is_flagged(client):
    body = {"patient": {"name": "Bengali Test", "age_years": 40, "sex": "male"}, "consent_given": True,
            "message": "আমার মাথা ব্যথা করছে"}
    d = client.post("/api/cases", json=body).json()
    flag = next(f for f in d["extraction"]["source_flags"] if f["kind"] == "translation_unavailable")
    assert flag["severity"] == "warning"
    assert d["triage"]["priority"] in ("P1", "P2", "P3")  # never silently routine


def test_rejects_unsupported_upload(client):
    r = client.post("/api/cases/intake",
                    data={"payload": json.dumps({"patient": PATIENT, "consent_given": True})},
                    files=[("files", ("virus.exe", b"MZ...", "application/octet-stream"))])
    assert r.status_code == 422
