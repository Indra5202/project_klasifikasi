import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

st.set_page_config(page_title="Paper Review ACMIT", layout="wide")

# ======================================================================
# 1. GOOGLE SHEETS CONNECTION
# ======================================================================
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
        sheet_id = st.secrets["google_sheet_id"]
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
        sheet_id = st.secrets["google_sheet_id"]
        sh = gc.open_by_key(sheet_id)
        worksheet = sh.sheet1

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
    "reviewer3": {"password": "reviewer123", "role": "Reviewer"},
}

def login():
    st.sidebar.title("Login Reviewer")

    if "user" not in st.session_state:
        st.session_state.user = None

    if st.session_state.user:
        st.sidebar.success(f"Logged in as {st.session_state.user} ({USERS[st.session_state.user]['role']})")
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

ROLE = USERS[st.session_state.user]["role"]
USER = st.session_state.user

st.title("SWISS GERMAN UNIVERSITY")
st.header("Paper Review ACMIT")

st.write(f"Logged in as **{USER}** ({ROLE})")

# ======================================================================
# 3. REVIEW FORM FOR REVIEWER
# ======================================================================
if ROLE == "Reviewer":
    st.subheader("📤 Upload PDF File")

    uploaded = st.file_uploader("Upload one PDF", type=["pdf"])
    if uploaded:
        st.success("PDF uploaded. Fill the review form below.")

        st.subheader("📝 Review Form")

        advisor = st.text_input("Advisor name")
        reviewer_name = st.text_input("Reviewed by")
        english_ok = st.selectbox("English OK?", ["Yes", "No"])
        english_issue = st.text_input("English issue (if any)")
        format_ok = st.selectbox("Format OK?", ["Yes", "No"])
        format_comment = st.text_input("Format comment")
        sota_ok = st.selectbox("State of the Art OK?", ["Yes", "No"])
        clarity_ok = st.selectbox("Clarity OK?", ["Yes", "No"])
        figures_ok = st.selectbox("Figures OK?", ["Yes", "No"])
        conclusion_ok = st.selectbox("Conclusion OK?", ["Yes", "No"])
        conclusion_comment = st.text_input("Conclusion comments")
        references_ok = st.selectbox("References OK?", ["Yes", "No"])
        recommendations = st.text_area("Recommendations")
        overall_eval = st.selectbox("Overall Evaluation", ["Accept", "Accept with revision", "Reject"])

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

            success = append_review_to_sheet(row)

            if success:
                st.success("Review submitted & saved to Google Sheets!")
            else:
                st.error("Failed to save review.")

# ======================================================================
# 4. ADMIN VIEW — SEE ALL REVIEWS
# ======================================================================
if ROLE == "Admin":
    st.subheader("📊 Final Review Summary (All Sessions)")

    df = load_reviews_from_sheet()

    if df.empty:
        st.info("No review data available yet.")
    else:
        st.dataframe(df, use_container_width=True)

        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button("📥 Download All Review Summary (CSV)", csv, "reviews.csv", "text/csv")
