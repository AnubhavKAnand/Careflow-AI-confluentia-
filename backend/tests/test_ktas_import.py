"""KTAS real-data importer: format quirks, label mapping, no outcome leakage, nurse baseline metric."""
import json

from app.services.evaluation import compute
from scripts.import_ktas import row_to_case, stratified

HDR = ("Group;Sex;Age;Patients number per hour;Arrival mode;Injury;Chief_complain;Mental;Pain;NRS_pain;SBP;DBP;HR;RR;BT;"
       "Saturation;KTAS_RN;Diagnosis in ED;Disposition;KTAS_expert;Error_group;Length of stay_min;KTAS duration_min;mistriage").split(";")


def _row(vals: str) -> dict:
    return dict(zip(HDR, vals.split(";")))


def test_row_mapping_and_missing_values():
    c = row_to_case(_row("2;2;80;6;2;1;dyspnea;2;0;#BOŞ!;90;50;130;30;37,8;??;3;Pneumonia;2;1;4;500;2,00;2"), 3)
    assert c["expected_priority"] == "P1" and c["nurse_priority"] == "P3"
    v = c["case"]["vitals"]
    assert v["temperature_c"] == 37.8 and "spo2" not in v and v["consciousness"] == "V"
    blob = json.dumps(c["case"]).lower()
    assert "pneumonia" not in blob  # diagnosis never reaches the system


def test_ktas_5_is_p4_and_unlabelled_rows_skipped():
    assert row_to_case(_row("2;1;30;6;3;2;ankle pain;1;1;3;120;70;80;18;36,4;99;4;Sprain;1;5;0;60;2,00;0"), 1)["expected_priority"] == "P4"
    assert row_to_case(_row("2;1;30;6;3;2;;1;1;3;120;70;80;18;36,4;99;4;x;1;5;0;60;2,00;0"), 2) is None


def test_stratified_keeps_all_p1():
    cases = [{"id": f"k{i}", "expected_priority": p} for i, p in enumerate(["P1"] * 5 + ["P3"] * 50 + ["P4"] * 50)]
    s = stratified(cases, 25, seed=1)
    assert sum(1 for c in s if c["expected_priority"] == "P1") == 5 and 20 <= len(s) <= 27


def test_nurse_baseline_scored_like_the_system():
    base = {"category": "real-ed", "language": "en", "expected_flags": [], "expected_flag_types": [], "fired_flags": [],
            "detected_flag_types": [], "latency_ms": 1, "split": "ktas-real"}
    rows = [{**base, "id": "a", "expected": "P1", "got": "P1", "nurse": "P3"},
            {**base, "id": "b", "expected": "P4", "got": "P3", "nurse": "P4"}]
    m = compute(rows)
    assert m["under_triage_urgent"] == 0 and m["nurse_baseline"]["under_triage_urgent"] == 1.0
    assert m["nurse_baseline"]["severe_under_triage"] == 1


def test_exclude_keeps_test_sample_disjoint(tmp_path):
    import subprocess, sys
    rows = [";".join(HDR)] + [f"2;2;{30+i};3;3;1;cough;1;1;2;120;80;80;18;36,6;98;4;x;1;4;0;60;2,00;0" for i in range(20)]
    csvf = tmp_path / "data.csv"
    csvf.write_text("\n".join(rows), encoding="utf-8")
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    run = lambda *x: subprocess.run([sys.executable, "-m", "scripts.import_ktas", str(csvf), *x], check=True, capture_output=True)
    run("--sample", "8", "--out", str(a))
    run("--sample", "8", "--seed", "3", "--split", "ktas-test", "--exclude", str(a), "--out", str(b))
    ida = {c["id"] for c in json.loads(a.read_text())["cases"]}
    cb = json.loads(b.read_text())["cases"]
    assert ida and cb and not ida & {c["id"] for c in cb} and all(c["split"] == "ktas-test" for c in cb)
