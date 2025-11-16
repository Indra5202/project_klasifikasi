import streamlit as st
import pandas as pd
import fitz  # PyMuPDF
from datetime import datetime
from streamlit.components.v1 import html  # untuk warning sebelum refresh/close

# === GLOBAL STORAGE UNTUK SEMUA REVIEW (share ke semua session) ===
# (Hilang kalau server di-restart, tapi dibagi ke semua user yang sedang pakai.)
if "GLOBAL_REVIEWS" not in globals():
    GLOBAL_REVIEWS = []

# === KONFIGURASI USER & ROLE (sementara hardcode di sini) ===
USERS = {
    "admin": {"password": "admin123", "role": "Admin"},
    "reviewer1": {"password": "rev123", "role": "Reviewer"},
    "reviewer2": {"password": "rev456", "role": "Reviewer"},
    # silakan tambah user lain di sini
}

# === Konfigurasi halaman ===
st.set_page_config(page_title="Paper Format Classifier", layout="wide")


# === FUNGSI LOGIN ===
def login_block():
    st.sidebar.title("Login Reviewer")

    username = st.sidebar.text_input("Username")
    password = st.sidebar.text_input("Password", type="password")

    if st.sidebar.button("Login"):
        user = USERS.get(username)
        if user and user["password"] == password:
            st.session_state["user"] = username
            st.session_state["role"] = user["role"]
            st.sidebar.success(f"Logged in as {username} ({user['role']})")
        else:
            st.sidebar.error("Invalid username or password")

    # tombol logout
    if "user" in st.session_state:
        if st.sidebar.button("Logout"):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()


# === Panggil blok login dulu ===
login_block()

# Kalau belum login, stop di sini
if "user" not in st.session_state:
    st.info("Please login from the left sidebar to use the app.")
    st.stop()

current_user = st.session_state["user"]
current_role = st.session_state["role"]

# === Daftar heading & sinonim (outline ACMIT baru) ===
HEADINGS = [
    "introduction",
    "materials and methods",
    "results and discussion",
    "conclusion",
    "references",
]

SECTION_SYNONYMS = {
    "introduction": [
        "introduction",
        "intro"
    ],
    "materials and methods": [
        "materials and methods",
        "material and methods",
        "materials & methods",
        "materials and method",
        "methodology",
        "methods and materials"
    ],
    "results and discussion": [
        "results and discussion",
        "result and discussion",
        "results & discussion",
        "results",
        "discussion"
    ],
    "conclusion": [
        "conclusion",
        "conclusions",
        "concluding remarks"
    ],
    "references": [
        "references",
        "reference",
        "bibliography"
    ],
}

# === Custom style ===
st.markdown("""
    <style>
        .centered-logo-title {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 1rem;
            margin-bottom: 1rem;
        }
        .centered-logo-title img {
            height: 60px;
        }
        .stTextInput > div > div > input {
            text-align: left;
        }
    </style>
""", unsafe_allow_html=True)

# === Heading dengan logo/title ===
st.markdown(f"""
<div class='centered-logo-title'>
    <div>
       <h1 style="font-size:50px; color:#2c5d94; text-align:center;">SWISS GERMAN UNIVERSITY</h1>
       <h1 style="font-size:50px; color:#2c5d94; text-align:center;">Paper Review ACMIT</h1>
       <p style='font-size:16px; color:gray; text-align:center;'>
           Logged in as <b>{current_user}</b> ({current_role})
       </p>
       <p style='font-size:14px; color:gray; text-align:center;'>
           Upload one paper PDF and let the app automatically check format structure compliance (rule-based, without ML).
       </p>
    </div>
</div>
""", unsafe_allow_html=True)

st.markdown("---")

# === Fungsi bantu ===

def detect_heading_presence(full_text: str, section_key: str) -> int:
    """
    Mengembalikan 1 jika salah satu sinonim heading ditemukan di teks (case-insensitive), selain itu 0.
    """
    if not full_text:
        return 0
    text_low = full_text.lower()
    for phrase in SECTION_SYNONYMS.get(section_key, [section_key]):
        if phrase.lower() in text_low:
            return 1
    return 0


def extract_title(lines):
    """
    Heuristik untuk mengekstrak judul paper dari halaman pertama.
    Menggabungkan beberapa baris judul jika terpisah (seperti contoh ACMIT).
    """
    blacklist = [
        "journal", "proceedings", "sciencedirect", "science direct",
        "elsevier", "www.", "http", "received", "accepted",
        "available online", "contents list", "volume", "issue",
        "open access", "license", "creativecommons"
    ]

    max_lookahead = 4  # maksimal 4 baris lanjutan judul

    for i, line in enumerate(lines[:40]):  # cek hanya bagian atas
        clean = line.strip()
        if not clean:
            continue

        if len(clean.split()) < 3:
            continue

        low = clean.lower()
        if any(word in low for word in blacklist):
            continue

        if sum(ch.isdigit() for ch in clean) > 4:
            continue

        # kandidat judul ditemukan → cek lanjutan judul
        title_lines = [clean]
        last_idx = i

        for j in range(i + 1, min(i + 1 + max_lookahead, len(lines))):
            nxt = lines[j].strip()
            if not nxt:
                break
            nxt_low = nxt.lower()

            if "abstract" in nxt_low:
                break
            if any(word in nxt_low for word in blacklist):
                break
            # kalau ada angka → kemungkinan baris author dengan superscript
            if any(ch.isdigit() for ch in nxt):
                break

            if 2 <= len(nxt.split()) <= 12:
                title_lines.append(nxt)
                last_idx = j
            else:
                break

        return " ".join(title_lines), last_idx

    # fallback
    for i, line in enumerate(lines):
        clean = line.strip()
        if clean:
            return clean, i
    return "", -1


def extract_author(lines, start_idx):
    """
    Heuristik mengekstrak baris nama author.
    Mencari di beberapa baris setelah judul (start_idx).
    """
    if start_idx < 0:
        search_start = 0
    else:
        search_start = start_idx + 1

    for line in lines[search_start: search_start + 10]:
        clean = line.strip()
        if not clean:
            continue

        words = clean.split()
        if not (2 <= len(words) <= 25):
            continue

        cap_words = [w for w in words if w[0].isupper()]
        if len(cap_words) < 2:
            continue

        if "," in clean or ";" in clean or " and " in clean.lower() or "." in clean:
            return clean

    return ""


# === BAGIAN UPLOAD & REVIEW: hanya untuk Reviewer ===
if current_role == "Reviewer":
    st.markdown("<h4 style='color:#f39c12;'>📁 Upload PDF File</h4>", unsafe_allow_html=True)
    pdf_file = st.file_uploader("Upload a PDF", type="pdf")

    if pdf_file:
        # key dasar per file (supaya setiap file punya widget state sendiri per user)
        file_key = f"{current_user}_" + pdf_file.name.replace(".", "_").replace(" ", "_")

        # baca teks dari PDF
        text = ""
        with fitz.open(stream=pdf_file.read(), filetype="pdf") as doc:
            for page in doc:
                text += page.get_text()

        lines = text.split("\n") if text else []

        # pakai heuristik title & author
        title, title_last_idx = extract_title(lines)
        student_author_line = extract_author(lines, title_last_idx)

        # deteksi heading berdasarkan outline baru
        detected = {
            "file_name": pdf_file.name,
            "title": title,
            "student_author": student_author_line,
            "reviewer_user": current_user,
            "reviewer_role": current_role,
        }

        for heading in HEADINGS:
            detected[heading.capitalize()] = detect_heading_presence(text, heading)

        # cek compliant & bagian yang hilang
        missing_sections = [h for h in HEADINGS if detected[h.capitalize()] == 0]
        all_ok = len(missing_sections) == 0
        detected["status"] = "✅ Compliant" if all_ok else "❌ Non-compliant"

        # pesan format lebih informatif
        if all_ok:
            st.success("✅ All required sections are present. Format is COMPLIANT.")
        else:
            st.warning(
                "❌ Format is NOT compliant. Missing sections: "
                + ", ".join(s.title() for s in missing_sections)
            )

        # tampilkan hasil format
        st.markdown("<h5 style='color:#2c3e50;'>🔹 Format Features</h5>", unsafe_allow_html=True)
        df_format = pd.DataFrame([detected])
        st.dataframe(df_format, use_container_width=True)

        st.markdown("---")

        # === Reviewer Form ===
        st.markdown("<h5 style='color:#e74c3c;'>🔴 Reviewer Evaluation</h5>", unsafe_allow_html=True)

        with st.expander(f"📄 Review: {detected['file_name']}"):
            advisor = st.text_input("Advisor:", key=f"{file_key}_advisor")
            reviewed_by = st.text_input("Reviewer name:", key=f"{file_key}_reviewer")

            def radio_with_comment(question, key_prefix):
                val = st.radio(
                    question,
                    ["Yes", "No"],
                    index=None,
                    key=f"{file_key}_{key_prefix}_val"
                )
                comment = ""
                if val == "No":
                    comment = st.text_area(
                        f"{question} - Comments:",
                        key=f"{file_key}_{key_prefix}_comment"
                    )
                return val, comment

            english_ok, english_issue = radio_with_comment(
                "Is the manuscript written in proper and sound English?", "english"
            )
            format_ok, format_comment = radio_with_comment(
                "Format follows author guideline?", "format"
            )
            sota_ok = st.radio(
                "Is the problem state-of-the-art?", ["Yes", "No"],
                index=None, key=f"{file_key}_sota"
            )
            clarity_ok = st.radio(
                "Is the problem clearly stated?", ["Yes", "No"],
                index=None, key=f"{file_key}_clarity"
            )
            figures_ok, figures_comment = radio_with_comment(
                "Do figures/tables support the goal/result?", "figures"
            )
            conclusion_ok, conclusion_comment = radio_with_comment(
                "Does the conclusion answer the problem?", "conclusion"
            )
            references_ok, references_comment = radio_with_comment(
                "Are references up-to-date?", "references"
            )

            recommendations = st.text_area(
                "Recommendations:", key=f"{file_key}_recommend"
            )
            overall_eval = st.selectbox(
                "Overall Evaluation",
                ["", "Reject", "Accept with revision", "Full acceptance"],
                key=f"{file_key}_overall_eval"
            )

            # === VALIDASI sebelum submit ===
            if st.button("Submit Review", key=f"{file_key}_submit"):
                errors = []

                if not advisor.strip():
                    errors.append("• Advisor is required.")
                if not reviewed_by.strip():
                    errors.append("• Reviewer name is required.")
                if overall_eval.strip() == "":
                    errors.append("• Overall Evaluation is required.")

                if (
                    english_ok is None
                    or format_ok is None
                    or sota_ok is None
                    or clarity_ok is None
                    or figures_ok is None
                    or conclusion_ok is None
                    or references_ok is None
                ):
                    errors.append("• Please answer all Yes/No questions.")

                if errors:
                    st.warning("Please complete the following before submitting:\n" + "\n".join(errors))
                else:
                    summary = {
                        **detected,
                        "advisor": advisor,
                        "reviewed_by": reviewed_by,
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
                        "references_comment": references_comment,
                        "recommendations": recommendations,
                        "overall_eval": overall_eval,
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    GLOBAL_REVIEWS.append(summary)  # SIMPAN DI GLOBAL
                    st.success("✅ Review form submitted.")
elif current_role == "Admin":
    # Admin tidak boleh upload / review
    st.info("You are logged in as Admin. Admin can view and download all reviews but cannot upload new papers or submit reviews.")


# === Tampilkan hasil review semua (GLOBAL) ===
if GLOBAL_REVIEWS:
    st.markdown("### 🚀 Final Review Summary (All Sessions)")

    df_all = pd.DataFrame(GLOBAL_REVIEWS)
    df_all.insert(0, "No", range(1, len(df_all) + 1))

    # pastikan semua kolom yang kita butuhkan SELALU ada
    needed_format_cols = ["file_name", "title", "status", "reviewer_user", "reviewer_role"] + [
        h.capitalize() for h in HEADINGS
    ]
    needed_subjective_cols = [
        "student_author", "advisor", "reviewed_by",
        "english_ok", "format_ok", "sota_ok", "clarity_ok", "figures_ok",
        "conclusion_ok", "references_ok", "recommendations", "overall_eval",
        "timestamp",
    ]

    for col in needed_format_cols + needed_subjective_cols:
        if col not in df_all.columns:
            df_all[col] = ""

    # filter data sesuai role
    if current_role == "Admin":
        df_view = df_all.copy()  # Admin lihat SEMUA review
    else:
        # reviewer hanya lihat review milik dia sendiri
        df_view = df_all[df_all["reviewer_user"] == current_user].copy()

    if df_view.empty:
        st.info("No reviews recorded yet for this user.")
    else:
        st.markdown("#### 🔹 Format Features")
        format_cols = ["No", "file_name", "title", "status", "reviewer_user", "reviewer_role"] + [
            h.capitalize() for h in HEADINGS
        ]
        st.dataframe(df_view[format_cols].set_index("No"), use_container_width=True)

        st.markdown("#### 🔴 Reviewer Evaluation")
        subjective_cols = [
            "No", "file_name", "title", "student_author", "advisor", "reviewed_by",
            "reviewer_user", "reviewer_role",
            "english_ok", "format_ok", "sota_ok", "clarity_ok", "figures_ok",
            "conclusion_ok", "references_ok", "recommendations", "overall_eval", "timestamp"
        ]
        st.dataframe(df_view[subjective_cols].set_index("No"), use_container_width=True)

        # hanya Admin yang boleh download semua review
        if current_role == "Admin":
            csv = df_all.to_csv(index=False).encode("utf-8")
            st.download_button(
                "💾 Download All Review Summary as CSV (Admin only)",
                csv,
                "review_summary.csv",
                "text/csv"
            )

    # === Warning jika user mau refresh/close saat ada data review ===
    html("""
    <script>
    window.addEventListener('beforeunload', function (e) {
        var confirmationMessage = 'Reloading this page will clear the current review data that has not been downloaded. Are you sure?';
        (e || window.event).returnValue = confirmationMessage;
        return confirmationMessage;
    });
    </script>
    """)
else:
    st.info("No reviews recorded yet.")
