import io
import re
from datetime import datetime

import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials
from pypdf import PdfReader
import gspread

# ------------------------------------------------------
#  CONFIG
# ------------------------------------------------------
st.set_page_config(
    page_title="Paper Review ACMIT",
    layout="wide",
)

# Hard-coded users (silakan sesuaikan)
USERS = {
    "admin": {"password": "admin", "role": "admin"},
    "reviewer1": {"password": "reviewer1", "role": "reviewer"},
    "reviewer2": {"password": "reviewer2", "role": "reviewer"},
}

# Kolom yang akan digunakan di Google Sheets (urutan fix)
REVIEW_COLUMNS = [
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


# ------------------------------------------------------
#  GOOGLE SHEETS HELPERS
# ------------------------------------------------------
@st.cache_resource
def get_gsheet_client():
    """Buat client gspread dari st.secrets."""
    try:
        sa_info = st.secrets["google_service_account"]
    except Exception:
        st.error(
            "Google service account credential tidak ditemukan di `st.secrets['google_service_account']`."
        )
        st.stop()

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
    client = gspread.authorize(creds)
    return client


def get_reviews_worksheet():
    """Ambil worksheet untuk menyimpan review + pastikan header ada."""
    client = get_gsheet_client()
    try:
        sheet_id = st.secrets["google_service_account"]["google_sheet_id"]
    except KeyError:
        st.error(
            "Error loading Google Sheets: `google_sheet_id` tidak ditemukan di secrets. "
            "Tambahkan `google_sheet_id` di dalam [google_service_account] pada secrets."
        )
        st.stop()

    sh = client.open_by_key(sheet_id)
    ws = sh.sheet1  # gunakan sheet pertama

    # Pastikan header
    existing_header = ws.row_values(1)
    if not existing_header:
        ws.append_row(REVIEW_COLUMNS)
    return ws


def append_review_row(row_dict):
    """Append satu baris review ke Google Sheet."""
    ws = get_reviews_worksheet()

    # Pastikan header di baris pertama sesuai REVIEW_COLUMNS
    existing_header = ws.row_values(1)
    if existing_header != REVIEW_COLUMNS:
        # Kosongkan sheet & tulis header ulang (opsi sederhana)
        ws.clear()
        ws.append_row(REVIEW_COLUMNS)

    row = [row_dict.get(col, "") for col in REVIEW_COLUMNS]
    ws.append_row(row, value_input_option="USER_ENTERED")


def load_all_reviews_df():
    """Load seluruh review dari Google Sheets sebagai DataFrame."""
    ws = get_reviews_worksheet()
    records = ws.get_all_records()
    if not records:
        return pd.DataFrame(columns=REVIEW_COLUMNS)
    df = pd.DataFrame(records)
    # Pastikan semua kolom ada
    for col in REVIEW_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[REVIEW_COLUMNS]


# ------------------------------------------------------
#  PDF ANALYSIS (FORMAT CHECK)
# ------------------------------------------------------
SECTION_PATTERNS = {
    "Introduction": [r"\bintroduction\b"],
    "Materials and methods": [
        r"\bmaterials?\s+and\s+methods?\b",
        r"\bmethodolog(y|ies)\b",
        r"\bmaterials?\b",
    ],
    "Results and discussion": [
        r"\bresults?\s+and\s+discussion\b",
        r"\bresults?\b",
        r"\bdiscussion\b",
    ],
    "Conclusion": [r"\bconclusion(s)?\b", r"\bconcluding\s+remarks\b"],
    "References": [r"\breferences\b", r"\bbibliography\b"],
}


def extract_text_from_pdf(uploaded_file) -> str:
    """Ekstrak teks dari semua halaman PDF."""
    reader = PdfReader(uploaded_file)
    texts = []
    for page in reader.pages:
        t = page.extract_text() or ""
        texts.append(t)
    return "\n".join(texts)


def guess_title_and_author(first_page_text: str):
    """Heuristik sederhana untuk menebak judul & penulis dari halaman pertama."""
    lines = [ln.strip() for ln in first_page_text.splitlines() if ln.strip()]
    title = lines[0] if lines else ""
    student_author = lines[1] if len(lines) > 1 else ""
    return title, student_author


def analyze_pdf(uploaded_file):
    """Analisis format outline paper."""
    # Simpan ke buffer supaya bisa dibaca dua kali jika perlu
    data = uploaded_file.read()
    bio = io.BytesIO(data)
    reader = PdfReader(bio)

    # Teks semua halaman
    full_text_pages = []
    for page in reader.pages:
        full_text_pages.append(page.extract_text() or "")
    full_text = "\n".join(full_text_pages)

    # Halaman pertama untuk judul & author
    first_page_text = full_text_pages[0] if full_text_pages else ""
    title, student_author = guess_title_and_author(first_page_text)

    # Cek keberadaan section
    section_flags = {}
    for section, patterns in SECTION_PATTERNS.items():
        found = False
        for pat in patterns:
            if re.search(pat, full_text, flags=re.IGNORECASE):
                found = True
                break
        section_flags[section] = 1 if found else 0

    # Status compliant jika semua section utama ada
    required_sections = [
        "Introduction",
        "Materials and methods",
        "Results and discussion",
        "Conclusion",
        "References",
    ]
    compliant = all(section_flags.get(sec, 0) == 1 for sec in required_sections)
    status = "Compliant" if compliant else "Non-compliant"

    result = {
        "file_name": uploaded_file.name,
        "title": title,
        "student_author": student_author,
        "status": status,
    }
    result.update(section_flags)
    return result


# ------------------------------------------------------
#  AUTH / LOGIN
# ------------------------------------------------------
def init_session_state():
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
        st.session_state.username = None
        st.session_state.role = None
    if "current_analysis" not in st.session_state:
        st.session_state.current_analysis = None


def login_sidebar():
    st.sidebar.title("Login Reviewer")

    if st.session_state.logged_in:
        st.sidebar.success(
            f"Logged in as {st.session_state.username} ({st.session_state.role.capitalize()})"
        )
        if st.sidebar.button("Logout"):
            st.session_state.logged_in = False
            st.session_state.username = None
            st.session_state.role = None
            st.session_state.current_analysis = None
            st.experimental_rerun()
        return

    username = st.sidebar.text_input("Username", key="login_username")
    password = st.sidebar.text_input(
        "Password", type="password", key="login_password"
    )

    if st.sidebar.button("Login"):
        user = USERS.get(username)
        if user and user["password"] == password:
            st.session_state.logged_in = True
            st.session_state.username = username
            st.session_state.role = user["role"]
            st.sidebar.success("Login berhasil.")
            st.experimental_rerun()
        else:
            st.sidebar.error("Invalid username or password.")


# ------------------------------------------------------
#  VIEW UNTUK REVIEWER
# ------------------------------------------------------
def reviewer_view():
    st.header("Upload PDF File")

    uploaded_file = st.file_uploader(
        "Upload a PDF", type=["pdf"], accept_multiple_files=False
    )

    analysis = None
    if uploaded_file is not None:
        with st.spinner("Menganalisis format paper..."):
            analysis = analyze_pdf(uploaded_file)
            st.session_state.current_analysis = analysis

        st.success("Analysis complete (rule-based). Format status:")
        st.write(f"**{analysis['status'].upper()}**")

        # Tampilkan format features
        st.subheader("Format Features")
        df_format = pd.DataFrame(
            [
                {
                    "file_name": analysis["file_name"],
                    "title": analysis["title"],
                    "student_author": analysis["student_author"],
                    "Introduction": analysis.get("Introduction", 0),
                    "Materials and methods": analysis.get("Materials and methods", 0),
                    "Results and discussion": analysis.get(
                        "Results and discussion", 0
                    ),
                    "Conclusion": analysis.get("Conclusion", 0),
                    "References": analysis.get("References", 0),
                    "status": analysis["status"],
                }
            ]
        )
        st.dataframe(df_format, use_container_width=True)

    # --- Reviewer evaluation form ---
    st.subheader("Reviewer Evaluation")

    if st.session_state.current_analysis is None:
        st.info("Silakan upload dan analisis satu paper terlebih dahulu.")
        return

    analysis = st.session_state.current_analysis

    with st.form("review_form"):
        advisor = st.text_input("Advisor:")
        reviewer_name = st.text_input("Reviewer name:")

        st.markdown("**Is the manuscript written in proper and sound English?**")
        english_ok = st.radio(
            "English OK?",
            ["Yes", "No"],
            index=None,  # <-- tidak auto pilih
            horizontal=True,
            key="english_ok_radio",
        )
        english_issue = st.text_area("If no, describe the main issues:", "")

        st.markdown("**Format follows author guideline?**")
        format_ok = st.radio(
            "Format OK?",
            ["Yes", "No"],
            index=None,
            horizontal=True,
            key="format_ok_radio",
        )
        format_comment = st.text_area("Format comments:")

        st.markdown("**Is the problem state-of-the-art?**")
        sota_ok = st.radio(
            "State-of-the-art OK?",
            ["Yes", "No"],
            index=None,
            horizontal=True,
            key="sota_ok_radio",
        )

        st.markdown("**Is the problem clearly stated?**")
        clarity_ok = st.radio(
            "Clarity OK?",
            ["Yes", "No"],
            index=None,
            horizontal=True,
            key="clarity_ok_radio",
        )

        st.markdown("**Do figures/tables support the goal/result?**")
        figures_ok = st.radio(
            "Figures OK?",
            ["Yes", "No"],
            index=None,
            horizontal=True,
            key="figures_ok_radio",
        )
        figures_comment = st.text_area("Figures comments:")

        st.markdown("**Does the conclusion answer the problem?**")
        conclusion_ok = st.radio(
            "Conclusion OK?",
            ["Yes", "No"],
            index=None,
            horizontal=True,
            key="conclusion_ok_radio",
        )
        conclusion_comment = st.text_area("Conclusion comments:")

        st.markdown("**Are references up-to-date?**")
        references_ok = st.radio(
            "References OK?",
            ["Yes", "No"],
            index=None,
            horizontal=True,
            key="references_ok_radio",
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
        # Optional: validasi sederhana – kalau ada radio yang belum dipilih
        radio_values = [
            english_ok,
            format_ok,
            sota_ok,
            clarity_ok,
            figures_ok,
            conclusion_ok,
            references_ok,
        ]
        if any(v is None for v in radio_values):
            st.error(
                "Harap isi semua pertanyaan Yes/No sebelum submit review."
            )
            return

        row = {
            "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "reviewer_user": st.session_state.username,
            "reviewer_role": "Reviewer",
            "file_name": analysis["file_name"],
            "title": analysis["title"],
            "student_author": analysis["student_author"],
            "status": analysis["status"],
            "Introduction": analysis.get("Introduction", 0),
            "Materials and methods": analysis.get("Materials and methods", 0),
            "Results and discussion": analysis.get("Results and discussion", 0),
            "Conclusion": analysis.get("Conclusion", 0),
            "References": analysis.get("References", 0),
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

        try:
            append_review_row(row)
            st.success("Review submitted & saved to central Google Sheet.")
        except Exception as e:
            st.error(f"Gagal menyimpan ke Google Sheets: {e}")
            return


# ------------------------------------------------------
#  VIEW UNTUK ADMIN
# ------------------------------------------------------
def admin_view():
    st.subheader("Final Review Summary (All Sessions)")

    try:
        df = load_all_reviews_df()
    except Exception as e:
        st.error(f"Error loading Google Sheets: {e}")
        return

    if df.empty:
        st.info("No review data available yet.")
        return

    st.dataframe(df, use_container_width=True)

    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download All Review Summary as CSV (Admin only)",
        data=csv,
        file_name="acmit_review_summary.csv",
        mime="text/csv",
    )


# ------------------------------------------------------
#  MAIN
# ------------------------------------------------------
def main():
    init_session_state()
    login_sidebar()

    st.title("SWISS GERMAN UNIVERSITY")
    st.header("Paper Review ACMIT")

    if not st.session_state.logged_in:
        st.info("Silakan login terlebih dahulu untuk menggunakan aplikasi.")
        return

    role = st.session_state.role

    if role == "reviewer":
        reviewer_view()
    elif role == "admin":
        admin_view()
    else:
        st.error("Role tidak dikenali.")


if __name__ == "__main__":
    main()
