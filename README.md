# 🏥 MediBot v4 — AI Medical Assistant

Stable, production-ready multimodal medical chatbot using:
- **Flask** (web server)
- **LangChain + FAISS** (RAG knowledge base)
- **HuggingFace ViT** (X-ray analysis, CPU)
- **OpenRouter / Groq** (LLM with automatic fallback)

## 🚀 Quick Start

### 1. Set up environment
```bash
cd medibot_v4
cp .env.example .env
```
Edit `.env` and add your **OpenRouter API key** (free at https://openrouter.ai/keys):
```
OPENROUTER_API_KEY=sk-or-v1-your-key-here
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Build the knowledge index (first run only)
```bash
python build_index.py
```

### 4. Run the app
```bash
python run.py
```

Open your browser at: **http://localhost:5000**

---

## ✨ Features

| Mode | Description |
|------|-------------|
| 💬 Ask a Question | Medical Q&A via RAG + LLM |
| 🩻 X-Ray Analysis | Upload JPG/PNG → AI radiological analysis |
| 📄 Medical Report | Upload PDF/TXT → AI report interpretation |
| 🔬 Combined | X-ray + report + question together |

## 📋 Structured Output Format

All responses follow this structure:
```json
{
  "problem_summary": "...",
  "possible_conditions": ["...", "..."],
  "severity_level": "low | moderate | high",
  "recommendations": ["...", "..."],
  "when_to_seek_help": "..."
}
```

## 🔄 LLM Fallback Chain
1. **OpenRouter** (primary — uses your API key)
2. **Groq** (fallback — set GROQ_API_KEY in .env)
3. **Safe offline response** (never crashes)

## ⚠️ Disclaimer
MediBot is for informational purposes only. Always consult a qualified healthcare professional for diagnosis and treatment.
