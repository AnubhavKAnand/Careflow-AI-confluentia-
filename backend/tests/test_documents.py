import pytest

from app.services.ingestion import documents
from app.services.ingestion.documents import DocResult, Line, process_document

needs_tesseract = pytest.mark.skipif(not documents.tesseract_available(), reason="tesseract not installed")


def test_pdf_text_layer_needs_no_ocr(sample_reports):
    r = process_document(sample_reports / "biochem_critical.pdf", "application/pdf")
    assert r.engine == "pdf-text-layer" and r.legibility == "good"
    assert "Serum Potassium 6.4 mmol/L" in r.text


@needs_tesseract
def test_clean_report_ocr_with_boxes(sample_reports):
    r = process_document(sample_reports / "cbc_dengue.png", "image/png")
    assert r.engine.startswith("tesseract") and r.legibility == "good"
    assert "18,000" in r.text
    line = next(ln for ln in r.lines if "Platelet" in ln.text)
    assert line.bbox and all(0 <= v <= 1000 for v in line.bbox)
    assert r.text[line.char_start:line.char_end] == line.text


@needs_tesseract
def test_blurry_report_is_flagged_poor(sample_reports):
    r = process_document(sample_reports / "cbc_blurry.jpg", "image/jpeg")
    assert r.legibility in ("poor", "unreadable")


@needs_tesseract
def test_escalates_to_gemini_only_when_local_is_weak(sample_reports, monkeypatch):
    calls = []

    def fake_gemini(data, mime):
        calls.append(mime)
        return documents._finish(DocResult(lines=[Line("Platelet Count 18,000 /cumm", 0.9)], engine="gemini:fake"))

    monkeypatch.setattr(documents, "ocr_gemini", fake_gemini)
    monkeypatch.setattr(documents.get_settings(), "ocr_engines", "tesseract,gemini")
    good = process_document(sample_reports / "cbc_dengue.png", "image/png")
    assert not calls and good.engine.startswith("tesseract")
    weak = process_document(sample_reports / "cbc_blurry.jpg", "image/jpeg")
    assert calls and weak.engine == "gemini:fake"
    assert [a["engine"].split(":")[0] for a in weak.attempts] == ["tesseract", "gemini"]


def test_nothing_available_is_unreadable(sample_reports, monkeypatch):
    monkeypatch.setattr(documents.get_settings(), "ocr_engines", "")
    r = process_document(sample_reports / "cbc_dengue.png", "image/png")
    assert r.legibility == "unreadable" and not r.text


def test_gemini_ocr_response_parsing(monkeypatch, sample_reports):
    class FakeGemini:
        model = "fake"

        def is_available(self):
            return True

        def generate_json(self, system, user, parts=None):
            assert parts and parts[0]["inline_data"]["mime_type"] == "image/png"
            return {"language": "hi", "legibility": "fair",
                    "lines": [{"page": 1, "text": "हीमोग्लोबिन 6.1 g/dL", "confidence": 0.8, "box_2d": [100, 50, 130, 600]},
                              {"page": 1, "text": "Dr. [illegible]", "confidence": 0.9, "box_2d": [140, 50, 160, 300]}],
                    "illegible_parts": ["doctor's signature"],
                    "translation_en": "Haemoglobin 6.1 g/dL", "translation_confidence": 0.9}

    monkeypatch.setattr(documents, "get_provider", lambda name: FakeGemini())
    r = documents.ocr_gemini(b"img", "image/png")
    assert r.lines[0].bbox == [50, 100, 600, 130]  # [ymin,xmin,ymax,xmax] -> [x0,y0,x1,y1]
    assert r.lines[1].confidence <= 0.3  # [illegible] caps confidence
    assert r.legibility in ("fair", "poor") and r.translation_en.startswith("Haemoglobin")
    assert any("signature" in n for n in r.notes)
