"""
The reported bug: "whatever input I give, it gives the same output."

Root cause was in this layer — every LLM failure (and a missing API key was a
guaranteed failure) fell through to one hard-coded paragraph, with no signal to
the caller that no answer had been generated.
"""

import os
import sys
from _bootstrap import Result, install_optional_stubs

install_optional_stubs()

os.environ.pop("OPENROUTER_API_KEY", None)
os.environ.pop("GROQ_API_KEY", None)

from services.llm_service import (          # noqa: E402
    call_llm_with_fallback, parse_llm_response, normalize_structured,
    render_prompt, _key, try_get_llm,
)
from prompts.system_prompts import LAB_VALUE_PROMPT, MEDICAL_REPORT_PROMPT  # noqa: E402

r = Result()

print("\n[1] JSON shapes models actually return")
for name, raw in {
    "plain object":     '{"problem_summary":"a","severity_level":"low"}',
    "```json fence":    '```json\n{"problem_summary":"a","severity_level":"HIGH"}\n```',
    "prose after":      '{"problem_summary":"a"}\n\nHope that helps {smile}',
    "trailing commas":  '{"problem_summary":"a","recommendations":["x","y",],}',
    "smart quotes":     '{\u201cproblem_summary\u201d:\u201ca\u201d}',
    "truncated output": '{"problem_summary":"a","recommendations":["x"',
    "brace in string":  '{"problem_summary":"use {this} form"}',
    "preamble + fence": 'Here is the JSON:\n```\n{"problem_summary":"a"}\n```',
}.items():
    try:
        parse_llm_response(raw)
        r.check(name, True)
    except Exception as e:
        r.check(name, False, f"-> {e}")

try:
    parse_llm_response("I cannot help with that.")
    r.check("non-JSON reply is rejected", False, "should have raised")
except ValueError:
    r.check("non-JSON reply is rejected", True)

print("\n[2] Schema normalisation")
n = normalize_structured(
    {"problem_summary": "s", "severity_level": "Severity: HIGH",
     "possible_conditions": "One\nTwo", "recommendations": {"a": "do x", "b": "do y"}},
    "cough", "")
r.check("severity coerced to 'high'", n["severity_level"] == "high", n["severity_level"])
r.check("string coerced to list", n["possible_conditions"] == ["One", "Two"], n["possible_conditions"])
r.check("dict coerced to list", n["recommendations"] == ["do x", "do y"], n["recommendations"])
r.check("disclaimer appended", "\u26a0\ufe0f" in n["when_to_seek_help"])
r.check("real answer not flagged degraded", n["_degraded"] is False)

print("\n[3] Prompt rendering (the prompt used to be selected, then discarded)")
lab = render_prompt(LAB_VALUE_PROMPT, context="CTX-HERE", lab_values="glucose=210")
r.check("context substituted", "CTX-HERE" in lab)
r.check("lab values substituted", "glucose=210" in lab)
r.check("no doubled braces leak to the model", "{{" not in lab and "}}" not in lab)
r.check("no unfilled placeholders", "{context}" not in lab and "{lab_values}" not in lab)
r.check("report prompt differs from lab prompt", render_prompt(MEDICAL_REPORT_PROMPT, context="CTX") != lab)

print("\n[4] No API key: answers still differ per question")
ctx = (
    "Pneumonia is an infection that inflames the air sacs in the lungs. Typical symptoms include "
    "cough with phlegm, fever, chills and difficulty breathing.\n"
    "Type 2 diabetes mellitus is diagnosed when fasting plasma glucose is 126 mg/dL or higher. "
    "An HbA1c of 6.5 percent or above also establishes the diagnosis of diabetes per WHO criteria.\n"
    "Migraine is a recurrent headache disorder that is often unilateral and pulsating."
)
a = call_llm_with_fallback(None, "What are the symptoms of pneumonia?", context=ctx)
b = call_llm_with_fallback(None, "How is diabetes diagnosed with HbA1c?", context=ctx)
c = call_llm_with_fallback(None, "What is a migraine headache?", context=ctx)
r.check("pneumonia != diabetes answer", a["problem_summary"] != b["problem_summary"])
r.check("diabetes != migraine answer", b["problem_summary"] != c["problem_summary"])
r.check("pneumonia answer on topic", "pneumonia" in a["problem_summary"].lower())
r.check("diabetes answer on topic", "diabet" in b["problem_summary"].lower() or "glucose" in b["problem_summary"].lower())
r.check("migraine answer on topic", "migraine" in c["problem_summary"].lower() or "headache" in c["problem_summary"].lower())
r.check("flagged degraded", a["_degraded"] is True)
r.check("failure reason recorded", bool(a["_error"]))

print("\n[5] No model and no context: honest system message, not a fake assessment")
d = call_llm_with_fallback(None, "my chest hurts", context="")
r.check("states no AI response", "No AI response" in d["problem_summary"])
r.check("names the remedy", any("OPENROUTER_API_KEY" in rec for rec in d["recommendations"]))
r.check("flagged degraded", d["_degraded"] is True)

print("\n[6] A working model is used, and its answer is not overwritten")


class FakeLLM:
    def __init__(self):
        self.seen = None

    def invoke(self, messages):
        self.seen = messages[0].content

        class Response:
            content = ('```json\n{"problem_summary":"Model answer for this exact query",'
                       '"possible_conditions":["X"],"severity_level":"high",'
                       '"recommendations":["do a","do b","do c"],'
                       '"when_to_seek_help":"if worse"}\n```')
        return Response()


fake = FakeLLM()
res = call_llm_with_fallback(fake, "chest pain on exertion", context="CTXCTX",
                             system_prompt=LAB_VALUE_PROMPT,
                             prompt_fields={"lab_values": "troponin=0.9"})
r.check("model answer preserved", res["problem_summary"] == "Model answer for this exact query")
r.check("not flagged degraded", res["_degraded"] is False)
r.check("user query reached the model", "chest pain on exertion" in fake.seen)
r.check("selected prompt reached the model", "DETECTED LAB VALUES" in fake.seen)
r.check("lab values reached the model", "troponin=0.9" in fake.seen)
r.check("retrieved context reached the model", "CTXCTX" in fake.seen)

print("\n[7] API key handling")
os.environ["OPENROUTER_API_KEY"] = "your_key_here"
r.check("placeholder key treated as unset", _key("OPENROUTER_API_KEY") == "")
llm, err = try_get_llm()
r.check("try_get_llm reports instead of raising", llm is None and "No LLM configured" in err)
os.environ.pop("OPENROUTER_API_KEY")

sys.exit(r.finish())
