# MediBot v5 — Changes & Improvements Guide

## What Was Added (Zero Breaking Changes)

### 1. New Trusted Knowledge Sources (`medical_data/trusted_sources/`)
| File | Source | Authority |
|---|---|---|
| `who_guidelines.txt` | WHO | 10/10 |
| `cdc_guidelines.txt` | CDC | 10/10 |
| `nih_medlineplus.txt` | NIH + MedlinePlus | 10/10 |
| `harrison_clinical_knowledge.txt` | Harrison's (educational) | 9/10 |
| `oxford_clinical_handbook.txt` | Oxford Handbook (educational) | 9/10 |
| `medical_report_patterns.txt` | Lab interpretation guide | 8/10 |

### 2. `rag/rag_engine.py` — Extensions
- `_get_source_metadata()`: Tags every document chunk with authority score, source name, trusted flag
- `_detect_topic()`: Classifies each chunk into 12 medical topic categories
- `_semantic_chunk_documents()`: Medical-aware separators (section headers, topic tags) preserve clinical context
- `_rerank_by_authority()`: WHO/CDC/NIH/Harrison's chunks bubble to the top of results
- `_build_source_citation()`: Attaches source names to every response
- `retrieve_with_priority()`: Public function for priority-weighted MMR retrieval
- `extract_medical_values()`: Detects 14 lab value patterns (glucose, HbA1c, creatinine, etc.)
- `build_enriched_query()`: Augments queries with lab value context for better RAG hits
- `build_vector_index()`: Now semantic-chunks + tags all docs (same interface)
- `build_rag_chain()`: MMR retrieval k=6, fetch_k=20 (was k=4 similarity)

### 3. `multimodal_handler.py` — Extensions
- Uses `retrieve_with_priority()` for all text/image/report queries
- Detects lab values in every query via `extract_medical_values()`
- Routes to `LAB_VALUE_PROMPT` when lab values detected
- Routes to `MEDICAL_REPORT_PROMPT` when report content detected
- Returns `_sources` citation in structured output
- Returns `lab_values` dict in API response

### 4. `prompts/system_prompts.py` — Additions
- `MEDICAL_REPORT_PROMPT`: Optimized for lab report interpretation with reference ranges
- `LAB_VALUE_PROMPT`: Activated when lab values detected; cites NIH reference ranges
- `XRAY_CORRELATION_PROMPT`: X-ray finding + clinical context from Harrison's/Oxford

### 5. `utils/file_utils.py` — Additions
- `is_valid_report()` / `validate_report_size()`: Report file validation
- `extract_report_text()`: PDF extraction with pypdf → pdfplumber fallback
- `preprocess_image_bytes()`: Normalizes X-ray images (RGB conversion, resize)
- `has_report_content()`: Detects medical report markers in query text

### 6. `flask_app/app.py` — Extensions
- Uses `extract_report_text()` from file_utils (cleaner, more robust)
- Uses `preprocess_image_bytes()` before X-ray analysis
- `/health` now returns version, trusted_sources status
- API response now includes `lab_values` dict

### 7. `build_index.py` — Extensions
- `--force` flag: `python build_index.py --force`
- Shows file counts before building
- Shows index size after building

## How to Upgrade from v4

```bash
# 1. Rebuild the FAISS index (required — trusted sources must be indexed)
python build_index.py --force

# 2. Run as normal
python run.py
```

## Lab Values MediBot Can Now Detect
glucose, HbA1c, creatinine, hemoglobin, blood pressure,
WBC, platelets, sodium, potassium, TSH, ALT, troponin,
cholesterol/LDL/HDL, SpO2, CRP, and more.

## Source Authority Scores
- WHO / CDC / NIH: 10  → Always retrieved first
- Harrison's / Oxford: 9  → Retrieved preferentially
- Medical report guide: 8  → High priority for lab queries
- General medical data: 3  → Background context
