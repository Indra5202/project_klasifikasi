import streamlit as st
import pandas as pd
from datetime import datetime
from io import BytesIO
from typing import Dict, Any

from PyPDF2 import PdfReader
import gspread
from google.oauth2.service_account import Credentials


# ---------- Simple user database ----------
USERS: Dict[str, Dict[str, str]] = {
    "admin": {"password": "admin", "role": "admin"},
    "reviewer1": {"password": "reviewer1", "role": "reviewer"},
    "reviewer2": {"password": "reviewer2", "role": "reviewer"},
}

# Kolom yang disimpan di Google Sheets (urutan penting)
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
    "conclusion_ok",
    "references_ok",
    "recommendations",
    "overall_eval",
]

# Kata kunci sederhana untuk deteksi section
SECTION_KEYWORDS = {
    "Introduction": ["introduction"],
    "Materials and methods": [
        "materials and methods",
        "materials & methods",
        "methodology",
        "methods",
    ],
    "Results and discussion": [
        "results and discussion",
        "results & discussion",
        "results",
        "discussion",
    ],
    "Conclusion": ["conclusion", "concluding remarks", "conclusions"],
    "References": ["references", "bibliography"],
}


# ---------- Google Sheets helpers ----------

@st.cache_resource
def get_worksheet():
    """Authorize sekali, lalu kembalikan worksheet pertama dari spreadsheet yang dikonfigurasi."""
    try:
        service_info = st.secrets["google_service_account"]
    except Exception:
        st.error(
            "Konfigurasi Google Service Account belum ditemukan di `st.secrets` "
            "dengan key `[google_service_account]`."
        )
        raise

    if "google_sheet_id" not in service_info:
        st.error(
            'Key `"google_sheet_id"` tidak ditemukan di secrets. '
            "Tambahkan ke dalam blok `[google_service_account]`."
        )
        raise KeyError("google_sheet_id missing in secrets")

    sheet_id = service_info["google_sheet_id"]

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(service_info, scopes=scopes)
    client = gspread.authorize(creds)
    sh = client.open_by_key(sheet_id)
    ws = sh.sheet1

    # Pastikan header sudah ada
    values = ws.get_all_values()
    if not values:
        ws.append_row(REVIEW_COLUMNS)

    return ws


def load_reviews_df() -> pd.DataFrame:
    ws = get_worksheet()
    rows = ws.get_all_records()  # list of dict
    if not rows:
        return pd.DataFrame(columns=REVIEW_COLUMNS)
    return pd.DataFrame(rows)


def append_review_row(row_dict: Dict[str, Any]):
    ws = get_worksheet()
    row = [row_dict.get(col, "") for col in REVIEW_COLUMNS]
    ws.append_row(row)


# ---------- PDF helpers ----------

def extract_text_from_pdf(uploaded_file) -> Dict[str, Any]:
    """Return full text (lowercase) dan list baris halaman pertama."""
    file_bytes = uploaded_file.getvalue()
    reader = PdfReader(BytesIO(file_bytes))

    pages = []
    for page in reader.pages:
        try:
            txt = page.extract_text() or ""
        except Exception:
            txt = ""
        pages.append(txt)

    full_text = "\n".join(pages).lower()
    first_page_lines = (pages[0] or "").splitlines() if pages else []

    return {"full_text": full_text, "first_page_lines": first_page_lines}


def guess_title_and_authors(first_page_lines):
    title = ""
    authors = ""
    for line in first_page_lines:
        clean = line.strip()
        if not clean:
            continue
        lower = clean.lower()
        if not title:
            title = clean
            continue
        if "abstract" in lower:
            break
        if not authors:
            authors = clean
        else:
            # masih mirip list author (ada koma / 'and')
            if "," in clean or " and " in lower:
                authors += " " + clean
            else:
                break
    return title, authors


def extract_format_features(uploaded_file) -> pd.DataFrame:
    parsed = extract_text_from_pdf(uploaded_file)
    full_text = parsed["full_text"]
    first_page_lines = parsed["first_page_lines"]

    title, authors = guess_title_and_authors(first_page_lines)

    section_flags = {}
    for section, keywords in SECTION_KEYWORDS.items():
        section_flags[section] = int(any(kw in full_text for kw in keywords))

    status = "Compliant" if all(section_flags.values()) else "Non-compliant"

    record = {
        "file_name": uploaded_file.name,
        "title": title,
        "student_author": authors,
        **section_flags,
        "status": status,
    }
    return pd.DataFrame([record])


# ---------- UI helpers ----------

def yes_no_radio(label: str, key: str):
    """Radio tanpa default. Mengembalikan 'Yes', 'No', atau ''."""
    choice = st.radio(
        label,
        ("Belum memilih", "Yes", "No"),
        index=0,
        horizontal=True,
        key=key,
    )
    if choice == "Belum memilih":
        return ""
    return choice


def login_sidebar():
    st.sidebar.header("Login Reviewer")

    # Inisialisasi state user
    if "user" not in st.session_state:
        st.session_state.user = None

    user = st.session_state.user

    if user:
        role = user["role"]
        uname = user["username"]
        st.sidebar.success(f"Logged in as {uname} ({role.title()})")
        if st.sidebar.button("Logout"):
            st.session_state.user = None
            st.experimental_rerun()
        return

    username = st.sidebar.text_input("Username")
    password = st.sidebar.text_input("Password", type="password")

    if st.sidebar.button("Login"):
        info = USERS.get(username)
        if info and info["password"] == password:
            st.session_state.user = {
                "username": username,
                "role": info["role"],
            }
            st.experimental_rerun()
        else:
            st.sidebar.error("Invalid username or password.")


# ---------- Reviewer view ----------

def reviewer_view(user: Dict[str, Any]):
    st.subheader("Upload PDF File")

    uploaded_file = st.file_uploader(
        "Upload one paper PDF.", type=["pdf"], accept_multiple_files=False
    )

    if uploaded_file is None:
        st.info("Silakan upload dan analisis satu paper terlebih dahulu.")
        return

    # Simpan di session supaya form reset jika ganti file
    current_name = uploaded_file.name
    st.session_state["current_file_name"] = current_name

    df_features = extract_format_features(uploaded_file)

    st.markdown("### Format Features")
    st.dataframe(df_features, use_container_width=True)

    status = df_features.loc[0, "status"]
    if status == "Compliant":
        st.success("All required sections are present. Format is **COMPLIANT**.")
    else:
        st.warning("Beberapa section masih kurang. Format **NON-COMPLIANT**.")

    st.markdown("### Reviewer Evaluation")

    with st.form("review_form", clear_on_submit=True):
        advisor = st.text_input("Advisor", key=f"advisor_{current_name}")
        reviewer_name = st.text_input("Reviewer name", key=f"revname_{current_name}")

        st.markdown("**Is the manuscript written in proper and sound English?**")
        english_ans = yes_no_radio(
            "English OK?", key=f"english_ok_{current_name}"
        )
        english_issue = st.text_area(
            "If no, describe the main issues:",
            key=f"english_issue_{current_name}",
        )

        st.markdown("**Format follows author guideline?**")
        format_ans = yes_no_radio(
            "Format OK?", key=f"format_ok_{current_name}"
        )
        format_comment = st.text_area(
            "Format comments:", key=f"format_comment_{current_name}"
        )

        st.markdown("**Technical content**")
        sota_ans = yes_no_radio(
            "Is the problem state-of-the-art?", key=f"sota_ok_{current_name}"
        )
        clarity_ans = yes_no_radio(
            "Is the problem clearly stated?", key=f"clarity_ok_{current_name}"
        )
        figures_ans = yes_no_radio(
            "Do figures/tables support the goal/result?",
            key=f"figures_ok_{current_name}",
        )
        conclusion_ans = yes_no_radio(
            "Does the conclusion answer the problem?",
            key=f"conclusion_ok_{current_name}",
        )
        references_ans = yes_no_radio(
            "Are references up-to-date?",
            key=f"references_ok_{current_name}",
        )

        recommendations = st.text_area("Recommendations:", key=f"recom_{current_name}")

        overall_eval = st.selectbox(
            "Overall Evaluation",
            ["Belum memilih", "Full acceptance", "Accept with revision", "Reject"],
            index=0,
            key=f"overall_{current_name}",
        )
        if overall_eval == "Belum memilih":
            overall_eval_value = ""
        else:
            overall_eval_value = overall_eval

        submitted = st.form_submit_button("Submit Review")

    if submitted:
        # Convert jawaban Yes/No ke 1/0/"" untuk sheet
        def yn_to_int(ans: str):
            if ans == "Yes":
                return 1
            if ans == "No":
                return 0
            return ""

        feats = df_features.loc[0]

        row = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "reviewer_user": user["username"],
            "reviewer_role": "Reviewer",
            "file_name": feats["file_name"],
            "title": feats["title"],
            "student_author": feats["student_author"],
            "status": feats["status"],
            "Introduction": int(feats["Introduction"]),
            "Materials and methods": int(feats["Materials and methods"]),
            "Results and discussion": int(feats["Results and discussion"]),
            "Conclusion": int(feats["Conclusion"]),
            "References": int(feats["References"]),
            "advisor": advisor,
            "reviewed_by": reviewer_name,
            "english_ok": yn_to_int(english_ans),
            "english_issue": english_issue,
            "format_ok": yn_to_int(format_ans),
            "format_comment": format_comment,
            "sota_ok": yn_to_int(sota_ans),
            "clarity_ok": yn_to_int(clarity_ans),
            "figures_ok": yn_to_int(figures_ans),
            "conclusion_ok": yn_to_int(conclusion_ans),
            "references_ok": yn_to_int(references_ans),
            "recommendations": recommendations,
            "overall_eval": overall_eval_value,
        }

        append_review_row(row)

        df_all = load_reviews_df()
        st.success(
            f"Review submitted & saved to Google Sheets. "
            f"Total reviews saved: {len(df_all)}"
        )


# ---------- Admin view ----------

def admin_view(user: Dict[str, Any]):
    st.info(
        "You are logged in as **Admin**. Admin can view and download all reviews "
        "but cannot upload new papers or submit reviews."
    )

    try:
        df = load_reviews_df()
    except Exception as e:
        st.error(f"Error loading Google Sheets: {e}")
        return

    if df.empty:
        st.warning("No review data available yet.")
        return

    st.markdown("### Final Review Summary (All Sessions)")
    st.dataframe(df, use_container_width=True)

    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "Download All Review Summary as CSV",
        csv,
        file_name="ACMIT_Review_Summary.csv",
        mime="text/csv",
    )


# ---------- Main ----------

def main():
    st.set_page_config(
        page_title="Paper Review ACMIT",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    login_sidebar()
    user = st.session_state.get("user")

    st.title("SWISS GERMAN UNIVERSITY")
    st.subheader("Paper Review ACMIT")

    if not user:
        st.info("Silakan login terlebih dahulu untuk menggunakan aplikasi.")
        return

    if user["role"] == "admin":
        admin_view(user)
    else:
        reviewer_view(user)


if __name__ == "__main__":
    main()
