# Demo video script (about 5 minutes)

**Before recording**
1. `python -m scripts.make_samples` and `python -m scripts.seed_db --reset --bootstrap 300`.
2. Start backend and frontend; have Ollama running if you will show the small model.
3. Two browser windows: one signed in as `dr.mehra`, one private window for the intake desk (`desk.ravi`).
4. Record a short Hinglish voice note on your phone: "Subah se seene mein dard hai aur bahut pasina aa raha hai." Save it as `voice.m4a`.
5. Zoom the browser to 110% so text is readable in the recording.

---

**0:00 – 0:25 The problem.** "A clinic gets messages, voice notes and report photos in many languages faster than doctors can read them. CareFlow reads them, says who to see first and why, flags what's missing or doesn't add up, and leaves every decision to a clinician."

**0:25 – 1:15 Intake with voice and a report (intake desk window).**
- New case: tick consent (point at the Hindi text), name "Ramesh", 58, male.
- Upload `voice.m4a` and `cbc_dengue.png`. Submit.
- Show the consent slip with case number and withdrawal code. "The patient can withdraw any time with this, no account needed."

**1:15 – 2:30 The case (doctor window).**
- Queue: the new case at the top in the crimson lane; point at the time-to-target bar.
- Open it. "Why this priority": cardiac chest pain from the voice note, critical platelets from the report.
- Click the sweating source tag: the audio jumps to the second it was said. Click the platelet tag: the report line is boxed.
- Flags panel: what's missing (pulse, BP, SpO2). Follow-up questions in Hinglish for the patient, a measurement task for staff.
- Type "pulse 112, BP 150/94, SpO2 95" in the staff task and save: the case re-checks and completeness rises.

**2:30 – 3:15 Safety.**
- Open `c14` (tampered report): "Text aimed at the AI" flag; the instruction was hidden from the model and the case lifted to P3.
- Open `c12` (blurry report): flagged hard to read, no values guessed.
- Open `c07`: patient said oxygen 86, the desk measured 95; both shown, the more concerning used, clinician asked to verify.

**3:15 – 3:45 Decision.**
- On a case, edit the note, choose a different priority, type a reason, finalize. "Overrides need a reason, and every action is in the audit log." Open Audit log, click *Check for tampering*: intact.

**3:45 – 4:30 Learning from clinicians.**
- Learning page: shadow mode, the agent's guesses are hidden so they can't sway anyone. Graduation checklist.
- Run simulation: agent abstains early, then overtakes the rules; pattern table (elderly fever, diabetes with vomiting, headache in pregnancy learned; young chest pain deliberately not downgraded).
- "It can only ever raise a priority, never lower one."

**4:30 – 4:50 Evaluation.**
- Evaluation page: development vs held-out. "Offline, the keyword safety net is strong on phrasings it knows and weak on new ones; that's why a local small model does the reading and the rules are the backstop." Show the small-model row if you ran it.

**4:50 – 5:00 Privacy and close.**
- Sign in as `admin`: priority visible, patient text hidden. Data requests: erase a withdrawn patient. "Built solo in three days. Every decision stays with the clinician."

---

## Shorter walkthrough cases

| Case | Shows |
|---|---|
| `c01` | Hinglish chest pain caught by the deterministic scanner even with no model |
| `c06` | "No chest pain. No fever." stays routine |
| `c08` | Vague message lifted to P3, not left at the bottom |
| `c11` | Dengue report photo, platelets 18,000 → P1, line boxed |
| `c13` | Lab PDF read from its text layer, glucose 48 and potassium 6.4 → P1 |
| `c15` | Report age 34 vs registration 61: possibly another patient's report |
