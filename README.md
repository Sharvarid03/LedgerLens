# FinDoc AI — RAG-Based Due Diligence Copilot

A premium AI web app that analyzes company reports using RAG.

## Features
- Upload PDF reports
- Extract text from annual reports / investor PDFs
- Create chunks
- Generate embeddings using sentence-transformers/all-MiniLM-L6-v2
- Store and retrieve using FAISS
- Generate source-backed answers using Groq LLM
- Display retrieved evidence with page numbers
- Premium dark fintech dashboard

## Local setup

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Create `.env`:

```bash
GROQ_API_KEY=your_key_here
```

Run:

```bash
streamlit run app.py
```

## Good test questions
- Summarize the company in 5 bullet points.
- What are the main risk factors?
- What growth opportunities are mentioned?
- Give me an executive due diligence summary.
- Are there any red flags in the document?
