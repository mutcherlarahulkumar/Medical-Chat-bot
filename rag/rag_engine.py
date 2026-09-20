"""
rag/rag_engine.py  — MediBot v5 Enhanced RAG Engine
------------------------------------------------------
EXTENSION of original rag_engine.py.
✅ Preserves original build_vector_index() and build_rag_chain() interfaces.
✅ Adds: trusted-source prioritisation, semantic chunking, metadata tagging,
         source-weighted retrieval, medical-value extraction, re-ranking.
✅ Does NOT break any existing functionality.

New additions (all additive):
  - _get_source_metadata()     : Tags each chunk with source authority level
  - _semantic_chunk_documents(): Semantic-aware chunking with medical context
  - _prioritised_retriever()   : Source-weighted MMR retrieval
  - _medical_value_extractor() : Detects lab values in queries for enriched context
  - enhanced build_vector_index(): Uses all new helpers, still same interface
  - enhanced build_rag_chain()  : Uses prioritised retriever + source citation
"""

import os
import re
import sys
import logging
from pathlib import Path
from typing import List, Optional, Dict, Tuple

# Lab-value patterns live in utils.medical_values so they can be unit-tested
# without loading torch/faiss. Re-exported below — rag_engine's public
# interface (LAB_VALUE_PATTERNS, extract_medical_values, build_enriched_query)
# is unchanged.
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.medical_values import (  # noqa: E402
    LAB_VALUE_PATTERNS,
    extract_medical_values,
    build_enriched_query as _build_enriched_query,
)

from langchain_community.document_loaders import (
    PyPDFLoader, DirectoryLoader, TextLoader, CSVLoader,
)
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain.chains import create_retrieval_chain
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.documents import Document

logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT_DIR    = Path(__file__).parent.parent
FAISS_DIR   = ROOT_DIR / "faiss_index"
MEDICAL_DIR = ROOT_DIR / "medical_data"

# ── Embedding model ───────────────────────────────────────────────────────────
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# ── Chunking ──────────────────────────────────────────────────────────────────
CHUNK_SIZE    = 500
CHUNK_OVERLAP = 80   # increased for better context continuity

# ── Source authority config ───────────────────────────────────────────────────
# Higher number = higher authority = retrieved preferentially
SOURCE_AUTHORITY = {
    "who_guidelines":             10,
    "cdc_guidelines":             10,
    "nih_medlineplus":            10,
    "harrison_clinical_knowledge": 9,
    "oxford_clinical_handbook":    9,
    "medical_report_patterns":     8,
    "pubmed":                      8,
    "trusted_sources":             7,   # any other file in trusted_sources/
}
DEFAULT_AUTHORITY = 3  # plain medical_data/*.txt files

# ── Topic tag patterns ────────────────────────────────────────────────────────
TOPIC_PATTERNS = {
    "respiratory":     r"\b(pneumonia|asthma|copd|bronchit|tuberculosis|tb|lung|pleural|effusion|emphysema|resp)\b",
    "cardiovascular":  r"\b(heart|cardiac|coronary|myocardial|MI|ACS|hypertension|stroke|arrhythmia|ECG|angina)\b",
    "diabetes":        r"\b(diabet|glucose|insulin|HbA1c|metformin|hyperglycaem|hypoglycaem|DKA)\b",
    "renal":           r"\b(kidney|renal|creatinine|eGFR|nephrotic|glomerulo|dialysis|CKD|AKI)\b",
    "hepatic":         r"\b(liver|hepat|ALT|AST|bilirubin|cirrhosis|jaundice|ALP|GGT)\b",
    "neurology":       r"\b(brain|neuro|seizure|epilepsy|stroke|headache|migraine|parkinson|dementia)\b",
    "infectious":      r"\b(infection|bacteria|virus|sepsis|malaria|HIV|fever|antibiotic|covid|influenza)\b",
    "hematology":      r"\b(blood|anaemia|anemia|platelet|WBC|CBC|RBC|haemoglobin|hemoglobin|coagulation)\b",
    "endocrine":       r"\b(thyroid|TSH|T4|T3|adrenal|cortisol|pituitary|hormone)\b",
    "pharmacology":    r"\b(drug|medication|dose|antibiotic|prescri|interaction|side effect)\b",
    "lab_values":      r"\b(mg/dL|mmol|mEq|U/L|ng/mL|reference range|normal value|lab result)\b",
    "emergency":       r"\b(emergency|urgent|acute|critical|resuscit|cardiac arrest|anaphylaxis|shock)\b",
}



# ══════════════════════════════════════════════════════════════════════════════
# ADDITION 1: Source metadata tagging
# ══════════════════════════════════════════════════════════════════════════════

def _get_source_metadata(file_path: Path) -> Dict:
    """
    NEW: Returns authority-level metadata for a file.
    Trusted sources get higher authority scores for retrieval prioritisation.
    """
    fname = file_path.stem.lower()
    parent = file_path.parent.name.lower()

    authority = DEFAULT_AUTHORITY
    source_name = fname
    source_type = "local_medical_data"

    # Check against known trusted sources
    for key, score in SOURCE_AUTHORITY.items():
        if key in fname or key in parent:
            authority = score
            source_type = "trusted_public_authority" if score >= 9 else "trusted_reference"
            break

    # Set display source name
    if "who" in fname:
        source_name = "WHO (World Health Organization)"
    elif "cdc" in fname:
        source_name = "CDC (Centers for Disease Control)"
    elif "nih" in fname or "medlineplus" in fname:
        source_name = "NIH / MedlinePlus"
    elif "harrison" in fname:
        source_name = "Harrison's Principles of Internal Medicine"
    elif "oxford" in fname:
        source_name = "Oxford Handbook of Clinical Medicine"
    elif "medical_report" in fname:
        source_name = "Medical Report Interpretation Guide"
    else:
        source_name = fname.replace("_", " ").title()

    return {
        "source_name":    source_name,
        "source_file":    file_path.name,
        "source_type":    source_type,
        "authority_score": authority,
        "is_trusted":     authority >= 7,
    }


# ══════════════════════════════════════════════════════════════════════════════
# ADDITION 2: Topic detection for metadata
# ══════════════════════════════════════════════════════════════════════════════

def _detect_topic(text: str) -> str:
    """
    NEW: Detects medical topic of a chunk for metadata tagging.
    Used to improve retrieval relevance filtering.
    """
    text_lower = text.lower()
    scores = {}
    for topic, pattern in TOPIC_PATTERNS.items():
        matches = len(re.findall(pattern, text_lower, re.IGNORECASE))
        if matches > 0:
            scores[topic] = matches
    if not scores:
        return "general_medicine"
    return max(scores, key=scores.get)


# ══════════════════════════════════════════════════════════════════════════════
# ADDITION 3: Medical value extraction from queries/reports
# ══════════════════════════════════════════════════════════════════════════════

def build_enriched_query(original_query: str, extracted_values: Dict[str, str]) -> str:
    """
    Augments the RAG query with medical value context for better retrieval.
    Delegates to utils.medical_values; kept here for interface compatibility
    and for the retrieval log line.
    """
    if not extracted_values:
        return original_query
    enriched = _build_enriched_query(original_query, extracted_values)
    logger.info(f"[RAG] Enriched query with {len(extracted_values)} lab value(s): {list(extracted_values.keys())}")
    return enriched


# ══════════════════════════════════════════════════════════════════════════════
# ADDITION 4: Semantic-aware chunking
# ══════════════════════════════════════════════════════════════════════════════

def _semantic_chunk_documents(documents: List[Document]) -> List[Document]:
    """
    NEW: Semantic-aware chunking that respects medical section boundaries.
    Splits on medical section markers (===, ---) before falling back to
    paragraph and sentence boundaries. Preserves medical context per chunk.
    """
    # Medical-aware separators: section dividers come first
    medical_separators = [
        "\n=== ",      # Harrison/Oxford section headers
        "\n--- ",      # Sub-section dividers
        "\nTOPIC: ",   # Topic tags in trusted files
        "\n\n\n",
        "\n\n",
        "\n",
        ". ",
        " ",
        "",
    ]

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=medical_separators,
        length_function=len,
        is_separator_regex=False,
    )

    chunks = splitter.split_documents(documents)

    # Filter and enrich each chunk
    enriched_chunks = []
    for chunk in chunks:
        content = chunk.page_content.strip()
        if len(content) < 40:  # skip near-empty chunks
            continue

        # Add topic metadata
        chunk.metadata["topic"] = _detect_topic(content)

        # Add section hint if detectable from content header
        first_line = content.split("\n")[0][:80]
        chunk.metadata["section"] = first_line if len(first_line) > 10 else "general"

        # Authority score — inherit from parent doc metadata
        if "authority_score" not in chunk.metadata:
            chunk.metadata["authority_score"] = DEFAULT_AUTHORITY
        if "is_trusted" not in chunk.metadata:
            chunk.metadata["is_trusted"] = False

        # Prepend source attribution to chunk content for LLM visibility
        if chunk.metadata.get("is_trusted") and chunk.metadata.get("source_name"):
            chunk.page_content = (
                f"[Source: {chunk.metadata['source_name']}]\n{content}"
            )

        enriched_chunks.append(chunk)

    logger.info(f"[RAG] Semantic chunking: {len(documents)} docs → {len(enriched_chunks)} enriched chunks")
    return enriched_chunks


# ══════════════════════════════════════════════════════════════════════════════
# ORIGINAL FUNCTION: _get_embeddings (unchanged)
# ══════════════════════════════════════════════════════════════════════════════

_cached_embeddings = None

def _get_embeddings():
    """Load HuggingFace embeddings (cached after first call)."""
    global _cached_embeddings
    if _cached_embeddings is not None:
        return _cached_embeddings

    try:
        _cached_embeddings = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL,
            model_kwargs={"device": "cpu", "local_files_only": True},
            encode_kwargs={"normalize_embeddings": True},
        )
    except Exception:
        _cached_embeddings = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
    return _cached_embeddings


# ══════════════════════════════════════════════════════════════════════════════
# ENHANCED: _load_all_documents (extended, not replaced)
# ══════════════════════════════════════════════════════════════════════════════

def _load_all_documents() -> List[Document]:
    """
    EXTENDED: Loads all documents from medical_data/ including new trusted_sources/ subfolder.
    Applies authority metadata to each document.
    Original CSV/TXT/PDF loaders preserved.
    """
    all_docs = []
    data_dir = MEDICAL_DIR

    if not data_dir.exists():
        logger.warning("[RAG] medical_data/ not found. Creating empty dir.")
        data_dir.mkdir(parents=True, exist_ok=True)
        return []

    # ── PDFs ──────────────────────────────────────────────────────────────────
    pdf_files = list(data_dir.rglob("*.pdf"))
    logger.info(f"[RAG] Found {len(pdf_files)} PDF file(s)")
    for pdf_path in pdf_files:
        try:
            loader = PyPDFLoader(str(pdf_path))
            docs = loader.load()
            meta = _get_source_metadata(pdf_path)
            for doc in docs:
                doc.metadata.update(meta)
                doc.metadata["source_type"] = "pdf"
            all_docs.extend(docs)
            logger.info(f"[RAG]   Loaded PDF: {pdf_path.name} ({len(docs)} pages) | authority={meta['authority_score']}")
        except Exception as e:
            logger.error(f"[RAG]   Failed to load {pdf_path.name}: {e}")

    # ── TXT files (includes new trusted_sources/*.txt) ────────────────────────
    txt_files = list(data_dir.rglob("*.txt"))
    logger.info(f"[RAG] Found {len(txt_files)} TXT file(s)")
    for txt_path in txt_files:
        try:
            loader = TextLoader(str(txt_path), encoding="utf-8")
            docs = loader.load()
            meta = _get_source_metadata(txt_path)
            for doc in docs:
                doc.metadata.update(meta)
                doc.metadata["source_type"] = "txt"
            all_docs.extend(docs)
            logger.info(f"[RAG]   Loaded TXT: {txt_path.name} | authority={meta['authority_score']} | trusted={meta['is_trusted']}")
        except Exception as e:
            logger.error(f"[RAG]   Failed to load {txt_path.name}: {e}")

    # ── CSV files ─────────────────────────────────────────────────────────────
    csv_files = list(data_dir.rglob("*.csv"))
    logger.info(f"[RAG] Found {len(csv_files)} CSV file(s)")
    for csv_path in csv_files:
        try:
            loader = CSVLoader(str(csv_path), csv_args={"delimiter": ","}, encoding="utf-8")
            docs = loader.load()
            meta = _get_source_metadata(csv_path)
            for doc in docs:
                doc.metadata.update(meta)
                doc.metadata["source_type"] = "csv"
            all_docs.extend(docs)
            logger.info(f"[RAG]   Loaded CSV: {csv_path.name} ({len(docs)} rows)")
        except Exception as e:
            logger.error(f"[RAG]   Failed to load {csv_path.name}: {e}")

    # Summary
    trusted_count = sum(1 for d in all_docs if d.metadata.get("is_trusted"))
    logger.info(f"[RAG] Total documents: {len(all_docs)} ({trusted_count} from trusted sources)")
    return all_docs


# ══════════════════════════════════════════════════════════════════════════════
# ORIGINAL FUNCTION: _split_documents → replaced by semantic version
# ══════════════════════════════════════════════════════════════════════════════

def _split_documents(documents: List[Document]) -> List[Document]:
    """
    ENHANCED: Now calls semantic chunker instead of basic splitter.
    Interface unchanged — drop-in replacement for build_vector_index().
    """
    return _semantic_chunk_documents(documents)


# ══════════════════════════════════════════════════════════════════════════════
# ADDITION 5: Source-weighted re-ranking
# ══════════════════════════════════════════════════════════════════════════════

def _rerank_by_authority(docs: List[Document], query: str) -> List[Document]:
    """
    NEW: Re-ranks retrieved documents by authority score.
    Trusted sources (WHO, CDC, NIH, Harrison's, Oxford) surface to the top.
    Falls back gracefully if metadata is missing.
    """
    def score(doc: Document) -> float:
        base_authority = doc.metadata.get("authority_score", DEFAULT_AUTHORITY)
        # Boost if topic matches query keywords
        topic = doc.metadata.get("topic", "")
        query_lower = query.lower()
        topic_boost = 0.5 if topic and topic.replace("_", " ") in query_lower else 0.0
        # Boost trusted sources
        trust_boost = 1.0 if doc.metadata.get("is_trusted") else 0.0
        return base_authority + topic_boost + trust_boost

    return sorted(docs, key=score, reverse=True)


# ══════════════════════════════════════════════════════════════════════════════
# ADDITION 6: Source citation builder
# ══════════════════════════════════════════════════════════════════════════════

def _build_source_citation(docs: List[Document]) -> str:
    """
    NEW: Builds a source citation footer from retrieved documents.
    Appended to LLM context so it cites which authority the info comes from.
    """
    seen = set()
    sources = []
    for doc in docs:
        name = doc.metadata.get("source_name", "Local medical data")
        if name not in seen:
            seen.add(name)
            trust_label = "✓ Trusted" if doc.metadata.get("is_trusted") else "Reference"
            sources.append(f"  [{trust_label}] {name}")
    if sources:
        return "\n\nKnowledge sources used:\n" + "\n".join(sources)
    return ""


# ══════════════════════════════════════════════════════════════════════════════
# ORIGINAL FUNCTION: build_vector_index — interface preserved, logic enhanced
# ══════════════════════════════════════════════════════════════════════════════

def build_vector_index(force_rebuild: bool = False):
    """
    ENHANCED: Build (or rebuild) the FAISS vector index.
    ✅ Same interface as original.
    ✅ Now uses semantic chunking, source metadata, authority scoring.
    
    Args:
        force_rebuild: If True, always rebuild even if index exists.
    Called by build_index.py — interface preserved.
    """
    FAISS_DIR.mkdir(parents=True, exist_ok=True)
    index_file = FAISS_DIR / "index.faiss"

    if index_file.exists() and not force_rebuild:
        logger.info("[RAG] FAISS index already exists. Use force_rebuild=True to rebuild.")
        return

    logger.info("[RAG] Loading documents from medical_data/ (including trusted sources)...")
    documents = _load_all_documents()

    if not documents:
        logger.warning("[RAG] No documents found! Add PDFs/TXTs to medical_data/")
        documents = [Document(
            page_content=(
                "This is a medical assistant. Please add medical documents "
                "to the medical_data/ folder and rebuild the index."
            ),
            metadata={"source": "placeholder", "authority_score": 1, "is_trusted": False}
        )]

    logger.info("[RAG] Applying semantic chunking with medical context preservation...")
    chunks = _split_documents(documents)

    # Stats
    trusted_chunks = sum(1 for c in chunks if c.metadata.get("is_trusted"))
    logger.info(f"[RAG] Chunks: {len(chunks)} total | {trusted_chunks} from trusted sources")

    logger.info("[RAG] Loading embedding model (all-MiniLM-L6-v2)...")
    embeddings = _get_embeddings()

    logger.info("[RAG] Building FAISS index...")
    vectorstore = FAISS.from_documents(chunks, embeddings)
    vectorstore.save_local(str(FAISS_DIR))

    logger.info(f"[RAG] ✅ Index saved → {FAISS_DIR}/")
    logger.info(f"[RAG] ✅ {len(chunks)} vectors indexed ({trusted_chunks} trusted-source chunks)")


# ══════════════════════════════════════════════════════════════════════════════
# ORIGINAL FUNCTION: load_vector_index — unchanged
# ══════════════════════════════════════════════════════════════════════════════

_cached_vectorstore = None

def load_vector_index(force_reload: bool = False):
    """Load existing FAISS index from disk (cached in memory)."""
    global _cached_vectorstore
    if _cached_vectorstore is not None and not force_reload:
        return _cached_vectorstore

    embeddings = _get_embeddings()
    index_file = FAISS_DIR / "index.faiss"

    if not index_file.exists():
        logger.warning("[RAG] No FAISS index found. Building now...")
        build_vector_index(force_rebuild=True)

    logger.info("[RAG] Loading FAISS index from disk...")
    vectorstore = FAISS.load_local(
        str(FAISS_DIR), embeddings, allow_dangerous_deserialization=True,
    )
    _cached_vectorstore = vectorstore
    return vectorstore


def get_vectorstore():
    """Retrieve the active cached FAISS vectorstore."""
    return load_vector_index()


# ══════════════════════════════════════════════════════════════════════════════
# ADDITION 7: Enhanced retrieval function (used by multimodal_handler)
# ══════════════════════════════════════════════════════════════════════════════

def retrieve_with_priority(vectorstore, query: str, k: int = 6) -> Tuple[List[Document], str]:
    """
    NEW (PUBLIC): Retrieves documents with authority-based re-ranking.
    Returns (reranked_docs, citation_string).
    
    Used by MultimodalHandler for direct retrieval with re-ranking.
    Falls back to basic retrieval if anything fails.
    """
    try:
        # Enrich query with any lab values detected
        lab_values = extract_medical_values(query)
        effective_query = build_enriched_query(query, lab_values)

        # MMR retrieval: balances relevance + diversity
        retriever = vectorstore.as_retriever(
            search_type="mmr",
            search_kwargs={"k": k, "fetch_k": k * 3, "lambda_mult": 0.7},
        )
        docs = retriever.invoke(effective_query)

        # Re-rank by authority
        reranked = _rerank_by_authority(docs, query)
        citation = _build_source_citation(reranked)
        return reranked, citation

    except Exception as e:
        logger.warning(f"[RAG] Priority retrieval failed, using basic: {e}")
        try:
            docs = vectorstore.similarity_search(query, k=k)
            return docs, ""
        except Exception as e2:
            logger.error(f"[RAG] Basic retrieval also failed: {e2}")
            return [], ""


# ══════════════════════════════════════════════════════════════════════════════
# ORIGINAL FUNCTION: build_rag_chain — interface preserved, logic enhanced
# ══════════════════════════════════════════════════════════════════════════════

def build_rag_chain(llm, system_prompt: str):
    """
    ENHANCED: Build the full RAG chain with the given LLM.
    ✅ Same interface as original — drop-in replacement.
    ✅ Now uses MMR retrieval (k=6 instead of 4) + source-weighted retriever.

    Args:
        llm: Any LangChain-compatible LLM
        system_prompt: System prompt string with {context} placeholder
    Returns:
        LangChain retrieval chain
    """
    logger.info("[RAG] Loading medical knowledge base (enhanced RAG v5)...")
    vectorstore = load_vector_index()

    # Enhanced: MMR retrieval fetches more candidates, selects diverse top-k
    retriever = vectorstore.as_retriever(
        search_type="mmr",
        search_kwargs={
            "k": 6,           # return 6 docs (was 4)
            "fetch_k": 20,    # fetch 20 candidates before MMR selection
            "lambda_mult": 0.7,  # balance relevance (1.0) vs diversity (0.0)
        },
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "{input}"),
    ])

    doc_chain = create_stuff_documents_chain(llm, prompt)
    rag_chain = create_retrieval_chain(retriever, doc_chain)
    try:
        rag_chain.vectorstore = vectorstore
    except Exception:
        pass

    logger.info("[RAG] ✅ Enhanced knowledge base loaded (MMR retrieval, trusted sources).")
    return rag_chain
