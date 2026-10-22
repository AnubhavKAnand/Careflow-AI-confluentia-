# Requirements traceability

Every requirement in the problem statement, where it is implemented, and what checks it.

## Capture and structure patient information

| Requirement | Implementation | Verified by |
|---|---|---|
| Symptoms through text | `POST /api/cases`, `/api/cases/intake`; Intake page | `tests/test_api.py` |
| Symptoms through voice | In-browser recording (`VoiceRecorder.tsx`); `services/ingestion/audio.py` (faster-whisper → Gemini), segments with timestamps and confidence | `tests/test_ingestion.py` |
| OCR of sample medical reports | `services/ingestion/documents.py`: PDF text layer, Tesseract with boxes and confidence, Gemini escalation below 0.75; `labs_regex.py` for Indian unit styles | `tests/test_documents.py`, `tests/test_labs.py`, `tests/test_api_phase2.py` |
| When symptoms started and how they changed | Timeline, onset, duration and progression in `schemas/extraction.py`; shown as a timeline on the case page | `tests/test_extraction.py` |
| Identify missing important information | 15 complaint checklists (`rules/complaint_checklists.yaml`), completeness score | `tests/test_validation.py` |

## Multilingual

| Requirement | Implementation | Verified by |
|---|---|---|
| English, Hindi, Hinglish | Negation-aware lexicon with English, romanised Hindi and Devanagari synonyms (`rules/symptom_lexicon.yaml`) | `tests/test_red_flags.py` |
| Regional languages | Script detection (`language.py`), translation with confidence (`translation.py`), English scan of the translation | `tests/test_ingestion.py` (Tamil) |
| Show uncertainty in transcription / translation | `low_asr_confidence`, `low_translation_confidence`, `translation_unavailable`, `uncertain_language` flags; fact confidence capped by ASR/OCR confidence | `tests/test_ingestion.py` |

## Safety-first triage support

| Requirement | Implementation | Verified by |
|---|---|---|
| Rules and/or AI to find warning signs | 45 red-flag rules + NEWS2 (`services/triage/`); model urgency signals can only raise routine to P3 | `tests/test_engine.py`, `tests/test_vitals_score.py` |
| Prioritise for review | P1–P4 with review-time targets; queue sorted by urgency with waiting-time escalation capped below the next band | `tests/test_api.py` |
| Suggest follow-up questions | Rule-based questions in the patient's language, staff tasks, verification items, up to 3 small-model suggestions | `tests/test_validation.py`, `tests/test_followup_answers.py` |
| Immediately flag urgent cases | P1 at the top of the queue, crimson lane, "patients need immediate review" banner | `frontend/src/__tests__/pages.test.tsx` |

## Uncertain or conflicting information

| Requirement | Implementation | Verified by |
|---|---|---|
| Information does not match | Value discrepancies (vitals, labs, demographics), symptom stated vs denied across sources, denied vs measured, pregnancy vs sex/age, allergy vs medicine | `tests/test_validation.py`, `tests/test_extraction.py` |
| Report difficult to read | Legibility and OCR confidence; `poor_legibility` / `unreadable` flags; unreadable lifts to at least P3 | `tests/test_documents.py`, `tests/test_api_phase2.py` |
| Low-confidence extraction | Grounding halves confidence of untraceable facts; source-confidence cap; low-confidence labs flagged | `tests/test_extraction.py` |
| Suspicious instructions | `services/validation/injection.py` (EN / Hinglish / Hindi / hidden text); masked from models; flagged; at least P3 | `tests/test_injection.py` |
| Flag rather than guess or silently correct | Discrepancies recorded with both values; triage uses the more concerning value and says so | `tests/test_api.py::test_conflicting_vitals_flagged` |

## Human review and referral

| Requirement | Implementation | Verified by |
|---|---|---|
| Prioritised list of cases | Review queue (`pages/Dashboard.tsx`) | page tests |
| Show where information and flags came from | Evidence on every fact (source, span, page box or timestamp); source viewer | `tests/test_api_phase2.py::test_lab_evidence_points_at_report_line`, page tests |
| Approve, edit or override before finalizing | Versioned note, approve / override with required reason, role check | `tests/test_api.py::test_review_flow_and_audit` |

## Protect patient information

| Requirement | Implementation | Verified by |
|---|---|---|
| Ask for consent | Consent required before any processing; versioned consent; slip with a code | `tests/test_api.py::test_consent_required`, `tests/test_auth.py` |
| Withdraw or delete data | Staff or patient-code withdrawal; erasure of files, records and learning examples | `tests/test_privacy.py` |
| Restrict information by role | Permission matrix (`services/privacy/auth.py`), role-shaped responses | `tests/test_auth.py` |
| Record important actions by AI and humans | Hash-chained audit log with tamper check; no patient free text in the log | `tests/test_privacy.py` |

## Expected output

| Output | Where |
|---|---|
| Prioritised dashboard | Review queue |
| Structured summary | Case page, Patient summary |
| Alerts for urgent cases | Queue banner and lanes, critical banner on the case page |
| Flags for missing, unclear, conflicting information | Case page, flags panel; counts in the queue |
| AI-suggested follow-up questions | Case page, Follow-up questions |
| Links to the original source | Source tags and source viewer |
| Reviewable triage / referral note | Case page, Triage note and decision |

## Bonus

| Bonus | Implementation |
|---|---|
| Small language model under 20B | Local Ollama model for extraction, translation and questions; Gemini only as fallback; `scripts/run_eval.py --provider ollama` compares accuracy and latency |
| Additional innovation | Shadow-trained agent with graduation, blind checks and raise-only recommendations; similar-case memory; held-out evaluation; patient self-service withdrawal; identifier redaction before cloud calls |
