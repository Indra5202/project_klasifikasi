import io
import re
from datetime import datetime

import pandas as pd
import streamlit as st

# ==== PDF READER (PyPDF2 / pypdf) ====
try:
    from PyPDF2 import PdfReader
except ModuleNotFoundError:
    from pypdf import PdfReader

# ==== GOOGLE SHEETS ====
import gspread
from google.oauth2.service_account import Credentials


# =========================
# KONFIG USER / LOGIN
# =========================

USERS = {
    "admin": {
        "password": "admin123",  # <-- ubah kalau mau
        "role": "admin",
        "full_name": "System Administrator",
    },
    "reviewer1": {
        "password": "reviewer1",  # <-- ubah kalau mau
        "role": "reviewer",
        "full_name": "Reviewer 1",
    },
    "reviewer2": {
        "password": "reviewer2",  # <-- ubah kalau mau
        "role": "reviewer",
        "full_name": "Reviewer 2",
    },
}


def authenticate(username: str, password: str):
    """Return (True, user_info) jika login sukses."""
    user = USERS.get(username)
    if not user:
        return False, None
    if password != user["password"]:
        return False, None
    return True, user


# =========================
# GOOGLE SHEETS HELPERS
# =========================

@st.cache_resource(show_spinner=False)
def get_gsheet_client():
    try:
        sa_info = st.secrets["google_service_account"]
    except Exception as e:
        raise RuntimeError(
            "Config [google_service_account] tidak ditemukan di secrets."
        ) from e

    google_sheet_id = sa_info.get("google_sheet_id") or st.secrets.get(
        "google_sheet_id"
    )
    if not google_sheet_id:
        raise RuntimeError(
            'Key "google_sheet_id" tidak ditemukan di secrets. '
            'Tambahkan di dalam [google_service_account].'
        )

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
    client = gspread.authorize(creds)
    sh = client.open_by_key(google_sheet_id)
    ws = sh.sheet1  # pakai sheet pertama
    return ws


def append_review_to_sheet(row_dict: dict):
    ws = get_gsheet_client()

    # header yang kita pakai (urutan kolom)
    headers = [
        "timestamp",
        "reviewer_user",
        "reviewer_role",
        "file_name",
        "title",
        "student_author",
        "status",
        "Introduction",
        "Materials and methods",
        "Results and discussion",
        "Conclusion",
        "References",
        "advisor",
        "reviewed_by",
        "english_ok",
        "english_issue",
        "format_ok",
        "format_comment",
        "sota_ok",
        "clarity_ok",
        "figures_ok",
        "figures_comment",
        "conclusion_ok",
        "conclusion_comment",
        "references_ok",
        "recommendations",
        "overall_eval",
    ]

    # cek apakah sheet kosong (belum ada header)
    existing = ws.get_all_values()
    if not existing:
        ws.append_row(headers)

    values = [row_dict.get(h, "") for h in headers]
    ws.append_row(values)


def load_all_reviews_from_sheet() -> pd.DataFrame:
    try:
        ws = get_gsheet_client()
        data = ws.get_all_records()
        if not data:
            return pd.DataFrame()
        return pd.DataFrame(data)
    except Exception as e:
        st.error(f"Error loading Google Sheets: {e}")
        return pd.DataFrame()


# =========================
# PDF & FORMAT CHECK
# =========================

def extract_text_from_pdf(uploaded_file) -> str:
    """Ambil semua text dari PDF dengan PyPDF2/pypdf."""
    if uploaded_file is None:
        return ""

    pdf_bytes = uploaded_file.read()
    reader = PdfReader(io.BytesIO(pdf_bytes))
    texts = []
    for page in reader.pages:
        try:
            texts.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n".join(texts)


def parse_title_author(pdf_text: str):
    """
    Heuristik simple:
    - Baris tidak kosong pertama = title
    - Baris-baris berikutnya sampai ketemu 'Abstract' / baris kosong = author
    """
    lines = [l.strip() for l in pdf_text.splitlines()]
    lines = [l for l in lines if l]  # buang yang kosong

    if not lines:
        return "", ""

    title = lines[0]
    author_lines = []
    for line in lines[1:]:
        if re.search(r"abstract", line, re.IGNORECASE):
            break
        # jika mengandung kata 'department', 'university' kemungkinan sudah affiliation
        if re.search(r"department|university|faculty", line, re.IGNORECASE):
            break
        author_lines.append(line)

    authors = " ".join(author_lines)
    return title, authors


def check_format_sections(pdf_text: str):
    """
    Cek keberadaan section utama (rule-based, bukan ML).
    Return dict {nama_section: 0/1}
    """
    sections = {
        "Introduction": ["introduction"],
        "Materials and methods": ["materials and methods", "methodology", "methods"],
        "Results and discussion": ["results and discussion", "results", "discussion"],
        "Conclusion": ["conclusion", "conclusions"],
        "References": ["references", "bibliography"],
    }

    text_lower = pdf_text.lower()
    result = {}
    for section_name, keywords in sections.items():
        found = any(kw in text_lower for kw in keywords)
        result[section_name] = 1 if found else 0
    return result


# =========================
# UI: LOGIN SIDEBAR
# =========================

def login_sidebar():
    st.sidebar.header("Login Reviewer")

    if "logged_in" not in st.session_state:
        st.session_state["logged_in"] = False
        st.session_state["user"] = None

    if st.session_state["logged_in"] and st.session_state["user"]:
        user = st.session_state["user"]
        st.sidebar.success(
            f"Logged in as {user['username']} ({user['role'].title()})"
        )

        if st.sidebar.button("Logout"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]

            # rerun aman untuk Streamlit versi baru
            if hasattr(st, "experimental_rerun"):
                st.experimental_rerun()
            else:
                st.rerun()
        return

    # belum login -> tampilkan form
    username = st.sidebar.text_input("Username")
    password = st.sidebar.text_input("Password", type="password")
    login_btn = st.sidebar.button("Login")

    if login_btn:
        ok, user = authenticate(username.strip(), password)
        if ok:
            st.session_state["logged_in"] = True
            st.session_state["user"] = {
                "username": username.strip(),
                "role": user["role"],
                "full_name": user["full_name"],
            }
            st.sidebar.success(
                f"Logged in as {username.strip()} ({user['role'].title()})"
            )
            if hasattr(st, "experimental_rerun"):
                st.experimental_rerun()
            else:
                st.rerun()
        else:
            st.sidebar.error("Invalid username or password.")


# =========================
# UI: REVIEWER VIEW
# =========================

def reviewer_view(user_info):
    st.subheader("Upload PDF File")

    uploaded_file = st.file_uploader(
        "Upload one paper PDF and let the app automatically check format structure "
        "compliance (rule-based, without ML).",
        type=["pdf"],
    )

    if uploaded_file is None:
        st.info("Silakan upload file PDF terlebih dahulu.")
        return

    pdf_text = extract_text_from_pdf(uploaded_file)
    if not pdf_text.strip():
        st.error("Gagal membaca teks dari PDF.")
        return

    title, authors = parse_title_author(pdf_text)
    sections_ok = check_format_sections(pdf_text)

    # Tampilkan fitur format
    st.markdown("### 📄 Format Features")
    format_row = {
        "file_name": uploaded_file.name,
        "title": title,
        "student_author": authors,
    }
    format_row.update(sections_ok)
    df_format = pd.DataFrame([format_row])
    st.dataframe(df_format, use_container_width=True)

    status = (
        "Compliant" if all(v == 1 for v in sections_ok.values()) else "Non-compliant"
    )
    st.success(f"Analysis complete (rule-based). Format is **{status.upper()}**.")

    # ================= REVIEW FORM =================
    st.markdown("### 📝 Reviewer Evaluation")

    with st.form("review_form"):
        advisor = st.text_input("Advisor:")
        reviewer_name = st.text_input("Reviewer name:")

        st.markdown("**Is the manuscript written in proper and sound English?**")
        english_ok = st.radio(
            "English OK?", ["Yes", "No"], horizontal=True, key="english_ok_radio"
        )
        english_issue = st.text_area("If no, describe the main issues:", "")

        st.markdown("**Format follows author guideline?**")
        format_ok = st.radio(
            "Format OK?", ["Yes", "No"], horizontal=True, key="format_ok_radio"
        )
        format_comment = st.text_area("Format comments:")

        st.markdown("**Is the problem state-of-the-art?**")
        sota_ok = st.radio(
            "SOTA OK?", ["Yes", "No"], horizontal=True, key="sota_ok_radio"
        )

        st.markdown("**Is the problem clearly stated?**")
        clarity_ok = st.radio(
            "Clarity OK?", ["Yes", "No"], horizontal=True, key="clarity_ok_radio"
        )

        st.markdown("**Do figures/tables support the goal/result?**")
        figures_ok = st.radio(
            "Figures OK?", ["Yes", "No"], horizontal=True, key="figures_ok_radio"
        )
        figures_comment = st.text_area("Figures comments:")

        st.markdown("**Does the conclusion answer the problem?**")
        conclusion_ok = st.radio(
            "Conclusion OK?", ["Yes", "No"], horizontal=True, key="conclusion_ok_radio"
        )
        conclusion_comment = st.text_area("Conclusion comments:")

        st.markdown("**Are references up-to-date?**")
        references_ok = st.radio(
            "References OK?", ["Yes", "No"], horizontal=True, key="references_ok_radio"
        )

        recommendations = st.text_area("Recommendations:")
        overall_eval = st.selectbox(
            "Overall Evaluation:",
            [
                "Full acceptance",
                "Accept with revision",
                "Major revision",
                "Reject",
            ],
        )

        submitted = st.form_submit_button("Submit Review")

    if submitted:
        try:
            row = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "reviewer_user": user_info["username"],
                "reviewer_role": user_info["role"].title(),
                "file_name": uploaded_file.name,
                "title": title,
                "student_author": authors,
                "status": status,
                "Introduction": sections_ok.get("Introduction", 0),
                "Materials and methods": sections_ok.get("Materials and methods", 0),
                "Results and discussion": sections_ok.get(
                    "Results and discussion", 0
                ),
                "Conclusion": sections_ok.get("Conclusion", 0),
                "References": sections_ok.get("References", 0),
                "advisor": advisor,
                "reviewed_by": reviewer_name,
                "english_ok": english_ok,
                "english_issue": english_issue,
                "format_ok": format_ok,
                "format_comment": format_comment,
                "sota_ok": sota_ok,
                "clarity_ok": clarity_ok,
                "figures_ok": figures_ok,
                "figures_comment": figures_comment,
                "conclusion_ok": conclusion_ok,
                "conclusion_comment": conclusion_comment,
                "references_ok": references_ok,
                "recommendations": recommendations,
                "overall_eval": overall_eval,
            }

            append_review_to_sheet(row)
            st.success("✅ Review submitted & saved to central Google Sheet.")

        except Exception as e:
            st.error(f"Error saat menyimpan ke Google Sheets: {e}")


# =========================
# UI: ADMIN VIEW
# =========================

def admin_view(user_info):
    st.markdown(
        "_You are logged in as Admin. Admin can view and download all reviews but "
        "cannot upload new papers or submit reviews._"
    )

    df = load_all_reviews_from_sheet()
    if df.empty:
        st.info("No review data available yet.")
        return

    st.markdown("### 📊 Final Review Summary (All Sessions)")
    st.dataframe(df, use_container_width=True)

    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️ Download All Review Summary as CSV (Admin only)",
        data=csv,
        file_name="acmit_reviews_summary.csv",
        mime="text/csv",
    )


# =========================
# MAIN
# =========================

def main():
    st.set_page_config(
        page_title="Paper Review ACMIT",
        layout="wide",
    )

    st.title("SWISS GERMAN UNIVERSITY")
    st.header("Paper Review ACMIT")

    login_sidebar()

    if not st.session_state.get("logged_in") or not st.session_state.get("user"):
        st.info("Silakan login terlebih dahulu untuk menggunakan aplikasi.")
        return

    user_info = st.session_state["user"]

    if user_info["role"] == "admin":
        admin_view(user_info)
    else:
        reviewer_view(user_info)


if __name__ == "__main__":
    main()
