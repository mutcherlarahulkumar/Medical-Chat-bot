"""
Request routing: each input type must reach its own prompt, with the retrieved
context attached. Previously every mode sent one hard-coded prompt, so a report,
a lab query and a plain question all produced the same shape of answer.
"""

import os
import sys
import types

from _bootstrap import Result, install_optional_stubs

install_optional_stubs()

os.environ.pop("OPENROUTER_API_KEY", None)
os.environ.pop("GROQ_API_KEY", None)

from utils.medical_values import extract_medical_values, build_enriched_query  # noqa: E402


class Doc:
    def __init__(self, text, meta=None):
        self.page_content = text
        self.metadata = meta or {}


# Stub the retrieval + vision layers: this suite is about routing, and those
# layers need faiss/torch. extract_medical_values is the real implementation.
CITATION = "\n\nKnowledge sources used:\n  [✓ Trusted] WHO\n  [✓ Trusted] NIH"
RETRIEVED = [Doc("Pneumonia causes fever and cough.", {"source_name": "WHO", "is_trusted": True}),
             Doc("HbA1c above 6.5% indicates diabetes.", {"source_name": "NIH", "is_trusted": True})]

rag_stub = types.ModuleType("rag.rag_engine")
rag_stub.retrieve_with_priority = lambda vs, q, k=6: (RETRIEVED, CITATION)
rag_stub.extract_medical_values = extract_medical_values
rag_stub.build_enriched_query = build_enriched_query
sys.modules["rag.rag_engine"] = rag_stub
sys.modules.setdefault("rag", types.ModuleType("rag")).rag_engine = rag_stub

xray_stub = types.ModuleType("image_model.xray_analyzer")
xray_stub.analyze_xray = lambda b: {
    "primary_finding": "PNEUMONIA", "confidence": 0.91,
    "interpretation": "Consolidation in the right lower lobe.",
    "severity": "high", "recommendations": ["See a physician."], "raw_probabilities": {}}
xray_stub.format_xray_for_rag = lambda res: f"X-ray finding: {res['primary_finding']}"
sys.modules["image_model.xray_analyzer"] = xray_stub
sys.modules.setdefault("image_model", types.ModuleType("image_model")).xray_analyzer = xray_stub

from multimodal_handler import MultimodalHandler, REPORT_MARKER  # noqa: E402

r = Result()


class SpyLLM:
    def __init__(self):
        self.prompts = []

    def invoke(self, messages):
        self.prompts.append(messages[0].content)

        class Response:
            content = ('{"problem_summary":"ok","possible_conditions":["A","B"],'
                       '"severity_level":"low","recommendations":["r1","r2","r3"],'
                       '"when_to_seek_help":"if worse"}')
        return Response()


print("\n[1] Each mode sends its own prompt")
llm = SpyLLM()
handler = MultimodalHandler(rag_chain=None, llm=llm, vectorstore=object())

text_result = handler.process(text_query="What causes pneumonia?")
r.check("text mode -> MEDICAL_RAG_PROMPT", "curated medical knowledge base" in llm.prompts[-1])
r.check("text mode label", text_result["mode"] == "text", text_result["mode"])

lab_result = handler.process(text_query="My HbA1c is 8.2, what does that mean?")
r.check("lab mode -> LAB_VALUE_PROMPT", "DETECTED LAB VALUES" in llm.prompts[-1])
r.check("detected value injected into prompt", "hba1c=8.2" in llm.prompts[-1])
r.check("user's own question preserved", "what does that mean" in llm.prompts[-1].lower())
r.check("lab values returned to caller", lab_result["lab_values"] == {"hba1c": "8.2"}, lab_result["lab_values"])
r.check("lab mode label", lab_result["mode"] == "lab_values", lab_result["mode"])

report_result = handler.process(
    text_query=f"{REPORT_MARKER}\nWBC 14.2 high\n\n[PATIENT QUESTION]\nWhat is wrong?")
r.check("report mode -> MEDICAL_REPORT_PROMPT", "INSTRUCTIONS FOR REPORT ANALYSIS" in llm.prompts[-1])
r.check("report wins over lab prompt when both apply", "DETECTED LAB VALUES" not in llm.prompts[-1])
r.check("values still handed to the report prompt", "wbc=14.2" in llm.prompts[-1])
r.check("report mode label", report_result["mode"] == "report", report_result["mode"])

image_result = handler.process(image_bytes=b"fake-image-bytes")
r.check("image mode -> XRAY_CORRELATION_PROMPT", "X-RAY FINDING" in llm.prompts[-1])
r.check("finding substituted", "X-RAY FINDING: PNEUMONIA" in llm.prompts[-1])
r.check("confidence substituted", "CONFIDENCE: 91.0%" in llm.prompts[-1])
r.check("no unfilled placeholders", "{xray_finding}" not in llm.prompts[-1] and "{context}" not in llm.prompts[-1])
r.check("no doubled braces sent to the model", "{{" not in llm.prompts[-1])
r.check("x-ray result returned", image_result["xray_analysis"]["primary_finding"] == "PNEUMONIA")

distinct = len(set(p[:400] for p in llm.prompts))
r.check("4 modes produced 4 distinct prompts", distinct == 4, f"-> {distinct}")

print("\n[2] Retrieved context reaches the model")
r.check("retrieved document text in prompt", "Pneumonia causes fever and cough." in llm.prompts[0])
r.check("citation in prompt", "Knowledge sources used" in llm.prompts[0])
r.check("rag_used reported", text_result["rag_used"] is True)
r.check("sources surfaced for the UI", "WHO" in text_result["structured"].get("_sources", ""))

print("\n[3] RAG-chain fallback passes documents, not the chain's own answer")


class FakeChain:
    def invoke(self, payload):
        return {"answer": '{"problem_summary":"CHAIN-JSON-ANSWER"}',
                "context": [Doc("CHAIN-RETRIEVED-DOCUMENT-TEXT")]}


chain_llm = SpyLLM()
chain_handler = MultimodalHandler(rag_chain=FakeChain(), llm=chain_llm, vectorstore=None)
chain_handler.process(text_query="what is asthma?")
r.check("chain documents used as context", "CHAIN-RETRIEVED-DOCUMENT-TEXT" in chain_llm.prompts[-1])
r.check("chain's JSON answer not fed back as context", "CHAIN-JSON-ANSWER" not in chain_llm.prompts[-1])

print("\n[4] Model unavailable: degraded flag propagates, answers still vary")
offline = MultimodalHandler(rag_chain=None, llm=None, vectorstore=object())
first = offline.process(text_query="What causes pneumonia?")
second = offline.process(text_query="How is diabetes diagnosed?")
r.check("degraded reported", first["degraded"] is True)
r.check("reason reported", bool(first["error"]))
r.check("still answers from the knowledge base", "pneumonia" in first["structured"]["problem_summary"].lower())
r.check("different question -> different answer",
        first["structured"]["problem_summary"] != second["structured"]["problem_summary"])

print("\n[5] Healthy path is not flagged degraded")
r.check("not degraded with a working model", text_result["degraded"] is False)
r.check("plain-text rendering still produced", "SUMMARY" in text_result["answer"])

print("\n[6] Empty input")
empty = handler.process()
r.check("empty input handled", empty["mode"] == "empty" and empty["error"] == "No input provided")

sys.exit(r.finish())
