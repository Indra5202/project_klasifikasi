import io
import re
from datetime import datetime

import pandas as pd
import streamlit as st
from PyPDF2 import PdfReader
from google.oauth2 import service_account
import gspread


# ========== CONFIG LOGIN ==========

# Silakan ganti password sesuai kebutuhan
USERS = {
    "reviewer1": {"password": "reviewer1", "role": "Reviewer"},
    "reviewer2": {"password": "reviewer2", "role": "Reviewer"},
    "admin": {"password": "admin", "role": "Admin"},
}


# ========== GOOGLE SHEETS HELPERS ==========

@st.cache_resource(show_spinner=False)
def get_gsheet_client():
    """Authorize client gspread dari service account di st.secrets."""
    creds_info = st.secrets["google_service_account"]
    creds = service_account.Credentials.from_service_account_info(
        creds_info,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    client = gspread.authorize(creds)
    return client


def get_sheet_id() -> str:
    """Ambil Google Sheet ID dari secrets (root atau di dalam blok google_service_account)."""
    if "google_sheet_id" in st.secrets:
        return st.secrets["google_sheet_id"]
    # fallback kalau user menaruh di dalam blok
    gsa = st.secrets.get("google_service_account", {})
    if "google_sheet_id" in gsa:
        return gsa["google_sheet_id"]
    raise KeyError(
        "google_sheet_id tidak ditemukan di secrets. "
        'Tambahkan `google_sheet_id = "SHEET_ID"` di secrets.'
    )


def get_reviews_worksheet():
    client = get_gsheet_client()
    sheet_id = get_sheet_id()
    sh = client.open_by_key(sheet_id)
    ws = sh.sheet1  # pakai sheet pertama
    return ws


def save_review_to_gsheet(row_dict: dict):
    """Append satu baris review ke Google Sheets. Auto bikin header kalau belum ada."""
    ws = get_reviews_worksheet()
    existing = ws.get_all_values()
    if not existing:
        # tulis header
        ws.append_row(list(row_dict.keys()))
    ws.append_row(list(row_dict.values()))


def load_all_reviews_df() -> pd.DataFrame:
    """Ambil semua review dari Google Sheets sebagai DataFrame."""
    ws = get_reviews_worksheet()
    data = ws.get_all_records()
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)
    return df


def user_has_review_for_file(reviewer_user: str, file_name: str) -> bool:
    """
    True jika reviewer_user sudah pernah mengirim review untuk file_name yang sama.
    """
    df = load_all_reviews_df()
    if df.empty:
        return False
    if "reviewer_user" not in df.columns or "file_name" not in df.columns:
        return False
    mask = (df["reviewer_user"] == reviewer_user) & (df["file_name"] == file_name)
    return mask.any()


# ========== PDF & FORMAT OUTLINE ==========

def extract_text_from_pdf(uploaded_file) -> str:
    """Ambil semua teks dari PDF menggunakan PyPDF2."""
    reader = PdfReader(uploaded_file)
    texts = []
    for page in reader.pages:
        try:
            texts.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n".join(texts)


def extract_title_and_author(text: str):
    """
    Heuristik sederhana:
    - Title: baris pertama yang agak panjang sebelum kata 'Abstract'
    - Author: baris setelah title
    Silakan sesuaikan jika mau lebih canggih.
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    title = ""
    author = ""

    # cari index Abstract
    abs_idx = None
    for i, line in enumerate(lines[:40]):  # batasi 40 baris pertama
        if re.search(r"\babstract\b", line, re.IGNORECASE):
            abs_idx = i
            break

    search_limit = abs_idx if abs_idx is not None else min(len(lines), 20)

    # Title: baris paling panjang dalam range awal
    if search_limit > 0:
        candidate_lines = lines[:search_limit]
        title = max(candidate_lines, key=len)

    # Author: baris setelah title jika ada
    if title and title in lines:
        idx = lines.index(title)
        if idx + 1 < len(lines):
            author = lines[idx + 1]

    return title, author


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
        "result and discussion",
        "results",
        "discussion",
    ],
    "Conclusion": ["conclusion", "conclusions", "concluding remarks"],
    "References": ["references", "bibliography"],
}


def check_section_present(text: str, keywords) -> int:
    """Return 1 jika ada salah satu keyword muncul, else 0."""
    text_low = text.lower()
    for kw in keywords:
        if kw in text_low:
            return 1
    return 0


def analyze_format(uploaded_file_name: str, text: str):
    """
    Analisis rule-based outline (tanpa ML).
    Return:
        - format_df: DataFrame 1 baris dengan kolom: file_name, title, student_author, section flags, status
        - title, author, status_bool
    """
    title, author = extract_title_and_author(text)

    section_flags = {}
    for sec_name, kws in SECTION_KEYWORDS.items():
        section_flags[sec_name] = check_section_present(text, kws)

    # semua wajib ada → compliant
    status_bool = all(section_flags.values())
    status_str = "Compliant" if status_bool else "Non-compliant"

    row = {
        "file_name": uploaded_file_name,
        "title": title,
        "student_author": author,
        **section_flags,
        "status": status_str,
    }
    format_df = pd.DataFrame([row])

    return format_df, title, author, status_bool


# ========== SESSION / LOGIN ==========

def init_session():
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
    if "user" not in st.session_state:
        st.session_state.user = None
    if "role" not in st.session_state:
        st.session_state.role = None


def login_sidebar():
    st.sidebar.title("Login Reviewer")

    if st.session_state.logged_in:
        st.sidebar.success(
            f"Logged in as {st.session_state.user} ({st.session_state.role})"
        )
        if st.sidebar.button("Logout"):
            st.session_state.logged_in = False
            st.session_state.user = None
            st.session_state.role = None
            st.experimental_rerun()
        return

    username = st.sidebar.text_input("Username")
    password = st.sidebar.text_input("Password", type="password")
    if st.sidebar.button("Login"):
        user_info = USERS.get(username)
        if user_info and password == user_info["password"]:
            st.session_state.logged_in = True
            st.session_state.user = username
            st.session_state.role = user_info["role"]
            st.experimental_rerun()
        else:
            st.sidebar.error("Invalid username or password.")


# ========== VIEW: ADMIN ==========

def show_admin_view():
    st.markdown("### 📊 Final Review Summary (All Sessions)")
    try:
        df_all = load_all_reviews_df()
    except Exception as e:
        st.error(
            f"Error loading Google Sheets: {e}. "
            "Pastikan `google_sheet_id` dan service account sudah benar di secrets."
        )
        return

    if df_all.empty:
        st.info("No review data available yet.")
        return

    df_all = df_all.copy()
    df_all = df_all.reset_index(drop=True)
    df_all.insert(0, "No", df_all.index + 1)

    st.dataframe(df_all, use_container_width=True)

    csv = df_all.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️ Download All Review Summary (CSV)",
        data=csv,
        file_name="ACMIT_all_reviews.csv",
        mime="text/csv",
    )


# ========== VIEW: REVIEWER ==========

def show_reviewer_view():
    st.subheader("Upload PDF File")
    uploaded_file = st.file_uploader(
        "Upload a PDF", type=["pdf"], accept_multiple_files=False
    )

    if uploaded_file is None:
        st.info("Silakan upload satu file PDF untuk dianalisis.")
        return

    # Analisis format
    with st.spinner("Membaca dan menganalisis PDF..."):
        try:
            text = extract_text_from_pdf(uploaded_file)
        except Exception as e:
            st.error(f"Gagal membaca PDF: {e}")
            return

        format_df, title, author, status_bool = analyze_format(uploaded_file.name, text)

    st.success("Analysis complete (rule-based). Format status: "
               + ("✅ COMPLIANT" if status_bool else "❌ NON-COMPLIANT"))

    # Tampilkan Format Features
    st.markdown("### 📑 Format Features")
    format_df_display = format_df.copy()
    format_df_display.insert(0, "No", 1)
    st.dataframe(format_df_display, use_container_width=True)

    current_user = st.session_state.user
    current_role = st.session_state.role
    file_name = uploaded_file.name

    # Cek apakah user sudah pernah mereview file ini
    if user_has_review_for_file(current_user, file_name):
        st.warning(
            f"Anda sudah pernah mengirim review untuk file **{file_name}**.\n\n"
            "Form review dikunci untuk mencegah duplikasi."
        )
        # tampilkan ringkasan review yang sudah ada
        df_all = load_all_reviews_df()
        df_user_file = df_all[
            (df_all["reviewer_user"] == current_user)
            & (df_all["file_name"] == file_name)
        ]
        if not df_user_file.empty:
            with st.expander("Lihat review yang sudah pernah Anda kirim"):
                st.dataframe(df_user_file, use_container_width=True)
        return

    # Jika belum pernah review → tampilkan form
    st.markdown("### 📝 Reviewer Evaluation")

    with st.form("review_form", clear_on_submit=True):
        advisor = st.text_input("Advisor")
        reviewer_name = st.text_input("Reviewer name")

        st.markdown("##### Pertanyaan")
        english_ok = st.radio(
            "Is the manuscript written in proper and sound English?",
            ["Yes", "No"],
            index=0,
        )
        format_ok = st.radio(
            "Format follows author guideline?", ["Yes", "No"], index=0
        )
        sota_ok = st.radio(
            "Is the problem state-of-the-art?", ["Yes", "No"], index=0
        )
        clarity_ok = st.radio(
            "Is the problem clearly stated?", ["Yes", "No"], index=0
        )
        figures_ok = st.radio(
            "Do figures/tables support the goal/result?", ["Yes", "No"], index=0
        )
        conclusion_ok = st.radio(
            "Does the conclusion answer the problem?", ["Yes", "No"], index=0
        )
        refs_ok = st.radio(
            "Are references up-to-date?", ["Yes", "No"], index=0
        )

        recommendations = st.text_area("Recommendations")
        overall_eval = st.selectbox(
            "Overall Evaluation",
            ["Full acceptance", "Accept with revision", "Reject"],
        )

        submitted = st.form_submit_button("Submit Review")

        if submitted:
            row = {
                "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                "reviewer_user": current_user,
                "reviewer_role": "Reviewer",
                "file_name": file_name,
                "title": title,
                "student_author": author,
                "status": "Compliant" if status_bool else "Non-compliant",
                "Introduction": int(format_df["Introduction"].iloc[0]),
                "Materials and methods": int(
                    format_df["Materials and methods"].iloc[0]
                ),
                "Results and discussion": int(
                    format_df["Results and discussion"].iloc[0]
                ),
                "Conclusion": int(format_df["Conclusion"].iloc[0]),
                "References": int(format_df["References"].iloc[0]),
                "advisor": advisor,
                "reviewed_by": reviewer_name,
                "english_ok": english_ok,
                "format_ok": format_ok,
                "sota_ok": sota_ok,
                "clarity_ok": clarity_ok,
                "figures_ok": figures_ok,
                "conclusion_ok": conclusion_ok,
                "references_ok": refs_ok,
                "recommendations": recommendations,
                "overall_eval": overall_eval,
            }

            try:
                save_review_to_gsheet(row)
            except Exception as e:
                st.error(f"Gagal menyimpan ke Google Sheets: {e}")
                return

            st.success("✅ Review submitted & saved to central Google Sheet.")

            df_all = load_all_reviews_df()
            count_user = (df_all["reviewer_user"] == current_user).sum()
            st.info(f"Total reviews yang sudah Anda kirim: **{count_user}**")


# ========== MAIN APP ==========

def main():
    st.set_page_config(
        page_title="Paper Review ACMIT",
        layout="wide",
    )

    st.title("SWISS GERMAN UNIVERSITY")
    st.header("Paper Review ACMIT")

    init_session()
    login_sidebar()

    if not st.session_state.logged_in:
        st.info("Silakan login terlebih dahulu untuk menggunakan aplikasi.")
        return

    role = st.session_state.role

    if role == "Admin":
        st.write(f"Logged in as **{st.session_state.user}** *(Admin)*")
        show_admin_view()
    else:
        st.write(
            f"Logged in as **{st.session_state.user}** *(Reviewer)*"
        )
        show_reviewer_view()


if __name__ == "__main__":
    main()
