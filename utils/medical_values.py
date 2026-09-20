"""
utils/medical_values.py
------------------------
Lab-value detection, split out of rag_engine so it carries no heavy
dependencies (no torch / faiss / langchain) and can be unit-tested directly.
`rag.rag_engine` re-exports these names, so its public interface is unchanged.

Fix in this revision
--------------------
The old patterns only matched a value glued to its label by punctuation
("glucose: 145", "HbA1c=8.2"). Everything a patient actually types —
"my HbA1c is 8.2", "glucose was around 145", "creatinine level of 2.1" —
fell through, so lab mode never triggered and those questions were answered
by the generic path. The connector fragment below accepts those phrasings.
"""

import re
from typing import Dict

# Label → value connector: optional punctuation, an optional linking word, and
# optional punctuation again. Keeps "HbA1c is 8.2" and "HbA1c=8.2" both valid
# while staying tight enough not to swallow an unrelated number further along.
# The word group repeats, so multi-word phrasings ("was around", "level of",
# "reading is") match as well as single connectors. Each repetition must
# consume a whole word, so the pattern cannot loop on an empty match.
_CONN = (
    r"(?:[\s:=><~\-]*(?:is|was|are|were|of|at|about|around|approx\.?|"
    r"approximately|reads?|measured|came|back|level|levels|value|values|"
    r"reading|readings|result|results|count|now|currently|only|just)\b)*"
    r"[\s:=><~\-]*"
)

_NUM = r"(\d+\.?\d*)"


def _pattern(labels: str, unit: str = "") -> str:
    """Build `<label> <connector> <number> [unit]` for a group of label spellings."""
    return rf"\b(?:{labels})\b{_CONN}{_NUM}\s*(?:{unit})?" if unit \
        else rf"\b(?:{labels})\b{_CONN}{_NUM}"


LAB_VALUE_PATTERNS: Dict[str, str] = {
    "glucose":     _pattern(r"glucose|blood sugar|sugar level|FBS|RBS|PPBS", r"mg/dL|mg/dl|mmol/L"),
    "hba1c":       _pattern(r"HbA1c|Hb A1c|A1c|glycated haemoglobin|glycated hemoglobin", r"%"),
    "creatinine":  _pattern(r"creatinine|serum creatinine|Cr", r"mg/dL|mg/dl|μmol/L|umol/L"),
    "hemoglobin":  _pattern(r"haemoglobin|hemoglobin|Hb|Hgb", r"g/dL|g/dl|g/L"),
    "blood_pressure": rf"\b(?:BP|blood pressure)\b{_CONN}(\d{{2,3}})\s*/\s*(\d{{2,3}})",
    "wbc":         _pattern(r"WBC|white blood cells?|white cell count|leukocytes?|TLC"),
    "platelets":   _pattern(r"platelets?|platelet count|PLT|thrombocytes?"),
    "sodium":      _pattern(r"sodium|Na\+?", r"mEq/L|mmol/L"),
    "potassium":   _pattern(r"potassium|K\+?", r"mEq/L|mmol/L"),
    "tsh":         _pattern(r"TSH|thyroid stimulating hormone", r"mIU/L|μIU/mL|uIU/mL"),
    "alt":         _pattern(r"ALT|SGPT|alanine aminotransferase|alanine", r"U/L|IU/L"),
    "ast":         _pattern(r"AST|SGOT|aspartate aminotransferase", r"U/L|IU/L"),
    "bilirubin":   _pattern(r"bilirubin|total bilirubin|TBIL", r"mg/dL|mg/dl|μmol/L"),
    "troponin":    _pattern(r"troponin\s*[IT]?|Trop\s*[IT]?|TnI|TnT"),
    "cholesterol": _pattern(r"total cholesterol|cholesterol|LDL|HDL|triglycerides?", r"mg/dL|mg/dl|mmol/L"),
    "spo2":        _pattern(r"SpO2|SPO2|oxygen saturation|O2 sat|saturation", r"%"),
    "crp":         _pattern(r"CRP|C-reactive protein", r"mg/L|mg/dL"),
    "urea":        _pattern(r"blood urea nitrogen|BUN|urea", r"mg/dL|mg/dl|mmol/L"),
    "temperature": _pattern(r"temperature|temp|fever(?: of)?", r"°?[CF]|degrees?"),
}

_COMPILED = {name: re.compile(pattern, re.IGNORECASE) for name, pattern in LAB_VALUE_PATTERNS.items()}


def extract_medical_values(text: str) -> Dict[str, str]:
    """
    Extract lab values from a report or a free-text question.

    Examples
    --------
    "glucose 145 mg/dL"        → {"glucose": "145"}
    "my HbA1c is 8.2"          → {"hba1c": "8.2"}
    "BP was 150/95"            → {"blood_pressure": "150/95"}
    """
    if not text:
        return {}

    found: Dict[str, str] = {}
    for lab, regex in _COMPILED.items():
        match = regex.search(text)
        if not match:
            continue
        groups = [g for g in match.groups() if g]
        found[lab] = "/".join(groups) if len(groups) > 1 else groups[0]
    return found


def build_enriched_query(original_query: str, extracted_values: Dict[str, str]) -> str:
    """
    Augment the retrieval query with lab-value context so the vector search
    reaches the reference-range passages as well as the symptom passages.
    """
    if not extracted_values:
        return original_query

    parts = [
        f"{lab.replace('_', ' ')} level {value} interpretation reference range normal abnormal"
        for lab, value in extracted_values.items()
    ]
    return original_query + " " + " ".join(parts)
