"""
Lab-value detection: the patterns must fire on the way patients actually write,
not only on `label: value` formatting.
"""

import sys
from _bootstrap import ROOT, Result  # noqa: F401  (adds repo root to sys.path)

from utils.medical_values import extract_medical_values, build_enriched_query

r = Result()

print("\n[1] Punctuation-separated values (worked before)")
for text, expected in [
    ("glucose: 145 mg/dL",          {"glucose": "145"}),
    ("HbA1c=8.2",                   {"hba1c": "8.2"}),
    ("BP 120/80",                   {"blood_pressure": "120/80"}),
]:
    r.check(repr(text), extract_medical_values(text) == expected, f"-> {extract_medical_values(text)}")

print("\n[2] Natural phrasing (regression: these silently returned nothing)")
for text, expected in [
    ("my HbA1c is 8.2",             {"hba1c": "8.2"}),
    ("glucose was around 145",      {"glucose": "145"}),
    ("creatinine level of 2.1 mg/dL", {"creatinine": "2.1"}),
    ("My SpO2 reading is 88%",      {"spo2": "88"}),
    ("CRP came back at 46 mg/L",    {"crp": "46"}),
    ("potassium is 6.1",            {"potassium": "6.1"}),
    ("platelet count 90",           {"platelets": "90"}),
    ("troponin I 0.8",              {"troponin": "0.8"}),
]:
    r.check(repr(text), extract_medical_values(text) == expected, f"-> {extract_medical_values(text)}")

print("\n[3] Several values in one report line")
multi = extract_medical_values("Hemoglobin 9.1 g/dL, WBC 14.2, sodium 128 mEq/L")
r.check("three analytes found", multi == {"hemoglobin": "9.1", "wbc": "14.2", "sodium": "128"}, f"-> {multi}")

print("\n[4] No false positives on ordinary questions")
for text in [
    "what is pneumonia?",
    "I have had a headache for 3 days",
    "I am 45 years old with a cough",
    "should I take paracetamol twice a day",
]:
    r.check(repr(text), extract_medical_values(text) == {}, f"-> {extract_medical_values(text)}")

print("\n[5] Query enrichment")
r.check("no values -> query unchanged", build_enriched_query("what is anaemia", {}) == "what is anaemia")
enriched = build_enriched_query("is this bad", {"hba1c": "8.2"})
r.check("values -> reference-range terms appended",
        "hba1c" in enriched and "reference range" in enriched and enriched.startswith("is this bad"))

sys.exit(r.finish())
