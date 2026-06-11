import os
import re
import html
import sqlite3
import hashlib
import secrets
import time
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from urllib.parse import quote

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
if "auth_user" not in st.session_state:
    st.session_state.auth_user = None
if "active_project_id" not in st.session_state:
    st.session_state.active_project_id = None
if "show_help_widget" not in st.session_state:
    st.session_state.show_help_widget = False
if "help_bot_answer" not in st.session_state:
    st.session_state.help_bot_answer = ""

DB_PATH = os.getenv("LEDGERLENS_DB_PATH", "ledgerlens.db")

# Demo admin emails: only these accounts can open the Admin DB Viewer.
ADMIN_EMAILS = {
    "sharvaridhekre05@gmail.com",
    "sharvaridhekre388@gmail.com",
    "gauridhekre@gmail.com",
}


def go(page: str):
    st.session_state.page = page
    st.rerun()


def clear_report():
    for key in [
        "report_ready", "latest_question", "latest_answer", "latest_sources",
        "latest_doc_names", "latest_metrics", "share_summary", "latest_report_id"
    ]:
        if key in st.session_state:
            del st.session_state[key]
    st.session_state.report_ready = False


def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            plan TEXT DEFAULT 'Free',
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            project_name TEXT NOT NULL,
            project_type TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            project_id INTEGER NOT NULL,
            file_name TEXT NOT NULL,
            page_count INTEGER DEFAULT 0,
            uploaded_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(project_id) REFERENCES projects(id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            project_id INTEGER,
            report_title TEXT NOT NULL,
            report_type TEXT NOT NULL,
            report_text TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(project_id) REFERENCES projects(id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS login_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            email TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            report_id INTEGER,
            rating INTEGER NOT NULL,
            review_text TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(report_id) REFERENCES reports(id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            plan TEXT NOT NULL,
            amount INTEGER NOT NULL,
            payment_status TEXT NOT NULL,
            payment_method TEXT NOT NULL,
            payment_reference TEXT,
            activated_by TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS email_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            recipient TEXT NOT NULL,
            subject TEXT NOT NULL,
            status TEXT NOT NULL,
            message TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    conn.commit()
    conn.close()


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000)
    return f"pbkdf2_sha256${salt}${key.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, salt, stored_key = stored_hash.split("$", 2)
        if algorithm != "pbkdf2_sha256":
            return False
        key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000)
        return secrets.compare_digest(key.hex(), stored_key)
    except Exception:
        return False


def log_activity(user_id: int, action: str):
    conn = get_db()
    conn.execute("INSERT INTO activity (user_id, action, created_at) VALUES (?, ?, ?)", (user_id, action, now_str()))
    conn.commit()
    conn.close()


def log_login_event(user_id: int, email: str, status: str):
    conn = get_db()
    conn.execute(
        "INSERT INTO login_events (user_id, email, status, created_at) VALUES (?, ?, ?, ?)",
        (user_id, email.strip().lower(), status, now_str()),
    )
    conn.commit()
    conn.close()


def plan_upload_limit(plan: str) -> Optional[int]:
    plan_normalized = (plan or "Free").strip().lower()
    if plan_normalized == "free":
        return 5
    return None  # Pro and Enterprise are unlimited in this MVP.


def plan_amount(plan: str) -> int:
    plan_normalized = (plan or "Free").strip().lower()
    if plan_normalized == "pro":
        return 99
    if plan_normalized == "enterprise":
        return 299
    return 0


def update_user_plan(user_id: int, new_plan: str, activated_by: str, payment_status: str = "manual_admin_activation") -> bool:
    allowed = {"Free", "Pro", "Enterprise"}
    if new_plan not in allowed:
        return False
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET plan = ? WHERE id = ?", (new_plan, int(user_id)))
    if cur.rowcount == 0:
        conn.close()
        return False
    cur.execute(
        """
        INSERT INTO payments (user_id, plan, amount, payment_status, payment_method, payment_reference, activated_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (int(user_id), new_plan, plan_amount(new_plan), payment_status, "admin_manual", f"admin-{now_str()}", activated_by, now_str()),
    )
    conn.commit()
    conn.close()
    log_activity(int(user_id), f"Plan changed to {new_plan} by admin")
    return True


def save_review(user_id: int, report_id: Optional[int], rating: int, review_text: str) -> int:
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO reviews (user_id, report_id, rating, review_text, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, report_id, int(rating), review_text.strip(), now_str()),
    )
    conn.commit()
    review_id = cur.lastrowid
    conn.close()
    log_activity(user_id, f"Submitted review rating {rating}/5")
    return review_id



def log_email_event(user_id: Optional[int], recipient: str, subject: str, status: str, message: str = ""):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO email_events (user_id, recipient, subject, status, message, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, recipient.strip().lower(), subject, status, message[:500], now_str()),
    )
    conn.commit()
    conn.close()


def send_email_optional(user_id: Optional[int], to_email: str, subject: str, body: str) -> Tuple[bool, str]:
    """
    Sends real email only when SMTP secrets are configured in Hugging Face.
    Required secrets:
    SMTP_HOST=smtp.gmail.com
    SMTP_PORT=587
    SMTP_USER=your_email@gmail.com
    SMTP_PASSWORD=your_gmail_app_password
    """
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
    smtp_port = int(os.getenv("SMTP_PORT", "587").strip() or "587")
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_password = os.getenv("SMTP_PASSWORD", "").strip()

    if not smtp_user or not smtp_password:
        log_email_event(user_id, to_email, subject, "prepared_not_sent", "SMTP secrets not configured")
        return False, "SMTP not configured. Email draft/log prepared only."

    try:
        msg = EmailMessage()
        msg["From"] = smtp_user
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.set_content(body)
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
        log_email_event(user_id, to_email, subject, "sent", "Email sent successfully")
        return True, "Email sent successfully."
    except Exception as exc:
        log_email_event(user_id, to_email, subject, "failed", str(exc))
        return False, f"Email sending failed: {exc}"


def send_welcome_email(user_id: int, name: str, email: str):
    subject = "Welcome to LedgerLens"
    body = f"""Hi {name},

Welcome to LedgerLens.

Your private workspace is ready. You can now create projects, upload business PDFs, generate source-backed due diligence reports, and save reports in your workspace.

Live app: https://sharvarid01-ledgerlens.hf.space

Regards,
LedgerLens Team
"""
    return send_email_optional(user_id, email, subject, body)


def create_user(name: str, email: str, password: str) -> Tuple[bool, str]:
    email = email.strip().lower()
    if not name.strip() or not email or not password:
        return False, "Please fill all fields."
    if len(password) < 6:
        return False, "Password should be at least 6 characters."
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (name, email, password_hash, plan, created_at) VALUES (?, ?, ?, ?, ?)",
            (name.strip(), email, hash_password(password), "Free", now_str()),
        )
        conn.commit()
        user_id = cur.lastrowid
        log_activity(user_id, "Account created")
        send_welcome_email(user_id, name.strip(), email)
        return True, "Account created successfully. Please sign in. Welcome email is sent if SMTP is configured."
    except sqlite3.IntegrityError:
        return False, "This email is already registered. Please sign in."
    finally:
        conn.close()


def authenticate_user(email: str, password: str) -> Tuple[bool, Optional[Dict], str]:
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
    conn.close()
    if not row:
        return False, None, "No account found with this email."
    if not verify_password(password, row["password_hash"]):
        return False, None, "Incorrect password."
    user = {"id": row["id"], "name": row["name"], "email": row["email"], "plan": row["plan"], "created_at": row["created_at"]}
    log_activity(user["id"], "Signed in")
    log_login_event(user["id"], user["email"], "success")
    return True, user, "Signed in successfully."


def current_user() -> Optional[Dict]:
    return st.session_state.get("auth_user")


def is_admin(user: Optional[Dict]) -> bool:
    return bool(user and user.get("email", "").strip().lower() in ADMIN_EMAILS)


def require_login(target_after_login: str = "workspace"):
    st.markdown(
        """
        <div class="panel">
        <div class="panel-title">Sign in required</div>
        <div class="panel-caption">Please sign in or create an account to access your private workspace, save projects, and view previous reports.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        if st.button("Sign In"):
            st.session_state.after_login = target_after_login
            go("login")
    with c2:
        if st.button("Create Account"):
            st.session_state.after_login = target_after_login
            go("signup")


def create_project(user_id: int, project_name: str, project_type: str) -> Tuple[bool, str, Optional[int]]:
    if not project_name.strip():
        return False, "Project name is required.", None
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO projects (user_id, project_name, project_type, created_at) VALUES (?, ?, ?, ?)",
        (user_id, project_name.strip(), project_type, now_str()),
    )
    conn.commit()
    project_id = cur.lastrowid
    conn.close()
    log_activity(user_id, f"Created project: {project_name.strip()}")
    return True, "Project created successfully.", project_id


def get_projects(user_id: int) -> List[Dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM projects WHERE user_id = ? ORDER BY id DESC",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_project(project_id: Optional[int]) -> Optional[Dict]:
    if not project_id:
        return None
    conn = get_db()
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def save_project_documents(user_id: int, project_id: int, documents: List[Dict]):
    """Store uploaded document metadata for project history.
    The demo does not persist raw PDF files; it stores file names/page counts for workspace tracking.
    """
    if not documents:
        return
    conn = get_db()
    existing = {
        row[0] for row in conn.execute(
            "SELECT file_name FROM documents WHERE user_id = ? AND project_id = ?",
            (user_id, project_id),
        ).fetchall()
    }
    for doc in documents:
        file_name = doc.get("file_name", "Uploaded document")
        page_count = int(doc.get("page_count", 0) or 0)
        if file_name not in existing:
            conn.execute(
                "INSERT INTO documents (user_id, project_id, file_name, page_count, uploaded_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, project_id, file_name, page_count, now_str()),
            )
    conn.commit()
    conn.close()
    log_activity(user_id, f"Uploaded {len(documents)} document(s) to project #{project_id}")


def get_project_documents(project_id: Optional[int], user_id: Optional[int] = None) -> List[Dict]:
    if not project_id:
        return []
    conn = get_db()
    if user_id is not None:
        rows = conn.execute(
            "SELECT * FROM documents WHERE project_id = ? AND user_id = ? ORDER BY id DESC",
            (project_id, user_id),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM documents WHERE project_id = ? ORDER BY id DESC",
            (project_id,),
        ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def save_report(user_id: int, project_id: Optional[int], report_title: str, report_type: str, report_text: str) -> int:
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO reports (user_id, project_id, report_title, report_type, report_text, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, project_id, report_title, report_type, report_text, now_str()),
    )
    conn.commit()
    report_id = cur.lastrowid
    conn.close()
    log_activity(user_id, f"Generated report: {report_title}")
    return report_id




def update_report(report_id: int, user_id: int, new_text: str) -> bool:
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE reports SET report_text = ? WHERE id = ? AND user_id = ?",
        (new_text, report_id, user_id),
    )
    conn.commit()
    updated = cur.rowcount > 0
    conn.close()
    if updated:
        log_activity(user_id, f"Edited saved report #{report_id}")
    return updated

def get_reports(user_id: int, limit: int = 50) -> List[Dict]:
    conn = get_db()
    rows = conn.execute(
        """
        SELECT reports.*, projects.project_name
        FROM reports
        LEFT JOIN projects ON reports.project_id = projects.id
        WHERE reports.user_id = ?
        ORDER BY reports.id DESC
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_activity(user_id: int, limit: int = 8) -> List[Dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM activity WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_user_stats(user_id: int) -> Dict:
    conn = get_db()
    projects_count = conn.execute("SELECT COUNT(*) FROM projects WHERE user_id = ?", (user_id,)).fetchone()[0]
    reports_count = conn.execute("SELECT COUNT(*) FROM reports WHERE user_id = ?", (user_id,)).fetchone()[0]
    documents_count = conn.execute("SELECT COUNT(*) FROM documents WHERE user_id = ?", (user_id,)).fetchone()[0]
    conn.close()
    return {"projects": projects_count, "reports": reports_count, "documents": documents_count}


def get_admin_table(table_name: str, limit: int = 100) -> List[Dict]:
    allowed_tables = {"users", "projects", "documents", "reports", "activity", "login_events", "reviews", "payments", "email_events"}
    if table_name not in allowed_tables:
        return []
    conn = get_db()
    rows = conn.execute(f"SELECT * FROM {table_name} ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    clean_rows = []
    for row in rows:
        item = dict(row)
        if "password_hash" in item:
            item["password_hash"] = "hidden_for_security"
        if "report_text" in item and item["report_text"]:
            item["report_text"] = item["report_text"][:500] + ("..." if len(item["report_text"]) > 500 else "")
        clean_rows.append(item)
    return clean_rows


def get_admin_counts() -> Dict:
    conn = get_db()
    counts = {}
    for table in ["users", "projects", "documents", "reports", "activity", "login_events", "reviews", "payments", "email_events"]:
        counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    conn.close()
    return counts


init_db()

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
.block-container { max-width: 1220px; padding-top: 0rem; padding-bottom: 3rem; }
[data-testid="stHeader"] { background: rgba(2,6,23,0); }
#MainMenu, footer { visibility: hidden; }
.navbar {
    position: sticky; top: 0; z-index: 999;
    margin-bottom: .35rem; padding: .62rem 1rem;
    border: 1px solid rgba(148,163,184,.18); border-radius: 999px;
    background: rgba(2,6,23,.72); backdrop-filter: blur(18px);
    display: flex; align-items: center; justify-content: space-between;
    box-shadow: 0 18px 50px rgba(0,0,0,.24);
}
.nav-brand { font-weight: 950; letter-spacing: -.04em; font-size: 1.08rem; color: white; }
.nav-mini { color: #94a3b8; font-size: .84rem; font-weight: 700; }
div[data-testid="stHorizontalBlock"]:has(button[kind="secondary"]) { gap: .35rem; }
.hero {
    min-height: 46vh; display: grid; grid-template-columns: .98fr 1.02fr;
    gap: 1.7rem; align-items: center; padding: .25rem 0 1.15rem;
}
.eyebrow {
    display: inline-flex; padding: .44rem .76rem; border-radius: 999px;
    background: rgba(34,197,94,.12); border: 1px solid rgba(74,222,128,.35);
    color: #bbf7d0; font-size: .74rem; font-weight: 950; letter-spacing: .06em;
    text-transform: uppercase; animation: fadeUp .8s ease both;
}
.logo-pop {
    margin-top: .35rem; font-size: clamp(2.65rem, 5.2vw, 4.8rem); line-height: .92;
    font-weight: 950; letter-spacing: -.09em; color: white; animation: logoPop 1.2s ease both;
}
.hero-title {
    margin-top: .35rem; max-width: 690px; font-size: clamp(1.7rem, 2.85vw, 2.85rem);
    line-height: 1.05; font-weight: 900; letter-spacing: -.06em; color: white; animation: fadeUp 1s ease both;
}
.gradient-text {
    background: linear-gradient(135deg, #4ade80, #5eead4, #60a5fa, #c084fc);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}
.hero-subtitle {
    margin-top: .75rem; max-width: 680px; color: #cbd5e1; font-size: .96rem;
    line-height: 1.72; animation: fadeUp 1.1s ease both;
}
.hero-visual { position: relative; min-height: 310px; animation: fadeIn 1.3s ease both; }
.blob {
    position: absolute; right: 40px; top: -5px; width: 275px; height: 275px;
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
.terminal { width: 88%; right: 0; top: 0%; min-height: 200px; }
.term-line { color: #cbd5e1; font-family: ui-monospace, Consolas, monospace; font-size: .82rem; padding: .30rem 0; }
.dot { width: 10px; height: 10px; border-radius: 999px; display: inline-block; margin-right: .32rem; }
.r { background: #fb7185; } .y { background: #fbbf24; } .g { background: #34d399; }
.mini-left { width: 46%; left: 0; bottom: 8%; animation: floaty 5s ease-in-out infinite; }
.mini-right { width: 39%; right: 5%; bottom: 0; animation: floaty 6s ease-in-out infinite reverse; }
.big { font-size: 2.1rem; font-weight: 950; letter-spacing: -.06em; color: white; }
.tiny { color: #94a3b8; font-size: .72rem; font-weight: 850; text-transform: uppercase; letter-spacing: .06em; }
.section { padding: 1.6rem 0 .8rem; }
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
.floating-help-icon {
    position: fixed;
    right: 24px;
    bottom: 24px;
    width: 58px;
    height: 58px;
    border-radius: 999px;
    background: linear-gradient(135deg,#22c55e,#2563eb);
    color: white !important;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.65rem;
    text-decoration: none !important;
    box-shadow: 0 18px 60px rgba(37,99,235,.42);
    border: 1px solid rgba(255,255,255,.24);
    z-index: 99999;
}
.help-drawer {
    position: fixed;
    right: 24px;
    bottom: 96px;
    width: min(390px, calc(100vw - 48px));
    max-height: 74vh;
    overflow-y: auto;
    padding: 1.05rem;
    border-radius: 24px;
    background: rgba(2,6,23,.96);
    border: 1px solid rgba(74,222,128,.28);
    box-shadow: 0 28px 90px rgba(0,0,0,.55);
    z-index: 99998;
}
.help-drawer-title { color: white; font-size: 1.08rem; font-weight: 950; margin-bottom: .35rem; }
.help-drawer-text { color: #cbd5e1; font-size: .86rem; line-height: 1.55; }
.help-chip {
    display: inline-block;
    margin: .22rem .18rem .22rem 0;
    padding: .35rem .55rem;
    border-radius: 999px;
    background: rgba(34,197,94,.12);
    border: 1px solid rgba(74,222,128,.22);
    color: #bbf7d0;
    font-size: .78rem;
    font-weight: 800;
}
.close-help {
    float: right;
    color: #93c5fd !important;
    text-decoration: none !important;
    font-weight: 900;
}

.floating-help {
    position: fixed; right: 22px; bottom: 24px; z-index: 9999;
    padding: .85rem 1rem; border-radius: 999px; color: white!important;
    background: linear-gradient(135deg,#22c55e,#2563eb); text-decoration: none!important;
    font-weight: 950; box-shadow: 0 18px 55px rgba(37,99,235,.35);
    border: 1px solid rgba(255,255,255,.18);
}
.floating-help:hover { transform: translateY(-2px); }
.rating-card { padding: 1.15rem; border-radius: 22px; background: rgba(15,23,42,.72); border: 1px solid rgba(74,222,128,.25); }

/* Reduce Streamlit default top whitespace on deployed app */
section.main > div { padding-top: 0rem !important; }
[data-testid="stAppViewContainer"] > .main { padding-top: 0rem !important; }
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
    width: auto; min-width: 145px; border-radius: 999px; border: 0;
    background: linear-gradient(135deg,#22c55e,#2563eb)!important;
    color: white!important; font-weight: 950; padding: .66rem 1rem;
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

/* Hide Streamlit's default 'Press Enter to submit form' helper text */
div[data-testid="InputInstructions"],
.stTextInput div[data-testid="InputInstructions"],
.stTextArea div[data-testid="InputInstructions"] {
    display: none !important;
    visibility: hidden !important;
    height: 0 !important;
}

/* Make support action buttons clearly visible */
.contact-btn,
.contact-btn:visited,
.contact-btn:active {
    color: #ffffff !important;
    text-decoration: none !important;
}
.contact-btn:hover {
    filter: brightness(1.12);
    transform: translateY(-1px);
}
.email-btn {
    margin-left: .7rem;
    background: linear-gradient(135deg,#7c3aed,#2563eb) !important;
    box-shadow: 0 12px 30px rgba(37,99,235,.22);
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
    .hero-visual { min-height: 310px; }
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

def compact_text(text: str, max_chars: int = 950) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + " ..."

def call_groq(prompt: str, max_tokens: int = 1800) -> str:
    api_key = get_api_key()
    if not api_key:
        return (
            "Groq API key is missing. Add GROQ_API_KEY in Hugging Face secrets or local .env. "
            "Your document upload and retrieval pipeline are working, but report generation needs the key."
        )

    # Groq free/on-demand tier has a low tokens-per-minute limit.
    # Keep prompt + answer under that limit so the app does not crash.
    safe_prompt = prompt
    if len(safe_prompt) > 11500:
        safe_prompt = safe_prompt[:11500].rsplit(" ", 1)[0] + "\n\n[Context shortened automatically to stay within API token limits.]"

    client = Groq(api_key=api_key)
    try:
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are LedgerLens, a professional business due diligence analyst. "
                        "Write concise, evidence-backed business reports. "
                        "Do not use chatbot language. Do not say 'as an AI'. "
                        "Use only retrieved evidence. Every key finding must cite document name and page number."
                    ),
                },
                {"role": "user", "content": safe_prompt},
            ],
            temperature=0.12,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content
    except Exception as exc:
        msg = str(exc)
        if "rate_limit" in msg.lower() or "Request too large" in msg or "tokens per minute" in msg:
            return (
                "LedgerLens could not generate the report because the current Groq free/on-demand token limit was exceeded.\n\n"
                "What to do now:\n"
                "- Choose Executive report depth.\n"
                "- Use 10 pages or a smaller custom page target.\n"
                "- Upload fewer/smaller PDFs for this run.\n"
                "- Try again after 60 seconds.\n\n"
                "The app has handled the error safely; your document upload and retrieval steps are still working."
            )
        return f"Report generation failed safely: {msg[:700]}"

def make_source_context(chunks: List[Dict], max_chars: int = 700) -> str:
    """Build a compact evidence pack with document and page citations."""
    return "\n\n".join(
        [
            f"Evidence {i + 1} | Document: {chunk['doc']} | Page {chunk['page']} | Similarity: {chunk.get('score', 0):.2f}\n{compact_text(chunk['text'], max_chars)}"
            for i, chunk in enumerate(chunks)
        ]
    )

def section_prompt(section_title: str, final_question: str, context: str, audience: str, report_depth: str, target_pages_value: str) -> str:
    return f"""
You are preparing one section of a professional LedgerLens financial intelligence report.

Report request:
{final_question}

Current section to write:
{section_title}

Audience:
{audience}

Depth:
{report_depth}

Target report size selected by user:
{target_pages_value}

Retrieved evidence for this section:
{context}

Write only this section.
Rules:
- Write in a professional analyst tone, not chatbot tone.
- Use only the evidence provided.
- Do not invent figures, dates, revenue values, ratios, or facts.
- Every important finding must end with an inline citation: (Source: Document_Name.pdf, Page X).
- If a topic is not identified in evidence, write: Not identified in the retrieved document evidence.
- Use clear headings and short paragraphs.
- Use clean bullets where useful.
- Do not use markdown tables, pipe symbols, emojis, or decorative formatting.
- Make the section detailed enough to be useful in a downloadable business report.
"""

def deterministic_evidence_register(sources: List[Dict]) -> str:
    lines = ["\n10. Source Evidence Register", "This register lists the evidence retrieved and used by the LedgerLens report engine."]
    seen = set()
    for i, src in enumerate(sources, start=1):
        key = (src.get('doc'), src.get('page'), compact_text(src.get('text', ''), 120))
        if key in seen:
            continue
        seen.add(key)
        excerpt = compact_text(src.get('text', ''), 260)
        lines.append(f"- Evidence {i}: {src.get('doc')} - Page {src.get('page')} - {excerpt}")
    return "\n".join(lines)

def generate_sectioned_report(
    final_question: str,
    all_chunks: List[Dict],
    index,
    review_type: str,
    report_depth: str,
    target_pages_value: str,
    audience: str,
    mode: str = "standard",
) -> Tuple[str, List[Dict]]:
    """Generate a serious report section-by-section instead of one huge prompt.
    This makes the report more detailed and avoids Groq token-limit crashes.
    """
    base_sections = [
        "1. Executive Summary",
        "2. Documents Reviewed and Scope of Analysis",
        "3. Business Overview and Operating Context",
        "4. Financial Health and Operating Signals",
        "5. Key Risks and Red Flags",
        "6. Compliance, Governance, and Control Concerns",
        "7. Growth Opportunities and Strategic Upside",
        "8. Investment Memo and Decision Considerations",
        "9. Recommended Follow-Up Questions",
    ]

    if report_depth == "Executive":
        sections = [base_sections[i] for i in [0, 1, 3, 4, 8]]
        max_tokens = 650
        context_chars = 520
    elif report_depth == "Standard":
        sections = [base_sections[i] for i in [0, 1, 2, 3, 4, 6, 8]]
        max_tokens = 850
        context_chars = 620
    else:
        sections = base_sections
        max_tokens = 1050
        context_chars = 700

    # For special report types, keep all core sections but bias retrieval and writing.
    type_guidance = {
        "Due Diligence": "full due diligence review",
        "Financial Health": "financial health, liquidity, revenue, costs, operating performance",
        "Investment Memo": "investment thesis, risks, upside, decision factors",
        "Compliance Review": "compliance, governance, audit, controls, disclosures",
        "Risk Assessment": "risks, red flags, severity, downside exposure",
        "Custom Analysis": "custom user request",
    }.get(review_type, review_type)

    report_parts = [
        "LedgerLens Professional Financial Intelligence Report",
        f"Report Type: {review_type}",
        f"Audience: {audience}",
        f"Report Depth: {report_depth}",
        f"Target Length Selected: {target_pages_value}",
        "Generation Method: Section-by-section RAG with source citations",
        "",
        "Visual Executive Dashboard",
        "- Risk snapshot: Generated from document-level risk signals and retrieved evidence.",
        "- Evidence model: Each section is generated from semantically retrieved document chunks.",
        "- Citation rule: Every major finding is expected to include document name and page number.",
        "",
    ]

    collected_sources: List[Dict] = []
    progress = st.progress(0, text="Starting LedgerLens report engine...")

    for idx, title in enumerate(sections, start=1):
        progress.progress((idx - 1) / max(len(sections), 1), text=f"Generating {title}...")
        section_query = f"{final_question} | {type_guidance} | {title}"
        # Fewer, tighter chunks per section. Different query per section creates better targeted evidence.
        section_chunks = retrieve_relevant_chunks(section_query, all_chunks, index, top_k=4)
        collected_sources.extend(section_chunks)
        context = make_source_context(section_chunks, max_chars=context_chars)
        prompt = section_prompt(title, final_question, context, audience, report_depth, target_pages_value)
        section_text = call_groq(prompt, max_tokens=max_tokens)
        report_parts.append(section_text.strip())
        report_parts.append("\n")
        # Avoid Groq TPM spikes on the free/on-demand tier for longer reports.
        if idx < len(sections):
            time.sleep(3)

    progress.progress(1.0, text="Finalizing citations and evidence register...")
    report_parts.append(deterministic_evidence_register(collected_sources[:18]))
    report_parts.append("\nFinal note: This report is generated for decision-support and internal review. It is not financial advice. Confidential business files should be processed only in a private deployment.")
    progress.empty()

    # De-duplicate sources while preserving order.
    deduped = []
    seen = set()
    for src in collected_sources:
        key = (src.get('doc'), src.get('page'), compact_text(src.get('text', ''), 140))
        if key not in seen:
            deduped.append(src)
            seen.add(key)
    return "\n".join(report_parts), deduped[:18]

def ask_groq(question: str, context_chunks: List[Dict], mode: str = "standard") -> str:
    # Backward-compatible simple answer function. The main report generator now uses generate_sectioned_report().
    context = make_source_context(context_chunks[:4], max_chars=650)
    prompt = f"""
Prepare a concise professional answer using the retrieved evidence.
Question: {question}
Evidence:
{context}
Rules: cite every major finding with (Source: Document_Name.pdf, Page X). Do not invent facts.
"""
    return call_groq(prompt, max_tokens=900)

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
    user = current_user()
    st.markdown(
        f"""
<div class="navbar">
    <div class="nav-brand">💼 LedgerLens</div>
    <div class="nav-mini">{'Signed in as ' + html.escape(user['name']) if user else 'RAG-powered due diligence workspace'}</div>
</div>
""",
        unsafe_allow_html=True,
    )
    if user:
        # Clean user navbar. Admin backend is never shown here.
        c1, c2, c3, c4, c5 = st.columns([1, 1.15, 1, 1, 1])
        with c1:
            if st.button("Home"):
                go("home")
        with c2:
            if st.button("Workspace"):
                go("workspace")
        with c3:
            if st.button("Reports"):
                go("reports")
        with c4:
            if st.button("Account"):
                go("account")
        with c5:
            if st.button("Logout"):
                log_activity(user["id"], "Logged out")
                st.session_state.auth_user = None
                st.session_state.active_project_id = None
                clear_report()
                go("home")
    else:
        c1, c2, c3, c4, c5, c6 = st.columns([1, 1, 1, 1, 1, 1])
        with c1:
            if st.button("Home"):
                go("home")
        with c2:
            if st.button("Security"):
                go("security")
        with c3:
            if st.button("Pricing"):
                go("plans")
        with c4:
            if st.button("Workspace"):
                st.session_state.after_login = "workspace"
                go("login")
        with c5:
            if st.button("Sign In"):
                go("login")
        with c6:
            if st.button("Sign Up"):
                go("signup")

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
<button type="submit">Send Query to Support</button>
</form>
<a class="contact-btn email-btn" href="mailto:sharvaridhekre05@gmail.com?subject=LedgerLens%20Query">Open Email App</a>
<div class="card-text" style="margin-top:.8rem;">Note: the support form uses FormSubmit. On the first submission, FormSubmit may send a one-time activation email to the support inbox.</div>
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
Enterprise financial intelligence powered by <span class="gradient-text">source-backed retrieval.</span>
</div>
<div class="hero-subtitle">
LedgerLens is a RAG-based platform that reviews business documents, retrieves evidence, and produces professional due diligence reports inside a secure user workspace.
</div>
</div>
<div class="hero-visual">
<div class="blob"></div>
<div class="float-card terminal">
<span class="dot r"></span><span class="dot y"></span><span class="dot g"></span>
<div class="term-line">secure login and private workspace</div>
<div class="term-line">project-based document review</div>
<div class="term-line">source-backed due diligence reports</div>
<div class="term-line">report history and export</div>
<div class="term-line">privacy-aware business workflow</div>
</div>
<div class="float-card mini-left">
<div class="tiny">Workspace</div>
<div class="big">Private</div>
<div style="color:#cbd5e1;">Users create projects and save reports in their own workspace.</div>
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
            if current_user():
                go("workspace")
            else:
                st.session_state.after_login = "workspace"
                go("login")
    with c2:
        if st.button("Create Free Account"):
            go("signup")
    with c3:
        if st.button("View Security Approach"):
            go("security")

    st.markdown(
        """
<section class="section">
<div class="section-title">Why LedgerLens is more than a PDF chatbot.</div>
<div class="section-sub">
LedgerLens combines authentication, user workspaces, project-based document uploads, vector search, source-backed answers, report history, and downloadable business reports. It is built like a financial intelligence platform, not just a chat window.
</div>
<div class="grid3">
<div class="card"><div class="icon">🔐</div><div class="card-title">Secure workspace flow</div><div class="card-text">Users sign in, create projects, and keep generated reports in their own workspace.</div></div>
<div class="card"><div class="icon">📌</div><div class="card-title">Evidence-first retrieval</div><div class="card-text">Uses embeddings and FAISS to retrieve relevant document sections before generating the report.</div></div>
<div class="card"><div class="icon">💼</div><div class="card-title">Business-ready reports</div><div class="card-text">Produces due diligence outputs with risks, findings, follow-up questions, and source evidence.</div></div>
</div>
</section>
""",
        unsafe_allow_html=True,
    )


def render_signup():
    render_nav()
    st.markdown('<section class="section"><div class="section-title">Create your LedgerLens account.</div><div class="section-sub">Sign up to access your private workspace, projects, and report history.</div></section>', unsafe_allow_html=True)
    left, right = st.columns([0.52, 0.48], gap="large")
    with left:
        with st.form("signup_form"):
            name = st.text_input("Full name")
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            confirm = st.text_input("Confirm password", type="password")
            submitted = st.form_submit_button("Create Account")
            if submitted:
                if password != confirm:
                    st.error("Passwords do not match.")
                else:
                    ok, msg = create_user(name, email, password)
                    if ok:
                        st.success(msg)
                        st.info("Now sign in using your email and password.")
                    else:
                        st.error(msg)
        if st.button("Already have an account? Sign In"):
            go("login")
    with right:
        st.markdown(
            """
<div class="security-box">
<div class="card-title">What your account enables</div>
<div class="card-text">
✅ Personal workspace<br>
✅ Project-based document review<br>
✅ Saved report history<br>
✅ Password hashing<br>
✅ User-isolated projects and reports<br><br>
Public demo note: Use only public or non-confidential files.
</div>
</div>
""",
            unsafe_allow_html=True,
        )


def render_login():
    render_nav()
    st.markdown('<section class="section"><div class="section-title">Sign in to your workspace.</div><div class="section-sub">Access your projects, previous reports, and document review workspace.</div></section>', unsafe_allow_html=True)
    left, right = st.columns([0.52, 0.48], gap="large")
    with left:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign In")
            if submitted:
                ok, user, msg = authenticate_user(email, password)
                if ok:
                    st.session_state.auth_user = user
                    st.success(msg)
                    target = st.session_state.get("after_login", "workspace")
                    go(target)
                else:
                    st.error(msg)
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Create Account"):
                go("signup")
        with c2:
            if st.button("Forgot Password"):
                go("forgot")
    with right:
        st.markdown(
            """
<div class="security-box">
<div class="card-title">Private Business Centre</div>
<div class="card-text">
In the enterprise version, each employee works inside a user-isolated workspace. Documents and reports are tied to a user and project, with password hashing, HTTPS upload flow, and configurable retention policies.
</div>
</div>
""",
            unsafe_allow_html=True,
        )


def render_forgot():
    render_nav()
    st.markdown('<section class="section"><div class="section-title">Forgot password.</div><div class="section-sub">This is a demo placeholder. In production, this would send a secure reset link or OTP to the registered email.</div></section>', unsafe_allow_html=True)
    email = st.text_input("Enter registered email")
    if st.button("Send Reset Link"):
        st.info("Demo mode: password reset email is not enabled yet. This placeholder shows the planned SaaS flow.")
    if st.button("Back to Sign In"):
        go("login")


def render_workspace():
    render_nav()
    user = current_user()
    if not user:
        require_login("workspace")
        return

    stats = get_user_stats(user["id"])
    projects = get_projects(user["id"])
    if projects and not st.session_state.get("active_project_id"):
        st.session_state.active_project_id = projects[0]["id"]

    st.markdown(
        f'<section class="section"><div class="section-title">My Workspace</div><div class="section-sub">Welcome, {html.escape(user["name"])}. Create projects, upload documents, generate reports, and access report history.</div></section>',
        unsafe_allow_html=True,
    )

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.markdown(f'<div class="metric"><div class="metric-label">Projects</div><div class="metric-value">{stats["projects"]}</div></div>', unsafe_allow_html=True)
    with m2:
        st.markdown(f'<div class="metric"><div class="metric-label">Reports</div><div class="metric-value">{stats["reports"]}</div></div>', unsafe_allow_html=True)
    with m3:
        st.markdown(f'<div class="metric"><div class="metric-label">Documents</div><div class="metric-value">{stats["documents"]}</div></div>', unsafe_allow_html=True)
    with m4:
        groq_value = "Ready" if get_api_key() else "Missing"
        st.markdown(f'<div class="metric"><div class="metric-label">Groq API</div><div class="metric-value">{groq_value}</div></div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    left, right = st.columns([0.34, 0.66], gap="large")

    with left:
        st.markdown('<div class="panel"><div class="panel-title">Create New Project</div><div class="panel-caption">Group documents by deal, company, client, or review purpose.</div></div>', unsafe_allow_html=True)
        with st.form("project_form"):
            project_name = st.text_input("Project name", placeholder="Example: ABC Acquisition")
            project_type = st.selectbox("Project type", ["Due Diligence", "Financial Health", "Investment Memo", "Compliance Review", "Risk Assessment", "Custom Analysis"])
            submitted = st.form_submit_button("Create Project")
            if submitted:
                ok, msg, project_id = create_project(user["id"], project_name, project_type)
                if ok:
                    st.session_state.active_project_id = project_id
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

        projects = get_projects(user["id"])
        if projects:
            project_options = {f'{p["project_name"]} — {p["project_type"]}': p["id"] for p in projects}
            labels = list(project_options.keys())
            current_label = labels[0]
            for label, pid in project_options.items():
                if pid == st.session_state.get("active_project_id"):
                    current_label = label
                    break
            selected = st.selectbox("Active project", labels, index=labels.index(current_label))
            st.session_state.active_project_id = project_options[selected]
        else:
            st.info("Create your first project to enable document upload.")

        if st.button("View Previous Reports"):
            go("reports")

        st.markdown(
            """
<div class="privacy-note">
<b>Privacy reminder:</b><br>
This public demo is for public or non-confidential PDFs only. For confidential business documents, use a private deployment with user-isolated storage, audit logs, retention policy, and private LLM/vector database options.
</div>
""",
            unsafe_allow_html=True,
        )

    with right:
        active_project = get_project(st.session_state.get("active_project_id"))
        if not active_project:
            st.markdown('<div class="panel"><div class="panel-title">Upload Documents</div><div class="panel-caption">Create a project first. Then upload PDFs inside that project.</div></div>', unsafe_allow_html=True)
            return

        stored_docs = get_project_documents(active_project["id"], user["id"])
        doc_tree = ""
        if stored_docs:
            doc_lines = "<br>".join([f"├── {html.escape(d['file_name'])} ({int(d.get('page_count') or 0)} pages)" for d in stored_docs[:8]])
            doc_tree = f"<br><br><b>Saved document history:</b><br>{doc_lines}"
        st.markdown(
            f'<div class="panel"><div class="panel-title">Project: {html.escape(active_project["project_name"])}</div><div class="panel-caption">Type: {html.escape(active_project["project_type"])}. Upload documents inside this project, like Annual Report, Audit Report, Balance Sheet. Current plan: {html.escape(user["plan"])}. Free limit: 5 PDFs. Pro and Enterprise: unlimited PDFs.{doc_tree}</div></div>',
            unsafe_allow_html=True,
        )
        safe_to_upload = st.checkbox("I confirm these documents are public or non-confidential and suitable for demo processing.")
        uploaded_files = []
        if safe_to_upload:
            uploaded_files = st.file_uploader("Upload PDFs", type=["pdf"], accept_multiple_files=True, label_visibility="collapsed")
        else:
            st.info("Confirm the safety checkbox to enable upload.")

        if not uploaded_files:
            st.markdown(
                """
<div class="panel">
<div class="panel-title">Generate a Due Diligence Report</div>
<div class="panel-caption">After upload, LedgerLens will build a FAISS index, retrieve relevant evidence, and generate a structured report.</div>
<div class="grid3">
<div class="card"><div class="card-title">Due Diligence</div><div class="card-text">Executive summary, key findings, source evidence.</div></div>
<div class="card"><div class="card-title">Risk Assessment</div><div class="card-text">Risks, red flags, severity, and business impact.</div></div>
<div class="card"><div class="card-title">Investment Memo</div><div class="card-text">Business signals and follow-up questions.</div></div>
</div>
</div>
""",
                unsafe_allow_html=True,
            )
            return

        upload_limit = plan_upload_limit(user.get("plan", "Free"))
        if upload_limit is not None and len(uploaded_files) > upload_limit:
            st.markdown(
                f"""
<div class="pro-lock">
<h3>Pro Plan Required</h3>
Your current <b>{html.escape(user.get('plan', 'Free'))}</b> plan supports up to <b>{upload_limit} PDFs</b> at once.
<br><br>Upgrade to <b>Pro ₹99/month</b> or <b>Enterprise ₹299/month</b> for unlimited uploads and premium features.
</div>
""",
                unsafe_allow_html=True,
            )
            return

        with st.spinner("Reading documents, creating chunks, and building the FAISS index..."):
            all_chunks: List[Dict] = []
            combined_text = ""
            total_pages = 0
            doc_names = []
            doc_meta = []
            for file in uploaded_files:
                doc_text, page_count, doc_chunks = extract_pdf_chunks(file)
                combined_text += "\n" + doc_text
                total_pages += page_count
                all_chunks.extend(doc_chunks)
                doc_names.append(file.name)
                doc_meta.append({"file_name": file.name, "page_count": page_count})
            save_project_documents(user["id"], active_project["id"], doc_meta)

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
            st.markdown(f'<div class="metric"><div class="metric-label">Project</div><div class="metric-value">#{active_project["id"]}</div></div>', unsafe_allow_html=True)

        if not get_api_key():
            st.markdown('<div class="key-warning"><b>Groq API key missing.</b><br>Report generation requires GROQ_API_KEY in Hugging Face secrets or local .env.</div>', unsafe_allow_html=True)

        review_type = st.selectbox(
            "Analysis type",
            [
                "Due Diligence",
                "Financial Health",
                "Investment Memo",
                "Compliance Review",
                "Risk Assessment",
                "Custom Analysis",
            ],
        )
        report_depth = st.selectbox("Report depth", ["Executive", "Standard", "Detailed"], index=1)
        target_pages = st.selectbox("Target report pages", ["10 pages", "40 pages", "80 pages", "120 pages", "Custom"], index=0)
        if target_pages == "Custom":
            custom_pages = st.number_input("Custom target pages", min_value=1, max_value=150, value=15, step=1)
            target_pages_value = f"{int(custom_pages)} pages"
        else:
            target_pages_value = target_pages
        audience = st.selectbox("Audience", ["Investor", "CFO", "Analyst", "Auditor", "Management Team"], index=2)
        prompt_goal = st.selectbox(
            "Prompt engine helper",
            [
                "Auto-generate a professional prompt",
                "Focus on risks and red flags",
                "Focus on financial health",
                "Focus on investment decision",
                "Focus on compliance/audit",
                "I will write my own prompt",
            ],
        )
        suggested_prompt_map = {
            "Auto-generate a professional prompt": f"Prepare a {report_depth.lower()} {review_type.lower()} report of around {target_pages_value} for a {audience.lower()}. Include executive summary, key findings, risks, financial/operational signals, growth opportunities, recommendations, and source citations for every major finding.",
            "Focus on risks and red flags": f"Prepare a risk-focused {review_type.lower()} report of around {target_pages_value} for a {audience.lower()}. Identify red flags, severity, business impact, missing information, and follow-up questions with source citations.",
            "Focus on financial health": f"Prepare a financial health review of around {target_pages_value} for a {audience.lower()}. Focus on revenue, cost, profitability, liquidity, debt, cash-flow indicators, operating signals, and source citations.",
            "Focus on investment decision": f"Prepare an investment memo of around {target_pages_value} for a {audience.lower()}. Cover investment thesis, strengths, risks, diligence questions, and recommendation-oriented insights with citations.",
            "Focus on compliance/audit": f"Prepare a compliance and audit review of around {target_pages_value} for a {audience.lower()}. Cover governance, disclosures, controls, regulatory risks, audit issues, missing information, and source citations.",
            "I will write my own prompt": "",
        }
        user_prompt = st.text_area(
            "Analysis request",
            value=suggested_prompt_map[prompt_goal],
            height=135,
            placeholder="Example: Identify risks, red flags, key findings, and recommended follow-up questions.",
        )
        st.caption("LedgerLens uses a section-wise report engine. Larger page targets generate deeper sections, evidence registers, and longer downloadable reports. Exact page count can vary based on available document evidence and API limits.")

        if st.button("Generate LedgerLens Report"):
            if not user_prompt.strip():
                st.warning("Please enter an analysis request.")
            else:
                mode = "standard"
                if "Risk" in review_type:
                    mode = "risk"
                elif "Compliance" in review_type:
                    mode = "compliance"
                elif "Financial" in review_type:
                    mode = "financial"
                elif "Investment" in review_type:
                    mode = "memo"
                elif "Custom" in review_type:
                    mode = "custom"

                final_question = f"Project: {active_project['project_name']} | Type: {review_type} | Depth: {report_depth} | Target Pages: {target_pages_value} | Audience: {audience} | Request: {user_prompt.strip()}"
                with st.spinner("LedgerLens is generating a section-wise professional report with citations..."):
                    answer, relevant_chunks = generate_sectioned_report(
                        final_question=final_question,
                        all_chunks=all_chunks,
                        index=index,
                        review_type=review_type,
                        report_depth=report_depth,
                        target_pages_value=target_pages_value,
                        audience=audience,
                        mode=mode,
                    )

                report_text = build_txt_report(final_question, answer, relevant_chunks, doc_names)
                report_title = f"{active_project['project_name']} - {review_type}"
                report_id = save_report(user["id"], active_project["id"], report_title, review_type, report_text)

                st.session_state.report_ready = True
                st.session_state.latest_question = final_question
                st.session_state.latest_answer = answer
                st.session_state.latest_sources = relevant_chunks
                st.session_state.latest_doc_names = doc_names
                st.session_state.latest_report_id = report_id
                st.session_state.latest_metrics = {
                    "documents": len(uploaded_files),
                    "pages": total_pages,
                    "risk": risk_label,
                    "evidence": len(relevant_chunks),
                    "review_type": review_type,
                }
                st.session_state.share_summary = "\n".join(generate_summary_points(answer))
                go("report")


def render_report():
    render_nav()
    if not current_user():
        require_login("report")
        return
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
        st.markdown("### Review LedgerLens")
        st.caption("Before downloading, please rate the generated report. This helps improve LedgerLens.")
        rating = st.select_slider("Rate your report experience", options=[1, 2, 3, 4, 5], value=5, format_func=lambda x: "⭐" * x, key="review_rating_top")
        review_text = st.text_area("Write a short review", placeholder="Example: The source citations helped me trust the report.", height=90, key="review_text_top")
        if st.button("Submit Review", key="submit_review_top"):
            save_review(current_user()["id"], st.session_state.get("latest_report_id"), int(rating), review_text)
            st.success("Thank you. Your review was saved in the database.")
        st.markdown("---")
        st.markdown("### Download Report")
        st.download_button("Download PDF Report", data=pdf_bytes, file_name="ledgerlens_due_diligence_report.pdf", mime="application/pdf")
        st.download_button("Download TXT Report", data=report_text, file_name="ledgerlens_due_diligence_report.txt", mime="text/plain")

        st.markdown("### Saved to Workspace")
        rid = st.session_state.get("latest_report_id")
        st.success(f"Report saved in Previous Reports. Report ID: {rid}")
        if st.button("Open Previous Reports"):
            go("reports")


        st.markdown("### Email Delivery")
        recipient_email = st.text_input("Send report to email", value=current_user().get("email", "") if current_user() else "")
        email_summary = f"LedgerLens report generated. Report ID: {rid}. Download the PDF from your LedgerLens workspace.\n\nSummary:\n{st.session_state.get('share_summary', '')[:900]}"
        mail_link = "mailto:" + quote(recipient_email or "") + "?subject=" + quote("LedgerLens Due Diligence Report") + "&body=" + quote(email_summary)
        st.markdown(f'<a class="contact-btn email-btn" href="{mail_link}">Open Email Draft</a>', unsafe_allow_html=True)
        if st.button("Send Email Now"):
            ok, message = send_email_optional(current_user()["id"], recipient_email, "LedgerLens Due Diligence Report", email_summary)
            log_activity(current_user()["id"], f"Email delivery attempted for report #{rid}: {message}")
            if ok:
                st.success("Email sent successfully.")
            else:
                st.warning(message + " Add SMTP_USER and SMTP_PASSWORD secrets to send real email automatically.")
        st.caption("Email works automatically only after SMTP secrets are added in Hugging Face. The Open Email Draft button works without SMTP.")
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


def render_reports():
    render_nav()
    user = current_user()
    if not user:
        require_login("reports")
        return
    st.markdown('<section class="section"><div class="section-title">Previous Reports</div><div class="section-sub">All reports generated from your logged-in workspace are saved here.</div></section>', unsafe_allow_html=True)
    reports = get_reports(user["id"])
    if not reports:
        st.info("No reports generated yet. Create a project and generate your first report from Workspace.")
        if st.button("Go to Workspace"):
            go("workspace")
        return
    for r in reports:
        title = f'{r["report_title"]} — {r["created_at"]}'
        with st.expander(title, expanded=False):
            st.caption(f'Project: {r.get("project_name") or "No project"} | Type: {r["report_type"]}')

            edited_text = st.text_area(
                "Edit saved report",
                value=r["report_text"],
                height=420,
                key=f'edit_report_text_{r["id"]}',
                help="You can edit the saved report text here and save the changes to your workspace history.",
            )

            save_col, dl1_col, dl2_col = st.columns([0.34, 0.33, 0.33])
            with save_col:
                if st.button("Save Edited Report", key=f'save_report_{r["id"]}'):
                    if update_report(r["id"], user["id"], edited_text):
                        st.success("Report updated and saved in your workspace.")
                        st.rerun()
                    else:
                        st.error("Could not update this report. Please login again and retry.")
            with dl1_col:
                st.download_button(
                    "Download Edited TXT",
                    data=edited_text,
                    file_name=f'ledgerlens_report_{r["id"]}_edited.txt',
                    mime="text/plain",
                    key=f'dl_txt_{r["id"]}',
                )
            with dl2_col:
                st.download_button(
                    "Download Edited PDF",
                    data=make_pdf_bytes("LedgerLens Saved Report", edited_text),
                    file_name=f'ledgerlens_report_{r["id"]}_edited.pdf',
                    mime="application/pdf",
                    key=f'dl_pdf_{r["id"]}',
                )

            saved_mail_body = quote(f"LedgerLens saved report: {r['report_title']}\nGenerated: {r['created_at']}\n\nPlease download the PDF from LedgerLens workspace.\n\n{edited_text[:900]}")
            st.markdown(f'<a class="contact-btn email-btn" href="mailto:{quote(user["email"])}?subject={quote("LedgerLens Saved Report")}&body={saved_mail_body}">Email This Report</a>', unsafe_allow_html=True)


def render_account():
    render_nav()
    user = current_user()
    if not user:
        require_login("account")
        return
    stats = get_user_stats(user["id"])
    activity = get_activity(user["id"])
    st.markdown('<section class="section"><div class="section-title">Account</div><div class="section-sub">Your LedgerLens profile, plan, and recent activity.</div></section>', unsafe_allow_html=True)
    c1, c2 = st.columns([0.45, 0.55], gap="large")
    with c1:
        st.markdown(
            f"""
<div class="security-box">
<div class="card-title">Profile</div>
<div class="card-text">
<b>Name:</b> {html.escape(user['name'])}<br>
<b>Email:</b> {html.escape(user['email'])}<br>
<b>Plan:</b> {html.escape(user['plan'])}<br>
<b>Created:</b> {html.escape(user['created_at'])}<br><br>
Passwords are stored using PBKDF2-SHA256 hashing in the demo SQLite database.
</div>
</div>
""",
            unsafe_allow_html=True,
        )
    with c2:
        m1, m2, m3 = st.columns(3)
        with m1:
            st.markdown(f'<div class="metric"><div class="metric-label">Projects</div><div class="metric-value">{stats["projects"]}</div></div>', unsafe_allow_html=True)
        with m2:
            st.markdown(f'<div class="metric"><div class="metric-label">Documents</div><div class="metric-value">{stats["documents"]}</div></div>', unsafe_allow_html=True)
        with m3:
            st.markdown(f'<div class="metric"><div class="metric-label">Reports</div><div class="metric-value">{stats["reports"]}</div></div>', unsafe_allow_html=True)
        st.markdown("### Recent Activity")
        if not activity:
            st.info("No activity yet.")
        for item in activity:
            st.markdown(f'<div class="source"><b>{html.escape(item["action"])}</b><br>{html.escape(item["created_at"])}</div>', unsafe_allow_html=True)


def render_admin():
    render_nav()
    user = current_user()
    if not is_admin(user):
        st.error("Admin access required. Sign in with the admin email to view the database.")
        return

    st.markdown('<section class="section"><div class="section-title">Hidden Admin Backend</div><div class="section-sub">Backend-only database and plan management for LedgerLens. This page is not shown in the public navbar and is accessible only through the hidden admin URL after admin login.</div></section>', unsafe_allow_html=True)

    counts = get_admin_counts()
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.markdown(f'<div class="metric"><div class="metric-label">Users</div><div class="metric-value">{counts["users"]}</div></div>', unsafe_allow_html=True)
    with m2:
        st.markdown(f'<div class="metric"><div class="metric-label">Projects</div><div class="metric-value">{counts["projects"]}</div></div>', unsafe_allow_html=True)
    with m3:
        st.markdown(f'<div class="metric"><div class="metric-label">Reports</div><div class="metric-value">{counts["reports"]}</div></div>', unsafe_allow_html=True)
    with m4:
        st.markdown(f'<div class="metric"><div class="metric-label">Reviews</div><div class="metric-value">{counts["reviews"]}</div></div>', unsafe_allow_html=True)

    st.markdown('<div class="section-title" style="font-size:1.4rem; margin-top:1.3rem;">Manual Plan Activation</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">Use this only as demo/admin activation before integrating Razorpay or Stripe. It updates the user plan and records an admin_manual payment record.</div>', unsafe_allow_html=True)

    user_rows = get_admin_table("users", limit=500)
    if user_rows:
        user_options = {
            f"#{row['id']} — {row['name']} — {row['email']} — current: {row['plan']}": row["id"]
            for row in user_rows
        }
        selected_user_label = st.selectbox("Select user to manage plan", list(user_options.keys()))
        selected_user_id = user_options[selected_user_label]
        selected_plan = st.radio("Set plan", ["Free", "Pro", "Enterprise"], horizontal=True)
        c1, c2 = st.columns([0.25, 0.75])
        with c1:
            if st.button("Activate Selected Plan"):
                ok = update_user_plan(selected_user_id, selected_plan, user.get("email", "admin"))
                if ok:
                    st.success(f"User plan updated to {selected_plan}. A payment/admin activation record was saved.")
                    st.rerun()
                else:
                    st.error("Could not update the selected user plan.")
        with c2:
            st.markdown('<div class="privacy-note"><b>Plan logic:</b> Free = 5 PDFs. Pro ₹99/month = unlimited demo features. Enterprise ₹299/month = unlimited + enterprise label/security positioning. Real payment gateway is not active yet.</div>', unsafe_allow_html=True)
    else:
        st.info("No users found yet. Create a test account first.")

    st.markdown('<div class="section-title" style="font-size:1.4rem; margin-top:1.3rem;">Database Tables</div>', unsafe_allow_html=True)
    table_name = st.selectbox("Select database table", ["users", "login_events", "projects", "documents", "reports", "reviews", "payments", "activity"])
    rows = get_admin_table(table_name, limit=100)
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("No records found in this table yet.")

    st.markdown(
        '<div class="privacy-note"><b>Admin note:</b> This is a demo SQLite backend. On Hugging Face, the database lives inside the running Space environment and may reset after rebuilds unless persistent storage is added. For production, use PostgreSQL/Supabase/Firebase, secure file storage, real payment verification, RBAC, and audit logging.</div>',
        unsafe_allow_html=True,
    )

def render_security():
    render_nav()
    if st.button("← Home"):
        go("home")
    st.markdown(
        """
<section class="section">
<div class="section-title">Security and Private Business Centre.</div>
<div class="section-sub">
LedgerLens public demo is for public or non-confidential files. For real company use, the platform is designed around private workspaces, user-isolated projects, password hashing, audit logs, and private deployment options.
</div>
<div class="security-box">
<div class="grid3">
<div><div class="card-title">Public Demo Mode</div><div class="card-text">Use public annual reports, investor presentations, and non-confidential documents only. The demo focuses on showcasing the workflow and should not be used for restricted company files.</div></div>
<div><div class="card-title">Private Business Centre</div><div class="card-text">Employees sign in to private workspaces. Documents, projects, and reports are isolated by user ID and project ID, so one user cannot access another user's work by default.</div></div>
<div><div class="card-title">Password Hashing</div><div class="card-text">The demo authentication stores password hashes, not raw passwords. Production systems should use stronger managed auth, MFA, and role-based access control.</div></div>
</div>
<br>
<div class="grid3">
<div><div class="card-title">No Model Training</div><div class="card-text">Uploaded files are used for requested analysis only. The intended enterprise policy is: user documents are not used to train AI models.</div></div>
<div><div class="card-title">Retention Control</div><div class="card-text">A company deployment can support auto-delete after analysis, 7-day retention, 30-day retention, or permanent private workspace storage.</div></div>
<div><div class="card-title">Private AI Stack</div><div class="card-text">For confidential use, LedgerLens can be deployed with a private vector database and private LLM endpoint such as a company-hosted model or enterprise cloud model.</div></div>
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
<div class="section-sub">The free demo keeps the core RAG workflow accessible. Pro and Enterprise can be manually activated by admin in this MVP; real payment gateway integration is planned for production.</div>
<div class="grid3">
<div class="pricing popular">
<div class="price-name">Free Demo</div><div class="price">₹0 <span>/ up to 5 PDFs</span></div>
<div class="check">✅ Upload up to five non-confidential PDFs</div>
<div class="check">✅ Ask document questions</div>
<div class="check">✅ Executive due diligence report</div>
<div class="check">✅ Risk and growth review</div>
<div class="check">✅ Source evidence with page numbers</div>
<div class="check">✅ Download PDF report</div>
</div>
<div class="pricing">
<div class="price-name">Pro</div><div class="price">₹99 <span>/ month</span></div>
<div class="check">⭐ More than 5 PDFs at once</div>
<div class="check">⭐ Unlimited report generation</div>
<div class="check">⭐ Branded downloadable reports</div>
<div class="check">⭐ Saved analysis history</div>
<div class="check">⭐ Longer reports and priority processing</div>
</div>
<div class="pricing">
<div class="price-name">Enterprise</div><div class="price">₹299 <span>/ month</span></div>
<div class="check">🏢 Unlimited enterprise workspaces</div>
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




def render_assistant():
    # Removed from navbar/workflow. LedgerLens focuses on professional due diligence reports.
    go("home")


def render_floating_help_panel():
    # Removed in LedgerLens Report Engine edition. Focus stays on professional report generation.
    return


# =========================
# HIDDEN ADMIN BACKEND ACCESS
# =========================
# Admin DB is not visible in the public navbar.
# To open backend viewer, sign in with admin email and open:
# https://sharvarid01-ledgerlens.hf.space/?backend=ledgerlens-admin
try:
    if st.query_params.get("backend") == "ledgerlens-admin":
        st.session_state.page = "admin"
except Exception:
    pass

# =========================
# ROUTER
# =========================
if st.session_state.page == "home":
    render_home()
elif st.session_state.page == "signup":
    render_signup()
elif st.session_state.page == "login":
    render_login()
elif st.session_state.page == "forgot":
    render_forgot()
elif st.session_state.page == "workspace":
    render_workspace()
elif st.session_state.page == "report":
    render_report()
elif st.session_state.page == "reports":
    render_reports()
elif st.session_state.page == "account":
    render_account()
elif st.session_state.page == "admin":
    render_admin()
elif st.session_state.page == "security":
    render_security()
elif st.session_state.page == "plans":
    render_plans()
else:
    render_home()

render_footer()
