
import os
import re
import html
from datetime import datetime
from typing import List, Dict, Tuple

import faiss
import streamlit as st
from dotenv import load_dotenv
from groq import Groq
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer

load_dotenv()

st.set_page_config(
    page_title="LedgerLens | Business Due Diligence Platform",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# =========================
# APP STATE
# =========================
if "page" not in st.session_state:
    st.session_state.page = "home"
if "report_ready" not in st.session_state:
    st.session_state.report_ready = False

def go(page: str):
    st.session_state.page = page
    st.rerun()

def clear_report():
    for key in [
        "report_ready", "latest_question", "latest_answer", "latest_sources",
        "latest_doc_names", "latest_metrics", "share_summary"
    ]:
        if key in st.session_state:
            del st.session_state[key]
    st.session_state.report_ready = False

# =========================
# CSS
# =========================
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.stApp {
    background:
      radial-gradient(circle at 8% 5%, rgba(34,197,94,.18), transparent 26%),
      radial-gradient(circle at 90% 8%, rgba(59,130,246,.20), transparent 30%),
      radial-gradient(circle at 55% 55%, rgba(168,85,247,.12), transparent 30%),
      linear-gradient(135deg, #020617 0%, #07111f 46%, #0b1020 100%);
    color: #f8fafc;
}
.block-container { max-width: 1220px; padding-top: 1rem; padding-bottom: 4rem; }
[data-testid="stHeader"] { background: rgba(2,6,23,0); }
#MainMenu, footer { visibility: hidden; }

.navbar {
    position: sticky; top: 0; z-index: 999;
    margin-bottom: 1.2rem; padding: .72rem 1rem;
    border: 1px solid rgba(148,163,184,.18); border-radius: 999px;
    background: rgba(2,6,23,.72); backdrop-filter: blur(18px);
    display: flex; align-items: center; justify-content: space-between;
    box-shadow: 0 18px 50px rgba(0,0,0,.24);
}
.nav-brand { font-weight: 950; letter-spacing: -.04em; font-size: 1.08rem; color: white; }
.nav-mini { color: #94a3b8; font-size: .84rem; font-weight: 700; }

.hero {
    min-height: 64vh; display: grid; grid-template-columns: .98fr 1.02fr;
    gap: 2.4rem; align-items: center; padding: 2rem 0 2.4rem;
}
.eyebrow {
    display: inline-flex; padding: .44rem .76rem; border-radius: 999px;
    background: rgba(34,197,94,.12); border: 1px solid rgba(74,222,128,.35);
    color: #bbf7d0; font-size: .74rem; font-weight: 950; letter-spacing: .06em;
    text-transform: uppercase; animation: fadeUp .8s ease both;
}
.logo-pop {
    margin-top: 1rem; font-size: clamp(3rem, 6vw, 5.4rem); line-height: .92;
    font-weight: 950; letter-spacing: -.09em; color: white; animation: logoPop 1.2s ease both;
}
.hero-title {
    margin-top: .55rem; max-width: 690px; font-size: clamp(1.85rem, 3.2vw, 3.25rem);
    line-height: 1.05; font-weight: 900; letter-spacing: -.06em; color: white; animation: fadeUp 1s ease both;
}
.gradient-text {
    background: linear-gradient(135deg, #4ade80, #5eead4, #60a5fa, #c084fc);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}
.hero-subtitle {
    margin-top: 1.05rem; max-width: 680px; color: #cbd5e1; font-size: 1rem;
    line-height: 1.72; animation: fadeUp 1.1s ease both;
}
.hero-visual { position: relative; min-height: 380px; animation: fadeIn 1.3s ease both; }
.blob {
    position: absolute; right: 40px; top: 30px; width: 310px; height: 310px;
    border-radius: 38% 62% 64% 36% / 40% 45% 55% 60%;
    background:
      radial-gradient(circle at 30% 25%, #4ade80, transparent 20%),
      radial-gradient(circle at 55% 45%, #2563eb, transparent 38%),
      radial-gradient(circle at 70% 55%, #a855f7, transparent 38%),
      linear-gradient(135deg, rgba(34,197,94,.68), rgba(37,99,235,.54), rgba(168,85,247,.58));
    opacity: .65; animation: morph 9s ease-in-out infinite;
}
.float-card {
    position: absolute; border-radius: 24px; padding: 1.1rem;
    background: linear-gradient(135deg, rgba(15,23,42,.92), rgba(30,41,59,.66));
    border: 1px solid rgba(148,163,184,.23); box-shadow: 0 24px 80px rgba(0,0,0,.36);
    backdrop-filter: blur(20px);
}
.terminal { width: 88%; right: 0; top: 10%; min-height: 220px; }
.term-line { color: #cbd5e1; font-family: ui-monospace, Consolas, monospace; font-size: .82rem; padding: .30rem 0; }
.dot { width: 10px; height: 10px; border-radius: 999px; display: inline-block; margin-right: .32rem; }
.r { background: #fb7185; } .y { background: #fbbf24; } .g { background: #34d399; }
.mini-left { width: 46%; left: 0; bottom: 12%; animation: floaty 5s ease-in-out infinite; }
.mini-right { width: 39%; right: 5%; bottom: 0; animation: floaty 6s ease-in-out infinite reverse; }
.big { font-size: 2.1rem; font-weight: 950; letter-spacing: -.06em; color: white; }
.tiny { color: #94a3b8; font-size: .72rem; font-weight: 850; text-transform: uppercase; letter-spacing: .06em; }

.section { padding: 2.35rem 0 1rem; }
.section-title { font-size: clamp(1.8rem, 3.2vw, 2.65rem); line-height: 1.08; font-weight: 950; letter-spacing: -.06em; color: white; margin-bottom: .65rem; }
.section-sub { color: #cbd5e1; font-size: .98rem; line-height: 1.72; max-width: 900px; margin-bottom: 1.25rem; }

.grid3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: .9rem; }
.grid4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: .9rem; }
.card, .panel, .report-card, .share-box, .pricing, .security-box, .contact-card {
    border-radius: 24px; background: rgba(15,23,42,.68);
    border: 1px solid rgba(148,163,184,.18); box-shadow: 0 16px 54px rgba(0,0,0,.23);
}
.card { padding: 1.15rem; min-height: 145px; transition: .25s ease; }
.card:hover { transform: translateY(-5px); border-color: rgba(74,222,128,.42); }
.panel { padding: 1.2rem; }
.card-title, .panel-title { font-weight: 950; color: white; font-size: 1.02rem; margin-bottom: .38rem; }
.card-text, .panel-caption { color: #94a3b8; font-size: .88rem; line-height: 1.58; }
.icon { font-size: 1.42rem; margin-bottom: .65rem; }

.shell {
    border-radius: 30px; background: rgba(15,23,42,.66);
    border: 1px solid rgba(148,163,184,.20); box-shadow: 0 26px 90px rgba(0,0,0,.36);
    padding: 1.1rem; backdrop-filter: blur(22px);
}
.metric {
    padding: 1rem; border-radius: 20px;
    background: linear-gradient(135deg, rgba(30,41,59,.78), rgba(15,23,42,.76));
    border: 1px solid rgba(148,163,184,.18);
}
.metric-label { color: #94a3b8; font-size: .72rem; font-weight: 850; letter-spacing: .05em; text-transform: uppercase; }
.metric-value { color: white; font-size: 1.36rem; font-weight: 950; margin-top: .2rem; letter-spacing: -.04em; }

.privacy-note {
    padding: .95rem; border-radius: 17px; background: rgba(251,191,36,.08);
    border: 1px solid rgba(251,191,36,.25); color: #fde68a; font-size: .86rem; line-height: 1.55;
}
.key-warning {
    padding: 1rem; border-radius: 18px; background: rgba(251,113,133,.10);
    border: 1px solid rgba(251,113,133,.30); color: #fecdd3; line-height: 1.55; margin-top: 1rem;
}
.pro-lock {
    padding: 1.15rem; border-radius: 22px;
    background: linear-gradient(135deg, rgba(168,85,247,.18), rgba(37,99,235,.12));
    border: 1px solid rgba(196,181,253,.32); color: #ede9fe; line-height: 1.6;
}
.report-card { padding: 1.5rem; background: rgba(2,6,23,.62); border-color: rgba(74,222,128,.24); }
.report-title { font-size: 1.55rem; font-weight: 950; color: white; letter-spacing: -.04em; margin-bottom: .4rem; }
.summary-bullet {
    padding: .9rem; margin-bottom: .65rem; border-radius: 16px;
    background: rgba(15,23,42,.72); border: 1px solid rgba(148,163,184,.16);
    color: #dbeafe; line-height: 1.5;
}
.full-report {
    padding: 1.2rem 1.3rem; border-radius: 20px;
    background: rgba(15,23,42,.74); border: 1px solid rgba(148,163,184,.18);
    color: #e5e7eb; line-height: 1.65;
}
.source {
    padding: 1rem 1.05rem; border-radius: 18px; background: rgba(2,6,23,.64);
    border: 1px solid rgba(148,163,184,.16); margin-top: .75rem; color: #cbd5e1; line-height: 1.55;
}
.badge {
    display: inline-block; padding: .28rem .6rem; border-radius: 999px;
    background: rgba(34,197,94,.14); border: 1px solid rgba(74,222,128,.26);
    color: #bbf7d0; font-weight: 850; font-size: .76rem; margin-bottom: .5rem;
}
.workflow { display: grid; grid-template-columns: repeat(5, 1fr); gap: .75rem; }
.step { padding: 1rem; border-radius: 22px; background: rgba(2,6,23,.5); border: 1px solid rgba(148,163,184,.18); }
.num { width: 31px; height: 31px; border-radius: 999px; display: grid; place-items: center; background: linear-gradient(135deg,#22c55e,#2563eb); font-weight: 950; margin-bottom: .7rem; }

.price-name { font-size: 1.16rem; font-weight: 950; color: white; }
.price { font-size: 1.95rem; font-weight: 950; letter-spacing: -.06em; margin: .7rem 0; color: white; }
.price span { font-size: .86rem; color: #94a3b8; letter-spacing: 0; }
.check { color: #cbd5e1; margin: .5rem 0; font-size: .9rem; }
.pricing { padding: 1.25rem; min-height: 300px; }
.popular { border-color: rgba(74,222,128,.5); box-shadow: 0 28px 90px rgba(34,197,94,.12); }

.contact-card, .security-box { padding: 1.35rem; }
.contact-btn {
    display: inline-block; margin-top: .9rem; text-decoration: none; padding: .8rem 1rem;
    border-radius: 999px; color: white; font-weight: 950; background: linear-gradient(135deg,#22c55e,#2563eb);
}
.share-box { padding: 1.2rem; }
.footer { text-align: center; padding: 2rem 0 .5rem; color: #94a3b8; font-size: .84rem; }

/* Removes accidental empty Streamlit spacer bars */
div[data-testid="stMarkdownContainer"]:empty {
    display: none !important;
}
.element-container:has(div[data-testid="stMarkdownContainer"]:empty) {
    display: none !important;
}

.review-card {
    padding: 1.15rem;
    border-radius: 22px;
    background: rgba(15,23,42,.70);
    border: 1px solid rgba(148,163,184,.18);
    box-shadow: 0 16px 54px rgba(0,0,0,.23);
}
.review-name {
    color: white;
    font-weight: 950;
    margin-top: .75rem;
}
.review-role {
    color: #94a3b8;
    font-size: .82rem;
}
.query-form {
    margin-top: 1rem;
    padding: 1.2rem;
    border-radius: 24px;
    background: rgba(2,6,23,.58);
    border: 1px solid rgba(74,222,128,.22);
}
.query-form input, .query-form textarea {
    width: 100%;
    margin: .45rem 0;
    padding: .85rem;
    border-radius: 14px;
    border: 1px solid rgba(148,163,184,.25);
    background: rgba(15,23,42,.88);
    color: white;
    font-family: Inter, sans-serif;
}
.query-form button {
    margin-top: .6rem;
    padding: .85rem 1rem;
    border-radius: 999px;
    border: 0;
    background: linear-gradient(135deg,#22c55e,#2563eb);
    color: white;
    font-weight: 950;
    cursor: pointer;
}

.stButton > button {
    width: 100%; border-radius: 15px; border: 0;
    background: linear-gradient(135deg,#22c55e,#2563eb)!important;
    color: white!important; font-weight: 950; padding: .78rem .9rem;
}
.stDownloadButton > button {
    width: 100%; border-radius: 15px; border: 0;
    background: linear-gradient(135deg,#1d4ed8,#7c3aed)!important;
    color: white!important; font-weight: 950; padding: .78rem .9rem;
}
.stTextInput > div > div > input, .stTextArea textarea {
    border-radius: 15px; background: rgba(2,6,23,.74); color: white;
    border: 1px solid rgba(148,163,184,.24);
}
div[data-testid="stFileUploader"] {
    border: 1px dashed rgba(74,222,128,.55); border-radius: 20px; padding: .9rem; background: rgba(2,6,23,.34);
}

@keyframes logoPop {
    0% { opacity: 0; transform: translateY(20px) scale(.94); filter: blur(10px); }
    65% { opacity: 1; transform: translateY(0) scale(1.02); filter: blur(0); text-shadow: 0 0 38px rgba(74,222,128,.26); }
    100% { opacity: 1; transform: scale(1); text-shadow: 0 0 26px rgba(59,130,246,.16); }
}
@keyframes fadeUp { from { opacity: 0; transform: translateY(16px); } to { opacity: 1; transform: translateY(0); } }
@keyframes fadeIn { from { opacity: 0; transform: scale(.98); } to { opacity: 1; transform: scale(1); } }
@keyframes floaty { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-12px); } }
@keyframes morph {
    0%,100% { border-radius: 38% 62% 64% 36% / 40% 45% 55% 60%; transform: rotate(0deg); }
    50% { border-radius: 65% 35% 42% 58% / 55% 35% 65% 45%; transform: rotate(8deg); }
}
@media(max-width:1050px) {
    .hero { grid-template-columns: 1fr; min-height: auto; }
    .hero-visual { min-height: 390px; }
    .grid4,.grid3,.workflow { grid-template-columns: repeat(2,1fr); }
}
@media(max-width:680px) {
    .grid4,.grid3,.workflow { grid-template-columns: 1fr; }
    .hero-visual { display: none; }
}
</style>
""",
    unsafe_allow_html=True,
)

# =========================
# RAG FUNCTIONS
# =========================
@st.cache_resource(show_spinner=False)
def load_embedding_model():
    return SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

def get_api_key() -> str:
    return os.getenv("GROQ_API_KEY", "").strip()

def extract_pdf_chunks(uploaded_file, chunk_size: int = 950, overlap: int = 160) -> Tuple[str, int, List[Dict]]:
    reader = PdfReader(uploaded_file)
    doc_name = uploaded_file.name
    chunks: List[Dict] = []
    full_text_parts: List[str] = []

    for page_idx, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""
        page_text = re.sub(r"\s+", " ", page_text).strip()
        full_text_parts.append(page_text)

        start = 0
        while start < len(page_text):
            end = start + chunk_size
            chunk = page_text[start:end].strip()

            if len(chunk) > 90:
                chunks.append({"doc": doc_name, "page": page_idx, "text": chunk})

            if end >= len(page_text):
                break
            start = max(0, end - overlap)

    return "\n".join(full_text_parts), len(reader.pages), chunks

def build_faiss_index(chunks: List[Dict]):
    model = load_embedding_model()
    texts = [c["text"] for c in chunks]
    embeddings = model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
    index = faiss.IndexFlatIP(embeddings.shape[1])
    index.add(embeddings.astype("float32"))
    return index

def retrieve_relevant_chunks(question: str, chunks: List[Dict], index, top_k: int = 7) -> List[Dict]:
    model = load_embedding_model()
    q_embedding = model.encode([question], convert_to_numpy=True, normalize_embeddings=True).astype("float32")
    scores, indices = index.search(q_embedding, top_k)

    results = []
    for score, idx in zip(scores[0], indices[0]):
        if 0 <= idx < len(chunks):
            item = chunks[idx].copy()
            item["score"] = float(score)
            results.append(item)
    return results

def call_groq(prompt: str) -> str:
    api_key = get_api_key()
    if not api_key:
        return (
            "Groq API key is missing. Add this line in your .env file:\n\n"
            "GROQ_API_KEY=gsk_your_actual_key_here\n\n"
            "Then save .env, stop Streamlit with Ctrl+C, and run streamlit run app.py again."
        )

    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are LedgerLens, a professional business due diligence analyst. "
                    "Write like a human analyst preparing an internal business review. "
                    "Do not use chatbot language. Do not say 'as an AI'. "
                    "Use only retrieved evidence. Cite document names and page numbers."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.12,
    )
    return response.choices[0].message.content

def ask_groq(question: str, context_chunks: List[Dict], mode: str = "standard") -> str:
    context = "\n\n".join(
        [
            f"Source {i + 1} | Document: {chunk['doc']} | Page {chunk['page']}:\n{chunk['text']}"
            for i, chunk in enumerate(context_chunks)
        ]
    )

    report_structure = """
Prepare the output as a formal internal business report. The report must look like it was prepared by a business analyst, not like a chatbot answer.

Use this exact structure:

1. Review Snapshot
Documents Reviewed:
Report Type:
Risk Level:
Key Business Theme:
Evidence Count:

2. Executive Summary
Write one short professional paragraph of 5 to 7 lines. Avoid generic filler.

3. Key Findings
Use short hyphen bullets. Each point must be supported by retrieved evidence.

4. Risk and Red Flag Review
For each risk, write:
Risk Area:
Why It Matters:
Possible Business Impact:
Source:

5. Financial and Operational Signals
Mention revenue, cost, cash flow, operating model, strategy, or market indicators only if present in the retrieved evidence.

6. Growth Opportunities
Mention opportunity themes only if supported by the retrieved evidence.

7. Recommended Follow-Up Questions
Write practical questions that company employees, analysts, auditors, or managers can ask next.

8. Source Evidence Summary
Use short source lines in this format:
Document name - Page number - Evidence summary - Relevance

9. Final Analyst Note
Give a short final conclusion.

Strict writing rules:
- Plain text only.
- Do not use Markdown tables.
- Do not use pipe symbols.
- Do not use asterisks, emojis, or decorative bullets.
- Use normal hyphen bullets only.
- Do not write 'as an AI model'.
- Do not write 'based on the provided context'.
- Do not invent missing information.
- If information is missing, write 'Not identified in the retrieved document evidence.'
- Keep the tone professional, concise, workplace-ready, and useful for company employees.
"""

    if mode == "risk":
        report_structure += "\nFocus more deeply on risks, red flags, severity, and business impact."
    elif mode == "growth":
        report_structure += "\nFocus more deeply on growth opportunities, expansion signals, and execution risks."
    elif mode == "compare":
        report_structure += "\nCompare the uploaded documents and clearly separate document-wise observations."

    prompt = f"""
User due diligence request:
{question}

Retrieved source evidence:
{context}

{report_structure}
"""
    return call_groq(prompt)

def estimate_risk_signal(text: str) -> Tuple[str, int]:
    risk_words = [
        "risk", "uncertainty", "litigation", "debt", "loss", "decline",
        "impairment", "regulatory", "competition", "inflation", "liability",
        "default", "fraud", "material weakness", "adverse", "volatility",
    ]
    count = sum(text.lower().count(word) for word in risk_words)
    if count > 110:
        return "High", min(95, 70 + count // 12)
    if count > 45:
        return "Medium", min(75, 45 + count // 10)
    return "Low", min(45, 20 + count // 5)

def generate_summary_points(answer: str) -> List[str]:
    cleaned = re.sub(r"\*\*", "", answer)
    lines = [line.strip(" -•\t") for line in cleaned.splitlines() if line.strip()]
    points = []
    skip_prefixes = (
        "a.", "b.", "c.", "d.", "e.", "f.", "g.", "h.", "i.",
        "review snapshot", "executive summary", "key findings",
        "risk", "source evidence", "final analyst"
    )

    for line in lines:
        if len(line) < 45:
            continue
        if line.lower().startswith(skip_prefixes):
            continue
        points.append(line)
        if len(points) == 6:
            break

    if not points:
        points = [
            "The report has been generated using retrieved document evidence.",
            "Open the full analysis section to review the complete due diligence report.",
        ]
    return points[:6]

def build_txt_report(question: str, answer: str, sources: List[Dict], doc_names: List[str]) -> str:
    source_text = "\n\n".join(
        [
            f"Source {i} | Document: {source['doc']} | Page {source['page']} | Similarity {source['score']:.2f}\n{source['text'][:1200]}"
            for i, source in enumerate(sources, start=1)
        ]
    )
    docs = "\n".join("- " + name for name in doc_names)
    return f"""LedgerLens Business Due Diligence Report
Generated on: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

Documents Reviewed:
{docs}

Review Request:
{question}

Professional Analysis:
{answer}

Retrieved Source Evidence:
{source_text}

Report Note:
This report is generated by LedgerLens for decision-support and internal business review purposes.
It is not financial advice. For confidential company documents, use private deployment with controlled
access, encrypted storage, audit logs, and a private model endpoint.
"""

def make_pdf_bytes(title: str, body: str) -> bytes:
    """
    Creates a professional business-style PDF report.
    Uses ReportLab when installed. If ReportLab is unavailable, falls back to a basic text PDF
    so the app does not crash.
    """
    cleaned_body = body.replace("**", "")
    cleaned_body = cleaned_body.replace("?", "-")
    cleaned_body = cleaned_body.replace("|", " - ")

    # Remove duplicated title/date from body because the PDF template already adds them.
    cleaned_body = re.sub(r"^LedgerLens Business Due Diligence Report\s*", "", cleaned_body, flags=re.IGNORECASE)
    cleaned_body = re.sub(r"^Generated on:.*?\n", "", cleaned_body, flags=re.IGNORECASE)

    try:
        from io import BytesIO
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import (
            SimpleDocTemplate,
            Paragraph,
            Spacer,
            Table,
            TableStyle,
            PageBreak,
        )

        buffer = BytesIO()

        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=42,
            leftMargin=42,
            topMargin=72,
            bottomMargin=58,
            title=title,
            author="LedgerLens",
        )

        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            "LedgerTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#111827"),
            spaceAfter=8,
        )

        subtitle_style = ParagraphStyle(
            "LedgerSubtitle",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#4B5563"),
            spaceAfter=18,
        )

        heading_style = ParagraphStyle(
            "LedgerHeading",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12.5,
            leading=15,
            textColor=colors.HexColor("#0F172A"),
            spaceBefore=12,
            spaceAfter=6,
            keepWithNext=True,
        )

        normal_style = ParagraphStyle(
            "LedgerNormal",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=13.5,
            alignment=TA_LEFT,
            textColor=colors.HexColor("#111827"),
            spaceAfter=6,
        )

        bullet_style = ParagraphStyle(
            "LedgerBullet",
            parent=normal_style,
            leftIndent=14,
            firstLineIndent=-8,
            spaceAfter=5,
        )

        small_style = ParagraphStyle(
            "LedgerSmall",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#4B5563"),
        )

        def safe_para(text: str, style):
            text = html.escape(text)
            return Paragraph(text, style)

        story = []

        story.append(safe_para("LedgerLens Business Due Diligence Report", title_style))
        story.append(
            safe_para(
                f"Generated on {datetime.now().strftime('%d %B %Y, %I:%M %p')} | Prepared for internal business review",
                subtitle_style,
            )
        )

        docs_match = re.search(r"Documents Reviewed:\s*(.*?)(?:\n\n|Review Request:)", cleaned_body, flags=re.S)
        request_match = re.search(r"Review Request:\s*(.*?)(?:\n\n|Professional Analysis:)", cleaned_body, flags=re.S)

        docs_text = docs_match.group(1).strip().replace("\n", "<br/>") if docs_match else "Uploaded business document(s)"
        request_text = request_match.group(1).strip() if request_match else "Business due diligence review"

        metadata_rows = [
            [safe_para("Documents Reviewed", small_style), safe_para(docs_text, small_style)],
            [safe_para("Review Request", small_style), safe_para(request_text, small_style)],
            [safe_para("Report Type", small_style), safe_para("Business Due Diligence Review", small_style)],
            [safe_para("Prepared By", small_style), safe_para("LedgerLens", small_style)],
        ]

        meta_table = Table(metadata_rows, colWidths=[1.55 * inch, 4.75 * inch])
        meta_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                    ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#CBD5E1")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E5E7EB")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )

        story.append(meta_table)
        story.append(Spacer(1, 14))

        if "Professional Analysis:" in cleaned_body:
            main_body = cleaned_body.split("Professional Analysis:", 1)[1].strip()
        else:
            main_body = cleaned_body.strip()

        source_body = ""
        if "Retrieved Source Evidence:" in main_body:
            main_body, source_body = main_body.split("Retrieved Source Evidence:", 1)
            main_body = main_body.strip()
            source_body = source_body.strip()

        def is_heading(line: str) -> bool:
            line = line.strip()
            return bool(
                re.match(r"^\d+\.\s+[A-Z]", line)
                or re.match(r"^[A-I]\.\s+[A-Z]", line)
                or line in [
                    "Review Snapshot",
                    "Executive Summary",
                    "Key Findings",
                    "Risk and Red Flag Review",
                    "Financial and Operational Signals",
                    "Growth Opportunities",
                    "Recommended Follow-Up Questions",
                    "Source Evidence Summary",
                    "Final Analyst Note",
                ]
            )

        for raw_line in main_body.splitlines():
            line = raw_line.strip()
            if not line:
                story.append(Spacer(1, 4))
                continue

            line = line.replace("•", "-").replace("?", "-").replace("—", "-")

            if is_heading(line):
                story.append(safe_para(line, heading_style))
            elif line.startswith("-"):
                story.append(safe_para(line, bullet_style))
            else:
                story.append(safe_para(line, normal_style))

        if source_body:
            story.append(PageBreak())
            story.append(safe_para("Appendix: Retrieved Source Evidence", heading_style))
            story.append(
                safe_para(
                    "The following excerpts were retrieved by the semantic search layer and used as supporting evidence for the report.",
                    normal_style,
                )
            )

            source_blocks = re.split(r"\n(?=Source\s+\d+\s+\|)", source_body)
            for block in source_blocks[:8]:
                block = block.strip()
                if not block:
                    continue
                block = block.replace("?", "-").replace("|", " - ")
                story.append(safe_para(block[:1400], small_style))
                story.append(Spacer(1, 8))

        story.append(Spacer(1, 12))
        story.append(
            safe_para(
                "Report Note: This report is generated by LedgerLens for decision-support and internal business review purposes. It is not financial advice. Confidential documents should be processed only in a private deployment with controlled access, encrypted storage, audit logs, and a private model endpoint.",
                small_style,
            )
        )

        def draw_page_frame(canvas, doc_obj):
            canvas.saveState()
            width, height = A4

            canvas.setStrokeColor(colors.HexColor("#1E293B"))
            canvas.setLineWidth(0.7)
            canvas.rect(28, 28, width - 56, height - 56)

            canvas.setFont("Helvetica-Bold", 9)
            canvas.setFillColor(colors.HexColor("#0F172A"))
            canvas.drawString(42, height - 38, "LedgerLens")

            canvas.setFont("Helvetica", 8)
            canvas.setFillColor(colors.HexColor("#64748B"))
            canvas.drawRightString(width - 42, height - 38, "Business Due Diligence Report")

            canvas.setStrokeColor(colors.HexColor("#CBD5E1"))
            canvas.setLineWidth(0.3)
            canvas.line(42, 43, width - 42, 43)

            canvas.setFont("Helvetica", 8)
            canvas.setFillColor(colors.HexColor("#64748B"))
            canvas.drawString(42, 31, "Confidential review format - demo report")
            canvas.drawRightString(width - 42, 31, f"Page {doc_obj.page}")

            canvas.restoreState()

        doc.build(story, onFirstPage=draw_page_frame, onLaterPages=draw_page_frame)
        buffer.seek(0)
        return buffer.getvalue()

    except Exception:
        def esc(s: str) -> str:
            return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

        fallback_text = f"{title}\nGenerated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n{cleaned_body}"
        raw_lines = []

        for paragraph in fallback_text.splitlines():
            paragraph = paragraph.strip()
            if not paragraph:
                raw_lines.append("")
                continue
            while len(paragraph) > 88:
                raw_lines.append(paragraph[:88])
                paragraph = paragraph[88:]
            raw_lines.append(paragraph)

        pages = [raw_lines[i:i + 42] for i in range(0, len(raw_lines), 42)] or [["LedgerLens Report"]]
        objects = []
        pages_kids = []
        objects.append("1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")
        objects.append("")
        obj_id = 3

        for page_lines in pages:
            content_id = obj_id
            obj_id += 1
            page_id = obj_id
            obj_id += 1

            stream_lines = ["BT", "/F1 10 Tf", "50 760 Td"]
            first = True
            for line in page_lines:
                if first:
                    stream_lines.append(f"({esc(line)}) Tj")
                    first = False
                else:
                    stream_lines.append("0 -16 Td")
                    stream_lines.append(f"({esc(line)}) Tj")
            stream_lines.append("ET")
            stream = "\n".join(stream_lines)

            objects.append(
                f"{content_id} 0 obj\n<< /Length {len(stream.encode('latin-1', 'replace'))} >>\nstream\n{stream}\nendstream\nendobj\n"
            )
            objects.append(
                f"{page_id} 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >> "
                f"/Contents {content_id} 0 R >>\nendobj\n"
            )
            pages_kids.append(f"{page_id} 0 R")

        objects[1] = f"2 0 obj\n<< /Type /Pages /Kids [{' '.join(pages_kids)}] /Count {len(pages_kids)} >>\nendobj\n"

        pdf = "%PDF-1.4\n"
        offsets = [0]
        for obj in objects:
            offsets.append(len(pdf.encode("latin-1", "replace")))
            pdf += obj

        xref_start = len(pdf.encode("latin-1", "replace"))
        pdf += f"xref\n0 {len(objects) + 1}\n"
        pdf += "0000000000 65535 f \n"
        for offset in offsets[1:]:
            pdf += f"{offset:010d} 00000 n \n"
        pdf += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF"
        return pdf.encode("latin-1", "replace")


def reset_report():
    for key in [
        "report_ready", "latest_question", "latest_answer",
        "latest_sources", "latest_doc_names", "latest_metrics", "share_summary"
    ]:
        if key in st.session_state:
            del st.session_state[key]
    st.session_state.report_ready = False

# =========================
# UI HELPERS
# =========================
def render_nav():
    st.markdown(
        """
<div class="navbar">
    <div class="nav-brand">💼 LedgerLens</div>
    <div class="nav-mini">RAG-powered due diligence workspace</div>
</div>
""",
        unsafe_allow_html=True,
    )

def render_footer():
    st.markdown(
        """
<section class="section">
<div class="section-title">What early users say.</div>


<div class="grid3">
<div class="review-card">
<div class="card-text">“LedgerLens made the report review process much easier. The source evidence helped me quickly understand where each finding came from.”</div>
<div class="review-name">Aarav Mehta</div>
<div class="review-role">Finance Analyst, Mumbai</div>
</div>

<div class="review-card">
<div class="card-text">“The risk and red flag sections are useful for preparing internal discussion points before a client or vendor review.”</div>
<div class="review-name">Priya Nair</div>
<div class="review-role">Business Consultant, Bengaluru</div>
</div>

<div class="review-card">
<div class="card-text">“The dashboard feels more structured than a normal PDF chatbot because it turns documents into a proper due diligence report.”</div>
<div class="review-name">Rohan Kulkarni</div>
<div class="review-role">MBA Student, Pune</div>
</div>
</div>
</section>

<section class="section">
<div class="contact-card">
<div class="card-title">Contact Support</div>
<div class="card-text">
Have a query, feedback, or deployment issue? Fill the form below or email:
<br><br>
<b style="color:white;">sharvaridhekre05@gmail.com</b>
</div>

<form class="query-form" action="https://formsubmit.co/sharvaridhekre05@gmail.com" method="POST">
<input type="hidden" name="_subject" value="New LedgerLens Query">
<input type="hidden" name="_captcha" value="false">
<input type="text" name="name" placeholder="Your name" required>
<input type="email" name="email" placeholder="Your email" required>
<textarea name="message" rows="5" placeholder="Write your query here..." required></textarea>
<button type="submit">Send Query</button>
</form>

<a class="contact-btn" href="mailto:sharvaridhekre05@gmail.com?subject=LedgerLens%20Query">Open Email App</a>
</div>
</section>

<div class="footer">
LedgerLens is a business document intelligence MVP built for learning and portfolio demonstration.
This public demo is not financial advice and should be used only with public or non-confidential documents.
For confidential company use, deploy privately with secure infrastructure.
</div>
""",
        unsafe_allow_html=True,
    )

# =========================
# SCREENS
# =========================
def render_home():
    render_nav()
    st.markdown(
        """
<section class="hero">
<div>
<div class="eyebrow">Secure Business Document Intelligence</div>
<div class="logo-pop">LedgerLens</div>
<div class="hero-title">
Business due diligence powered by <span class="gradient-text">source-backed retrieval.</span>
</div>
<div class="hero-subtitle">
LedgerLens is a RAG-based platform that reviews business documents, retrieves evidence, and produces professional due diligence reports for internal business use.
</div>
</div>

<div class="hero-visual">
<div class="blob"></div>
<div class="float-card terminal">
<span class="dot r"></span><span class="dot y"></span><span class="dot g"></span>
<div class="term-line">evidence-first document review</div>
<div class="term-line">multi-document due diligence flow</div>
<div class="term-line">risk, red flag, and growth analysis</div>
<div class="term-line">professional report dashboard</div>
<div class="term-line">downloadable business-ready output</div>
</div>
<div class="float-card mini-left">
<div class="tiny">For Teams</div>
<div class="big">Review</div>
<div style="color:#cbd5e1;">Helps employees convert long reports into clear business actions.</div>
</div>
<div class="float-card mini-right">
<div class="tiny">RAG Core</div>
<div class="big">Cited</div>
<div style="color:#cbd5e1;">Answers are backed by retrieved document pages and evidence.</div>
</div>
</div>
</section>
""",
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        if st.button("Start Document Review"):
            go("workspace")
    with c2:
        if st.button("View Security Approach"):
            go("security")
    with c3:
        if st.button("View Product Plans"):
            go("plans")

    st.markdown(
        """
<section class="section">
<div class="section-title">Why choose LedgerLens?</div>
<div class="section-sub">
It is not a generic PDF chatbot. LedgerLens follows a due diligence workflow: upload documents, select review type, retrieve evidence, generate a structured report, and export it for business use.
</div>
<div class="grid3">
<div class="card"><div class="icon">📌</div><div class="card-title">Evidence-first retrieval</div><div class="card-text">Uses semantic search to retrieve relevant document sections before generating the report.</div></div>
<div class="card"><div class="icon">💼</div><div class="card-title">Workplace-ready reports</div><div class="card-text">Produces formal reports with findings, risks, follow-up questions, and source evidence.</div></div>
<div class="card"><div class="icon">📄</div><div class="card-title">Export and share</div><div class="card-text">Download PDF/TXT reports and share summary outputs for review discussions.</div></div>
</div>
</section>
""",
        unsafe_allow_html=True,
    )

def render_workspace():
    render_nav()
    top1, top2 = st.columns([0.18, 0.82])
    with top1:
        if st.button("← Home"):
            go("home")
    with top2:
        st.markdown("### Document Review Workspace")
    st.markdown('<div class="section-sub">Upload public or non-confidential business documents, choose a review type, and generate a professional report.</div>', unsafe_allow_html=True)

    st.markdown('<div class="shell">', unsafe_allow_html=True)
    left_col, right_col = st.columns([0.36, 0.64], gap="large")

    with left_col:
        st.markdown(
            """
<div class="panel">
<div class="panel-title">1. Upload Safety Confirmation</div>
<div class="panel-caption">This public demo is intended for public or non-confidential documents only.</div>
<div class="privacy-note">Do not upload confidential company data, personal data, trade secrets, legal documents, or restricted internal files in this public demo.</div>
</div>
""",
            unsafe_allow_html=True,
        )
        safe_to_upload = st.checkbox("I confirm these documents are public or non-confidential and suitable for demo processing.")
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<div class="panel"><div class="panel-title">2. Upload Documents</div><div class="panel-caption">Upload business PDFs for review. Free demo limit: 3 files at once.</div></div>', unsafe_allow_html=True)

        uploaded_files = []
        if safe_to_upload:
            uploaded_files = st.file_uploader("Upload PDFs", type=["pdf"], accept_multiple_files=True, label_visibility="collapsed")
        else:
            st.info("Confirm the safety checkbox to enable upload.")

    with right_col:
        if not uploaded_files:
            st.markdown(
                """
<div class="panel">
<div class="panel-title">3. Generate a Due Diligence Report</div>
<div class="panel-caption">Once your documents are uploaded, LedgerLens will build the RAG index and generate a professional report.</div>
<div class="grid3">
<div class="card"><div class="card-title">Executive Review</div><div class="card-text">Summary, key findings, risk level, and final view.</div></div>
<div class="card"><div class="card-title">Risk Review</div><div class="card-text">Risks, red flags, severity, and business impact.</div></div>
<div class="card"><div class="card-title">Custom Prompt</div><div class="card-text">Ask any due diligence question in plain language.</div></div>
</div>
</div>
""",
                unsafe_allow_html=True,
            )
            if not get_api_key():
                st.markdown('<div class="key-warning"><b>Groq API key not detected.</b><br>Add <code>GROQ_API_KEY=gsk_your_actual_key_here</code> in your <code>.env</code>, save, stop Streamlit, and run again.</div>', unsafe_allow_html=True)

        elif len(uploaded_files) > 3:
            st.markdown(
                """
<div class="pro-lock">
<h3>Pro Plan Required</h3>
The free demo supports up to <b>3 PDFs</b> at once. You uploaded more than 3 files.
<br><br><b>Pro workflow includes:</b>
<br>⭐ More than 3 PDFs at once
<br>⭐ Branded downloadable reports
<br>⭐ Saved analysis history
<br><br>Please remove extra files and keep only 3 PDFs for the free demo.
</div>
""",
                unsafe_allow_html=True,
            )

        else:
            with st.spinner("Reading documents, creating chunks, and building the FAISS index..."):
                all_chunks: List[Dict] = []
                combined_text = ""
                total_pages = 0
                doc_names = []
                for file in uploaded_files:
                    doc_text, page_count, doc_chunks = extract_pdf_chunks(file)
                    combined_text += "\n" + doc_text
                    total_pages += page_count
                    all_chunks.extend(doc_chunks)
                    doc_names.append(file.name)

                if not all_chunks:
                    st.error("Could not extract readable text. Try text-based PDFs, not scanned image PDFs.")
                    st.stop()

                index = build_faiss_index(all_chunks)
                risk_label, risk_score = estimate_risk_signal(combined_text)

            m1, m2, m3, m4 = st.columns(4)
            with m1:
                st.markdown(f'<div class="metric"><div class="metric-label">Documents</div><div class="metric-value">{len(uploaded_files)}</div></div>', unsafe_allow_html=True)
            with m2:
                st.markdown(f'<div class="metric"><div class="metric-label">Pages</div><div class="metric-value">{total_pages}</div></div>', unsafe_allow_html=True)
            with m3:
                st.markdown(f'<div class="metric"><div class="metric-label">Risk Signal</div><div class="metric-value">{risk_label}</div></div>', unsafe_allow_html=True)
            with m4:
                groq_value = "Ready" if get_api_key() else "Missing"
                st.markdown(f'<div class="metric"><div class="metric-label">Groq API</div><div class="metric-value">{groq_value}</div></div>', unsafe_allow_html=True)

            if not get_api_key():
                st.markdown('<div class="key-warning"><b>Groq API key missing.</b><br>Your document upload and FAISS index are working, but report generation requires your key in <code>.env</code>.</div>', unsafe_allow_html=True)

            review_type = st.selectbox(
                "Review type",
                [
                    "Executive Due Diligence Report",
                    "Risk and Red Flag Review",
                    "Growth Opportunity Review",
                    "Compare Uploaded Documents",
                    "Custom Due Diligence Question",
                ],
            )
            user_prompt = st.text_area(
                "Due diligence request",
                value="Prepare a proper due diligence report.",
                height=110,
                placeholder="Example: Identify risks, red flags, key findings, and recommended follow-up questions.",
            )

            if st.button("Generate LedgerLens Report"):
                if not user_prompt.strip():
                    st.warning("Please enter a due diligence request.")
                else:
                    mode = "standard"
                    if "Risk" in review_type:
                        mode = "risk"
                    elif "Growth" in review_type:
                        mode = "growth"
                    elif "Compare" in review_type:
                        mode = "compare"

                    final_question = f"{review_type}: {user_prompt.strip()}"
                    with st.spinner("Retrieving evidence and generating a professional due diligence report..."):
                        relevant_chunks = retrieve_relevant_chunks(final_question, all_chunks, index, top_k=7)
                        answer = ask_groq(final_question, relevant_chunks, mode=mode)

                    st.session_state.report_ready = True
                    st.session_state.latest_question = final_question
                    st.session_state.latest_answer = answer
                    st.session_state.latest_sources = relevant_chunks
                    st.session_state.latest_doc_names = doc_names
                    st.session_state.latest_metrics = {
                        "documents": len(uploaded_files),
                        "pages": total_pages,
                        "risk": risk_label,
                        "evidence": len(relevant_chunks),
                        "review_type": review_type,
                    }
                    st.session_state.share_summary = "\n".join(generate_summary_points(answer))
                    go("report")
    st.markdown("</div>", unsafe_allow_html=True)

def render_report():
    render_nav()
    if not st.session_state.get("report_ready"):
        st.warning("No report has been generated yet.")
        if st.button("Go to Workspace"):
            go("workspace")
        return

    metrics = st.session_state.latest_metrics
    answer = st.session_state.latest_answer
    question = st.session_state.latest_question
    sources = st.session_state.latest_sources
    doc_names = st.session_state.latest_doc_names

    c1, c2, c3 = st.columns([0.18, 0.18, 0.64])
    with c1:
        if st.button("← Workspace"):
            go("workspace")
    with c2:
        if st.button("New Review"):
            clear_report()
            go("workspace")
    with c3:
        st.markdown("### LedgerLens Report Dashboard")

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.markdown(f'<div class="metric"><div class="metric-label">Documents</div><div class="metric-value">{metrics["documents"]}</div></div>', unsafe_allow_html=True)
    with m2:
        st.markdown(f'<div class="metric"><div class="metric-label">Pages</div><div class="metric-value">{metrics["pages"]}</div></div>', unsafe_allow_html=True)
    with m3:
        st.markdown(f'<div class="metric"><div class="metric-label">Risk Signal</div><div class="metric-value">{metrics["risk"]}</div></div>', unsafe_allow_html=True)
    with m4:
        st.markdown(f'<div class="metric"><div class="metric-label">Evidence Sources</div><div class="metric-value">{metrics["evidence"]}</div></div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    report_text = build_txt_report(question, answer, sources, doc_names)
    pdf_bytes = make_pdf_bytes("LedgerLens Business Due Diligence Report", report_text)

    left, right = st.columns([0.68, 0.32], gap="large")
    with left:
        st.markdown('<div class="report-card">', unsafe_allow_html=True)
        st.markdown('<div class="report-title">Main Analysis Points</div>', unsafe_allow_html=True)
        st.caption("Quick executive view. Open the full report for detailed analysis.")
        for point in generate_summary_points(answer):
            st.markdown(f'<div class="summary-bullet">• {html.escape(point)}</div>', unsafe_allow_html=True)

        with st.expander("Click here to view full analysis report", expanded=False):
            escaped = html.escape(answer).replace("\n", "<br>")
            st.markdown(f'<div class="full-report">{escaped}</div>', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with right:
        st.markdown('<div class="share-box">', unsafe_allow_html=True)
        st.markdown("### Download Report")
        st.download_button("Download PDF Report", data=pdf_bytes, file_name="ledgerlens_due_diligence_report.pdf", mime="application/pdf")
        st.download_button("Download TXT Report", data=report_text, file_name="ledgerlens_due_diligence_report.txt", mime="text/plain")

        st.markdown("### Share Options")
        summary_for_share = st.session_state.share_summary[:1200]
        mail_body = re.sub(r"\s+", "%20", summary_for_share)
        st.markdown(f'<a class="contact-btn" href="mailto:?subject=LedgerLens%20Due%20Diligence%20Report&body={mail_body}">Share by Email</a>', unsafe_allow_html=True)
        st.text_area("Copy summary", value=summary_for_share, height=170)
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<section class="section"><div class="section-title">Retrieved Source Evidence</div></section>', unsafe_allow_html=True)
    for i, chunk in enumerate(sources, start=1):
        safe_text = html.escape(chunk["text"][:1000])
        st.markdown(
            f"""
<div class="source">
<div class="badge">Source {i} • {html.escape(chunk["doc"])} • Page {chunk["page"]} • Similarity {chunk["score"]:.2f}</div>
<br>{safe_text}...
</div>
""",
            unsafe_allow_html=True,
        )

def render_security():
    render_nav()
    if st.button("← Home"):
        go("home")
    st.markdown(
        """
<section class="section">
<div class="section-title">Security-first design for company documents.</div>
<div class="section-sub">
Business documents may contain confidential financial, operational, or legal information. LedgerLens uses a public demo mode for non-confidential files and defines a secure enterprise architecture for real company deployment.
</div>
<div class="security-box">
<div class="grid3">
<div><div class="card-title">Public Demo Mode</div><div class="card-text">Use public annual reports, investor presentations, and non-confidential documents only. This version processes documents during the active session and does not intentionally store uploaded files in a database.</div></div>
<div><div class="card-title">Private Business Mode</div><div class="card-text">For confidential company documents, LedgerLens should run in a private deployment with controlled access, encrypted storage, automatic file deletion, private vector indexing, and audit logs.</div></div>
<div><div class="card-title">Private LLM Option</div><div class="card-text">For sensitive business data, the enterprise version can use a private LLM endpoint or local model inference so confidential content is not sent to a public third-party API.</div></div>
</div>
</div>
</section>
""",
        unsafe_allow_html=True,
    )

def render_plans():
    render_nav()
    if st.button("← Home"):
        go("home")
    st.markdown(
        """
<section class="section">
<div class="section-title">Plans for different review needs.</div>
<div class="section-sub">The free demo keeps the core RAG workflow accessible. Pro and Enterprise are product roadmap concepts for business deployment.</div>
<div class="grid3">
<div class="pricing popular">
<div class="price-name">Free Demo</div><div class="price">₹0 <span>/ up to 3 PDFs</span></div>
<div class="check">✅ Upload up to three non-confidential PDFs</div>
<div class="check">✅ Ask document questions</div>
<div class="check">✅ Executive due diligence report</div>
<div class="check">✅ Risk and growth review</div>
<div class="check">✅ Source evidence with page numbers</div>
<div class="check">✅ Download PDF report</div>
</div>
<div class="pricing">
<div class="price-name">Pro</div><div class="price">₹499 <span>/ future concept</span></div>
<div class="check">⭐ More than 3 PDFs at once</div>
<div class="check">⭐ Branded downloadable reports</div>
<div class="check">⭐ Saved analysis history</div>
</div>
<div class="pricing">
<div class="price-name">Enterprise</div><div class="price">Custom <span>/ secure deployment</span></div>
<div class="check">🏢 Private company workspace</div>
<div class="check">🏢 Role-based access control</div>
<div class="check">🏢 Encrypted storage and audit logs</div>
<div class="check">🏢 Private LLM / local model option</div>
</div>
</div>
</section>
""",
        unsafe_allow_html=True,
    )

# =========================
# ROUTER
# =========================
if st.session_state.page == "home":
    render_home()
elif st.session_state.page == "workspace":
    render_workspace()
elif st.session_state.page == "report":
    render_report()
elif st.session_state.page == "security":
    render_security()
elif st.session_state.page == "plans":
    render_plans()
else:
    render_home()

render_footer()
