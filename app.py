import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

st.set_page_config(page_title="Paper Review ACMIT", layout="wide")

# ======================================================================
# 1. GOOGLE SHEETS CONNECTION
# ======================================================================

def get_sheet_id() -> str:
    """
    Ambil google_sheet_id dari secrets.
    - Coba dulu di root: st.secrets["google_sheet_id"]
    - Kalau tidak ada, coba di dalam blok google_service_account:
      st.secrets["google_service_account"]["google_sheet_id"]
    """
    # 1) coba di root
    if "google_sheet_id" in st.secrets:
        return st.secrets["google_sheet_id"]

    # 2) coba di dalam blok google_service_account
    if "google_service_account" in st.secrets:
        svc = st.secrets["google_service_account"]
        if isinstance(svc, dict) and "google_sheet_id" in svc:
            return svc["google_sheet_id"]

    # Kalau dua-duanya tidak ada, lempar error yang jelas
    raise KeyError(
        'google_sheet_id tidak ditemukan di secrets. '
        'Tambahkan "google_sheet_id" di root atau di dalam [google_service_account].'
    )


def get_gsheet_client():
    """Authorize Google Sheets using Service Account from st.secrets."""
    service_info = st.secrets["google_service_account"]
    creds = Credentials.from_service_account_info(
        service_info,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return gspread.authorize(creds)


def load_reviews_from_sheet():
    """Load all review rows from Google Sheets."""
    try:
        gc = get_gsheet_client()
        sheet_id = get_sheet_id()
        sh = gc.open_by_key(sheet_id)
        worksheet = sh.sheet1
        rows = worksheet.get_all_records()
        return pd.DataFrame(rows)
    except Exception as e:
        st.error(f"Error loading Google Sheets: {e}")
        return pd.DataFrame()


def append_review_to_sheet(row_dict):
    """Append one review row into Google Sheets."""
    try:
        gc = get_gsheet_client()
        sheet_id = get_sheet_id()
        sh = gc.open_by_key(sheet_id)
        worksheet = sh.sheet1

        # Jika sheet masih kosong (tanpa header), tulis header dulu
        if len(worksheet.get_all_values()) == 0:
            worksheet.append_row(list(row_dict.keys()))

        worksheet.append_row(list(row_dict.values()))
        return True
    except Exception as e:
        st.error(f"Error saving review to Google Sheets: {e}")
        return False

# ======================================================================
# 2. LOGIN SYSTEM
# ======================================================================

USERS = {
    "admin": {"password": "admin123", "role": "Admin"},
    "reviewer1": {"password": "reviewer123", "role": "Reviewer"},
    "reviewer2": {"password": "reviewer123", "role": "Reviewer"},
}


def login():
    st.sidebar.title("Login Reviewer")

    if "user" not in st.session_state:
        st.session_state.user = None

    if st.session_state.user:
        role = USERS[st.session_state.user]["role"]
        st.sidebar.success(f"Logged in as {st.session_state.user} ({role})")
        if st.sidebar.button("Logout"):
            st.session_state.user = None
            st.rerun()
        return

    username = st.sidebar.text_input("Username")
    password = st.sidebar.text_input("Password", type="password")
    if st.sidebar.button("Login"):
        if username in USERS and USERS[username]["password"] == password:
            st.session_state.user = username
            st.sidebar.success("Login successful!")
            st.rerun()
        else:
            st.sidebar.error("Invalid username or password")


login()

if not st.session_state.user:
    st.stop()

USER = st.session_state.user
ROLE = USERS[USER]["role"]

# ======================================================================
# 3. UI HEADER
# ======================================================================

st.markdown(
    """
    <h1 style="text-align:center;">SWISS GERMAN UNIVERSITY</h1>
    <h2 style="text-align:center; color:#2e6f9e;">Paper Review ACMIT</h2>
    """,
    unsafe_allow_html=True,
)

st.write(f"Logged in as **{USER}** ({ROLE})")

# ======================================================================
# 4. REVIEW FORM UNTUK REVIEWER
# ======================================================================

if ROLE == "Reviewer":
    st.subheader("📤 Upload PDF File")

    uploaded = st.file_uploader("Upload one PDF", type=["pdf"])

    if uploaded:
        st.success("PDF uploaded. Fill the review form below.")

        st.subheader("📝 Review Form")

        advisor = st.text_input("Advisor name")
        reviewer_name = st.text_input("Reviewed by (Name)")
        english_ok = st.selectbox("Is the English proper?", ["Yes", "No"])
        english_issue = st.text_input("English issue (if any)")
        format_ok = st.selectbox("Format follows guideline?", ["Yes", "No"])
        format_comment = st.text_input("Format comment")
        sota_ok = st.selectbox("Is the problem state-of-the-art?", ["Yes", "No"])
        clarity_ok = st.selectbox("Is the problem clearly stated?", ["Yes", "No"])
        figures_ok = st.selectbox("Do figures/tables support the goal/result?", ["Yes", "No"])
        conclusion_ok = st.selectbox("Does the conclusion answer the problem?", ["Yes", "No"])
        conclusion_comment = st.text_input("Conclusion comment")
        references_ok = st.selectbox("Are references up-to-date?", ["Yes", "No"])
        recommendations = st.text_area("Recommendations")
        overall_eval = st.selectbox(
            "Overall Evaluation",
            ["Full acceptance", "Accept with revision", "Reject"],
        )

        if st.button("Submit Review"):
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            row = {
                "timestamp": timestamp,
                "reviewer_user": USER,
                "reviewer_role": ROLE,
                "file_name": uploaded.name,
                "advisor": advisor,
                "reviewed_by": reviewer_name,
                "english_ok": english_ok,
                "english_issue": english_issue,
                "format_ok": format_ok,
                "format_comment": format_comment,
                "sota_ok": sota_ok,
                "clarity_ok": clarity_ok,
                "figures_ok": figures_ok,
                "conclusion_ok": conclusion_ok,
                "conclusion_comment": conclusion_comment,
                "references_ok": references_ok,
                "recommendations": recommendations,
                "overall_eval": overall_eval,
            }

            if append_review_to_sheet(row):
                st.success("Review submitted & saved to Google Sheets!")

# ======================================================================
# 5. ADMIN VIEW – FINAL SUMMARY
# ======================================================================

if ROLE == "Admin":
    st.subheader("📊 Final Review Summary (All Sessions)")

    df = load_reviews_from_sheet()

    if df.empty:
        st.info("No review data available yet.")
    else:
        # Tambah nomor urut biar rapi
        df.insert(0, "No", range(1, len(df) + 1))

        st.dataframe(df, use_container_width=True)

        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "📥 Download All Review Summary (CSV)",
            csv,
            "reviews_summary.csv",
            "text/csv",
        )
