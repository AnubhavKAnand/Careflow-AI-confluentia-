# Assumptions

The problem statement leaves several details open. These are the assumptions CareFlow AI is built on.

## Setting and users
- **Setting:** an outpatient department, primary health centre or tele-triage desk in India, where patient messages, voice notes and reports arrive faster than clinicians can read them.
- **Users:** intake staff (nurse, front desk or ASHA worker) enter cases; doctors and nurses review them. Patients do not see the AI's priority.
- **Decision support only:** the system suggests a review priority and drafts a note. It does not diagnose, prescribe or finalise. Every case needs clinician approval.

## Triage design
- **Priority bands:** four bands (P1 Immediate, P2 Very urgent, P3 Urgent, P4 Routine). Review-time targets (0 / 10 / 60 / 120 minutes) are adapted from the Manchester Triage System for an outpatient queue.
- **Red-flag rules** are adapted from the Manchester Triage System, the Emergency Severity Index, WHO Emergency Triage Assessment and Treatment (ETAT), WHO IMCI child danger signs, NEWS2, and Indian national guidelines (snakebite, rabies, dengue). They are a demonstration rule set, **not a validated clinical protocol**; a deployment would need sign-off by a clinical governance team.
- **Safety-first asymmetry:** missing an urgent case (under-triage) is treated as far worse than over-triage. Therefore: the most urgent signal wins; no model can lower a rule-based priority; uncertain or incomplete cases are never left at routine; conflicting vitals are resolved toward the more concerning value *for triage only*, and the conflict is shown to the clinician.
- **NEWS2** is computed only from vitals actually present (missing values are not assumed normal) and is shown for reference only for under-16s and in pregnancy, where it is not validated.

## Data and models
- **Demo data is synthetic.** No real patient data is used.
- **Small model first:** extraction runs on a local small language model (under 20B parameters, via Ollama). Gemini is a fallback. A deterministic rule-based extractor is the final fallback, so the system keeps working offline.
- **The model extracts; rules decide.** The model's job is to structure text. Priority comes from transparent rules and scores, with model-noticed signals allowed only to raise a routine case for review.
- **Registration data beats free text** for age and sex; disagreements are flagged.

## Reports and voice notes
- Reports arrive as phone photos, scans or PDFs. Text-layer PDFs are read directly; images go to local OCR first and are escalated to Gemini only when local confidence is low, to keep latency, cost and data sharing down.
- Voice notes are transcribed locally (faster-whisper on the clinic's GPU) where possible; Gemini is the fallback.
- A fact can never be more certain than the text it was read from: confidence is capped by the OCR/ASR confidence of that line or segment.
- Lab thresholds follow commonly used critical-value lists; a real deployment would use the local laboratory's critical-value policy.
- Indian report conventions are handled explicitly (platelets in lakh or "2,10,000" grouping, glucose in mg/dL, Hb in gm%). A missing unit lowers confidence rather than being assumed silently.
- When the report's age or name disagrees with registration, it may be another patient's document; this is flagged, never corrected.

## Validation and follow-up questions
- Follow-up questions only gather information. They never suggest a diagnosis or treatment.
- Patient questions are shown in the patient's language (Hindi in Devanagari, Hinglish in Roman script, or English); staff and clinician tasks are in English.
- A symptom counts as "known" when it is either reported or explicitly denied, so the system stops asking once the patient has answered.
- Missing information does not change priority by itself (that would flood the queue); it is shown as flags and questions. Suspicious instructions and critical conflicts (e.g. a report with another person's name) do lift a case to at least P3.
- Text that tries to instruct the AI is treated as a sign the document may be tampered with. It is masked from the model, but the deterministic symptom scanner still reads the full original, so a real symptom in the same sentence is not lost.
- Reports use the Indian DD-MM-YYYY date format; reports older than 30 days are flagged as possibly out of date.

## Languages
- English, Hindi (Devanagari) and Hinglish are covered directly by the multilingual symptom lexicon and the model.
- Other Indian languages (detected by script) are translated to English with a confidence score; the English symptom scanner then runs on the translation as a safety net. The original text is always shown to the clinician next to the translation.
- If no translation model is available for a language the lexicon does not cover, the case is flagged for review by someone who reads that language.

## Shadow learning
- The training signal is the clinician's final priority. One clinician's decisions vary (inter-rater disagreement in triage is well documented), so targets are relative: the agent must agree at least 80% of the time and under-triage no more often than the rules alone.
- Shadow mode lasts until the graduation checks pass on real reviews, typically months in a real clinic; the simulator compresses this to show the learning curve. Synthetic examples may warm the model up but never count toward sign-off.
- The simulated clinician's extra judgement (elderly fever, diabetes with vomiting, headache in pregnancy, small children with fever and vomiting) is illustrative of local practice, not clinical guidance.
- Outcome data (admission, ICU, safe discharge) would be a stronger label than the clinician's decision and would let the agent catch cases clinicians under-triage; it is future work.

## Evaluation
- Expected priorities in the evaluation set were assigned from case content using the triage guidance the rules are adapted from, by the developer, not by a panel of clinicians. A real validation would use independent clinician labels (and ideally outcomes) and report inter-rater agreement.
- The development set was used while building, so its figures are optimistic. The held-out set was written after the last change and never used for tuning; it is small (20 cases), so treat its percentages as indicative.
- The headline metric is under-triage of urgent (P1/P2) cases, because a missed urgent patient is the harm that matters most; over-triage is reported alongside it.

## Privacy and security
- **Consent first.** Nothing is processed until consent is recorded (with the consent text version and time). The patient receives a slip with the case number and a code.
- **Withdrawal** can be recorded by staff or done by the patient with the slip code, without an account. It takes effect immediately: the case leaves the queue, can no longer be opened by clinicians, and is not processed further.
- **Erasure** is a separate, deliberate step by the data protection officer, after withdrawal is recorded (so there is an auditable reason). It deletes uploaded files, messages, transcripts, extracted data, triage results, notes, clinician reviews and the patient record. The audit log keeps a tombstone with ids and counts only.
- **Least privilege.** Doctors and nurses see clinical content and decide. The intake desk registers patients and records answers but cannot read the clinical note or finalize. The data protection officer manages consent, erasure, users and the audit log but cannot read patient text, files or notes. Contact details are shown only to the desk and the data protection officer.
- **The audit log never contains patient free text** (no override reasons, no quotes from messages, no file names). This is what lets erasure leave the log untouched, so its hash chain stays verifiable.
- **External models only see redacted text.** Before any text goes to Gemini, the patient's name, phone numbers, email, Aadhaar, PAN, ABHA and hospital ID numbers are replaced with placeholders; symptoms, vitals and lab values are kept. Every external call is logged with the provider, purpose and number of identifiers removed. Images and audio cannot be redacted this way, so `EXTERNAL_DOCUMENTS_ALLOWED=false` keeps them on local engines.
- Local engines (Ollama, Tesseract, faster-whisper) keep data on the clinic's machine and need no redaction.
- Passwords are stored as salted PBKDF2-SHA256 hashes; sessions are signed JWTs valid for one shift (12 h) and kept in the browser tab's session storage, so closing the tab signs out on a shared computer.
- Design follows the intent of India's Digital Personal Data Protection Act, 2023 (consent, purpose limitation, right to erasure, accountability) and ABDM health-data principles. A real deployment would add encryption at rest, HTTPS, a retention schedule and a formal data protection impact assessment.
