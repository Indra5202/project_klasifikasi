import streamlit as st
import pandas as pd
import datetime
import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="ACMIT Paper Review", layout="wide")

# =======================================================
# LOAD SERVICE ACCOUNT & GOOGLE SHEET
# =======================================================
def get_gsheet_client():
    service_info = st.secrets["google_service_account"]
    creds = Credentials.from_service_account_info(
        service_info,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return gspread.authorize(creds)


def load_reviews_from_sheet():
    try:
        gc = get_gsheet_client()
        sh = gc.open_by_key(st.secrets["google_sheet_id"])
        ws = sh.sheet1
        data = ws.get_all_records()
        if not data:
            return pd.DataFrame()
        return pd.DataFrame(data)
    except Exception as e:
        st.error(f"Error loading Google Sheets: {e}")
        return pd.DataFrame()


def append_review_to_sheet(row_dict):
    gc = get_gsheet_client()
    sh = gc.open_by_key(st.secrets["google_sheet_id"])
    ws = sh.sheet1

    # Jika sheet kosong → tulis header dulu
    if len(ws.get_all_values()) == 0:
        ws.append_row(list(row_dict.keys()))

    ws.append_row(list(row_dict.values()))
    return True


# =======================================================
# USER & SESSION MANAGEMENT
# =======================================================
users = {
    "admin": {"password": "admin123", "role": "Admin"},
    "reviewer1": {"password": "rev1", "role": "Reviewer"},
    "reviewer2": {"password": "rev2", "role": "Reviewer"},
}

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "username" not in st.session_state:
    st.session_state.username = None
if "role" not in st.session_state:
    st.session_state.role = None


def login(username, password):
    if username in users and users[username]["password"] == password:
        st.session_state.logged_in = True
        st.session_state.username = username
        st.session_state.role = users[username]["role"]
        return True
    return False


def logout():
    st.session_state.logged_in = False
    st.session_state.username = None
    st.session_state.role = None


# =======================================================
# SIDEBAR LOGIN
# =======================================================
with st.sidebar:
    st.title("Login Reviewer")
    if not st.session_state.logged_in:
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.button("Login"):
            if not login(username, password):
                st.error("Invalid username or password")
    else:
        st.success(f"Logged in as {st.session_state.username} ({st.session_state.role})")
        st.button("Logout", on_click=logout)

# Stop if not logged in
if not st.session_state.logged_in:
    st.stop()

current_user = st.session_state.username
current_role = st.session_state.role

# =======================================================
# HEADER
# =======================================================
st.markdown("""
# <div style="text-align:center;">SWISS GERMAN UNIVERSITY</div>
# <div style="text-align:center; color:#2e6f9e;">Paper Review ACMIT</div>
""", unsafe_allow_html=True)

st.write(f"Logged in as **{current_user}** ({current_role})")

# =======================================================
# REVIEWER PANEL
# =======================================================
if current_role == "Reviewer":

    st.markdown("## 📁 Upload PDF File")
    pdf = st.file_uploader("Upload a PDF", type=["pdf"])

    st.markdown("## ⭐ Reviewer Evaluation Form")

    title = st.text_input("Paper Title")
    student_author = st.text_input("Student Author(s)")
    advisor = st.text_input("Advisor")
    reviewed_by = st.text_input("Reviewed by (Name)")

    st.write("### Format Checks")
    intro = st.selectbox("Introduction correct?", ["1", "0"])
    methods = st.selectbox("Materials & Methods correct?", ["1", "0"])
    results = st.selectbox("Results & Discussion correct?", ["1", "0"])
    conclusion = st.selectbox("Conclusion correct?", ["1", "0"])
    references = st.selectbox("References correct?", ["1", "0"])

    st.write("### Subjective Evaluation")
    english_ok = st.selectbox("English OK?", ["Yes", "No"])
    format_ok = st.selectbox("Format OK?", ["Yes", "No"])
    sota_ok = st.selectbox("SOTA OK?", ["Yes", "No"])
    clarity_ok = st.selectbox("Clarity OK?", ["Yes", "No"])
    figures_ok = st.selectbox("Figures OK?", ["Yes", "No"])
    conclusion_ok = st.selectbox("Conclusion OK?", ["Yes", "No"])
    references_ok = st.selectbox("References OK?", ["Yes", "No"])
    recommendations = st.text_area("Reviewer Recommendations")
    overall_eval = st.selectbox("Overall Evaluation", ["Full acceptance", "Accept with revision"])

    if st.button("Submit Review"):
        if not pdf:
            st.error("PDF is required.")
        else:
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            file_name = pdf.name

            row = {
                "timestamp": now,
                "reviewer_user": current_user,
                "reviewer_role": "Reviewer",
                "file_name": file_name,
                "title": title,
                "student_author": student_author,
                "status": "Compliant" if all(x == "1" for x in [intro, methods, results, conclusion, references]) else "Non-compliant",
                "Introduction": intro,
                "Materials and methods": methods,
                "Results and discussion": results,
                "Conclusion": conclusion,
                "References": references,
                "advisor": advisor,
                "reviewed_by": reviewed_by,
                "english_ok": english_ok,
                "format_ok": format_ok,
                "sota_ok": sota_ok,
                "clarity_ok": clarity_ok,
                "figures_ok": figures_ok,
                "conclusion_ok": conclusion_ok,
                "references_ok": references_ok,
                "recommendations": recommendations,
                "overall_eval": overall_eval,
            }

            append_review_to_sheet(row)
            st.success("Review submitted & saved to Google Sheet.")

# =======================================================
# ADMIN PANEL — FINAL REVIEW SUMMARY
# =======================================================
st.markdown("---")
st.markdown("## 🧪 Final Review Summary (All Sessions)")

df_all = load_reviews_from_sheet()

if df_all.empty:
    st.info("No review data available yet.")
else:
    # Tambah nomor urut
    df_all.insert(0, "No", range(1, len(df_all) + 1))

    # ============================
    # FILTER PANEL
    # ============================
    with st.expander("🔍 Filter & Search", expanded=True):

        reviewers = sorted(df_all["reviewer_user"].dropna().unique())
        statuses = sorted(df_all["status"].dropna().unique())

        if current_role == "Admin":
            sel_reviewer = st.multiselect("Reviewer", reviewers, default=reviewers)
        else:
            sel_reviewer = [current_user]

        sel_status = st.multiselect("Status", statuses, default=statuses)

        keyword = st.text_input("Search (title / author / file name)")

    # Apply filter
    df_view = df_all.copy()

    if sel_reviewer:
        df_view = df_view[df_view["reviewer_user"].isin(sel_reviewer)]
    if sel_status:
        df_view = df_view[df_view["status"].isin(sel_status)]
    if keyword:
        kw = keyword.lower()
        df_view = df_view[
            df_view["file_name"].str.lower().str.contains(kw)
            | df_view["title"].str.lower().str.contains(kw)
            | df_view["student_author"].str.lower().str.contains(kw)
        ]

    if df_view.empty:
        st.warning("No data matches the filter.")
    else:
        # FORMAT FEATURES TABLE
        st.markdown("### 🔹 Format Features")
        format_cols = [
            "No", "file_name", "title", "status",
            "reviewer_user", "reviewer_role",
            "Introduction", "Materials and methods",
            "Results and discussion", "Conclusion", "References"
        ]

        st.dataframe(df_view[format_cols].set_index("No"), use_container_width=True)

        # REVIEW EVALUATION TABLE
        st.markdown("### 🔴 Reviewer Evaluation")
        eval_cols = [
            "No", "file_name", "title", "student_author",
            "advisor", "reviewed_by", "reviewer_user", "reviewer_role",
            "english_ok", "format_ok", "sota_ok", "clarity_ok", "figures_ok",
            "conclusion_ok", "references_ok", "recommendations",
            "overall_eval", "timestamp"
        ]

        st.dataframe(df_view[eval_cols].set_index("No"), use_container_width=True)

        if current_role == "Admin":
            csv = df_all.to_csv(index=False).encode("utf-8")
            st.download_button("💾 Download ALL Reviews (CSV)", csv, "reviews.csv")

# =======================================================
# ANTI REFRESH WARNING
# =======================================================
st.markdown("""
<script>
window.addEventListener('beforeunload', function (e) {
    e.preventDefault();
    e.returnValue = '';
});
</script>
""", unsafe_allow_html=True)
