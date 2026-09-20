# Fixes — response flow, prompt routing, and UI typography

This round addresses three reported problems: **every input produced the same
output**, the **conversation/mode flow**, and the **fonts**.

---

## 1. Why every input gave the same output

There were four independent causes, stacked. The first one alone was enough to
make the bot answer identically forever.

### 1a. A missing API key killed the app at startup — silently

`flask_app/app.py` built everything inside one `try`:

```python
llm = get_llm()            # raises RuntimeError when no API key is set
rag_chain  = build_rag_chain(...)
multimodal = MultimodalHandler(...)   # never reached
```

`get_llm()` raises when neither `OPENROUTER_API_KEY` nor `GROQ_API_KEY` is
configured, so `multimodal` stayed `None`. Every `/analyze` request then took
the `else` branch into `_default_structured(query)` — a **hard-coded
paragraph**. The HTTP response still looked completely normal: status 200, no
`error` field, a plausible-looking medical answer. Nothing told you the model
had never been called.

**Fixed:** startup is now staged. The vector store loads independently of the
LLM, so the app runs in knowledge-base-only mode instead of dying, and
`/health` reports exactly which subsystem is down.

### 1b. The fallback answer was constant by construction

`_default_structured()` returned the same conditions, the same recommendations
and the same "when to seek help" text for every query — only a truncated echo
of the query varied.

**Fixed:** the offline path is now *extractive*. It scores the retrieved
knowledge-base sentences against the question and answers from the best
matches, so a pneumonia question and a diabetes question return different text
even with no API key at all. When there is no context either, it says plainly
that no AI response could be generated, rather than presenting a system message
as a medical assessment.

### 1c. The selected prompt was computed and then thrown away

In `multimodal_handler.py`:

```python
effective_prompt = LAB_VALUE_PROMPT      # or MEDICAL_REPORT_PROMPT ...
...
structured = call_llm_with_fallback(self.llm, llm_query, context=...)
#                                   ^ effective_prompt never passed
```

`call_llm_with_fallback()` had its own hard-coded prompt string. So
`MEDICAL_REPORT_PROMPT`, `LAB_VALUE_PROMPT` and `XRAY_CORRELATION_PROMPT` were
dead code — a lab report, an X-ray and a plain question were all sent the same
generic instructions and came back with the same shape of answer.

**Fixed:** `call_llm_with_fallback()` takes `system_prompt` and
`prompt_fields`, and each mode passes its own. The templates double their JSON
braces for LangChain, so `render_prompt()` fills the placeholders and undoubles
the braces before a direct call — otherwise the model is shown `{{` and copies
it into its reply.

### 1d. Every LLM failure was swallowed

Any exception — rate limit, timeout, unparsable JSON — was caught and turned
into the same canned response, with `error: None` in the payload.

**Fixed:**
- `_degraded` / `_error` travel from the LLM layer to the API to the UI. The
  reply carries a red notice, the header badge flips to `offline`/`limited`,
  and a banner pins the reason at the top of the window.
- JSON parsing is brace-balanced (survives prose after the object) and repairs
  code fences, `json` prefixes, smart quotes, trailing commas and
  truncated-at-max-tokens output, closing delimiters in correct nesting order.
- Responses are normalised: five required keys, lists coerced from strings or
  dicts, `severity_level` forced to `low`/`moderate`/`high`.
- The context handed to the model is capped at 6 000 characters — an
  over-long context makes free-tier models truncate their JSON mid-answer,
  which used to drop the request into the canned fallback.

---

## 2. Flow fixes

| Problem | Fix |
|---|---|
| The RAG fallback fed the chain's **own JSON answer** back in as "context" for a second LLM call, collapsing different questions into near-identical output | Uses the retrieved **documents** (`rag_response["context"]`) |
| Lab mode replaced the user's question with a fixed sentence ("Please interpret these values with reference ranges") | The user's actual question is kept and sent |
| A report containing lab values was routed to the lab prompt | Report prompt wins; detected values are passed to it |
| `my HbA1c is 8.2`, `glucose was around 145`, `creatinine level of 2.1` were never detected — the patterns only matched `label: value` | Connector words (`is`, `was`, `around`, `level of`, `came back at`, …) now match; blood pressure returns `150/95`; four more analytes added |
| The mode tabs were cosmetic — sending text from the "X-Ray Analysis" tab silently ran a plain text query | Each mode validates its required attachment before sending |
| Attachments were cleared even when the request failed | Cleared only after the request completes |
| Double-send while a request was in flight | Send button disables and shows a spinner |
| `/health` always reported `trusted_sources: true` | Reports the real state of the LLM, vector store and RAG chain |

---

## 3. Font & typography fixes

- **`font-family: 'Segoe UI', sans-serif`** only resolves on Windows. Everywhere
  else the browser fell back to its default sans, and — with no emoji family in
  the stack — the emoji section headings rendered as tofu boxes (□). Replaced
  with a full system stack ending in `"Apple Color Emoji", "Segoe UI Emoji",
  "Noto Color Emoji"`.
- Buttons, tabs and the textarea did not inherit the body font; they now do.
- Replies were one `white-space: pre-wrap` text blob. They are now rendered as
  real sections — summary paragraphs, bulleted conditions, a severity badge,
  numbered recommendations, a highlighted "when to seek help" box and source
  chips — built with `textContent`, so model output can never inject markup.
- **Mobile:** the four tabs overflowed a phone-width viewport and "Combined"
  was clipped off the edge (`.shell` hides overflow). They now wrap to a 2×2
  grid. The input placeholder no longer wraps and clips.
- Header/welcome card said **v4** while the backend reported v5.
- Added `.sev-normal` / `.sev-mild` badge styles — the X-ray model emits those
  two severities and they previously rendered unstyled.

---

## Setup

```bash
cp .env.example .env     # add OPENROUTER_API_KEY or GROQ_API_KEY
pip install -r requirements.txt
python build_index.py --force
python run.py
```

Check `http://localhost:5000/health` first. If `"llm": false`, the model is not
configured and answers will be knowledge-base excerpts only — the UI now says
so instead of quietly returning boilerplate.

## Tests

```bash
python tests/run_all.py
```

86 assertions covering JSON-parsing edge cases, schema normalisation, per-mode
prompt routing, lab-value detection, and the "different inputs must produce
different outputs" regression. They stub torch/faiss/langchain only when those
packages are absent, so the same suite runs in a full environment.
