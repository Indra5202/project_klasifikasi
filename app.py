import streamlit as st
import pandas as pd
import fitz  # PyMuPDF
from datetime import datetime

# === Konfigurasi halaman ===
st.set_page_config(page_title="Paper Format Classifier", layout="wide")

# === Daftar heading sesuai outline ACMIT baru ===
HEADINGS = [
    "introduction",
    "materials and methods",
    "results and discussion",
    "conclusion",
    "references",
]

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
st.markdown("""
<div class='centered-logo-title'>
    <div>
       <h1 style="font-size:50px; color:#2c5d94; text-align:center;">SWISS GERMAN UNIVERSITY</h1>
       <h1 style="font-size:50px; color:#2c5d94; text-align:center;">Paper Review ACMIT</h1>
       <p style='font-size:16px; color:gray;'>
           Upload one paper PDF and let the app automatically check format structure compliance (rule-based, without ML).
       </p>
    </div>
</div>
""", unsafe_allow_html=True)

st.markdown("---")

# === Upload file ===
st.markdown("<h4 style='color:#f39c12;'>📁 Upload PDF File</h4>", unsafe_allow_html=True)
pdf_file = st.file_uploader("Upload a PDF", type="pdf")


# === RESET STATE JIKA FILE BERGANTI ===
if pdf_file is not None:
    new_name = pdf_file.name
    # kalau belum ada current_pdf atau nama file berbeda → reset form
    if st.session_state.get("current_pdf") != new_name:
        # backup dulu rekap review kalau ada
        review_all_backup = st.session_state.get("review_all", [])

        # bersihkan seluruh session_state (supaya form kosong lagi)
        st.session_state.clear()

        # restore rekap dan set nama pdf aktif
        st.session_state["review_all"] = review_all_backup
        st.session_state["current_pdf"] = new_name


# === Fungsi bantu ===

def detect_heading_presence(full_text: str, heading: str) -> int:
    """
    Mengembalikan 1 jika heading ditemukan di teks (case-insensitive), selain itu 0.
    """
    if not full_text:
        return 0
    return 1 if heading.lower() in full_text.lower() else 0


def extract_title(lines):
    """
    Heuristik untuk mengekstrak judul paper dari lines halaman pertama.
    Menghindari baris yang berisi 'Contents list', info jurnal, dll.
    """
    blacklist = [
        "journal", "proceedings", "sciencedirect", "science direct",
        "elsevier", "www.", "http", "received", "accepted",
        "available online", "contents list", "volume", "issue",
        "open access", "license", "creativecommons"
    ]

    # Cek hanya 40 baris pertama (bagian atas paper)
    for line in lines[:40]:
        clean = line.strip()
        if not clean:
            continue

        # minimal 5 kata agar tidak kepilih text pendek
        if len(clean.split()) < 5:
            continue

        # jangan ambil baris yang mengandung kata blacklist
        if any(word in clean.lower() for word in blacklist):
            continue

        # hindari baris penuh angka (tahun, volume, dsb)
        if any(char.isdigit() for char in clean):
            continue

        return clean  # judul ditemukan

    # fallback: kalau tidak ketemu pakai baris pertama yang tidak kosong
    for line in lines:
        clean = line.strip()
        if clean:
            return clean
    return ""


def extract_author(lines, title):
    """
    Heuristik untuk mengekstrak baris nama author.
    Diasumsikan muncul SETELAH title dan berisi beberapa nama dengan huruf kapital.
    """
    found_title = False

    for line in lines:
        clean = line.strip()
        if not clean:
            continue

        # tandai saat melewati title
        if clean == title:
            found_title = True
            continue

        if not found_title:
            continue

        # setelah title: baris kandidat author
        words = clean.split()
        if not (2 <= len(words) <= 20):
            continue

        # butuh minimal 2 kata yang kapital
        cap_words = [w for w in words if w[0].isupper()]
        if len(cap_words) < 2:
            continue

        # biasanya ada koma / titik / tanda a,b,* dsb
        if "," in clean or ";" in clean or " and " in clean.lower() or "." in clean:
            return clean

    return ""


# === Proses jika ada file PDF ===
if pdf_file:
    # Baca teks dari PDF
    text = ""
    with fitz.open(stream=pdf_file.read(), filetype="pdf") as doc:
        for page in doc:
            text += page.get_text()

    lines = text.split("\n") if text else []

    # Pakai heuristik baru untuk title dan author
    title = extract_title(lines)
    student_author_line = extract_author(lines, title)

    # Deteksi heading berdasarkan outline baru
    detected = {
        "file_name": pdf_file.name,
        "title": title,
        "student_author": student_author_line
    }

    for heading in HEADINGS:
        detected[heading.capitalize()] = detect_heading_presence(text, heading)

    # === Evaluasi rule-based: compliant jika SEMUA heading ada ===
    all_ok = all(detected[h.capitalize()] == 1 for h in HEADINGS)
    detected["status"] = "✅ Compliant" if all_ok else "❌ Non-compliant"

    st.success("✅ Analysis complete (rule-based). Ready for reviewer evaluation.")

    # === Tampilkan hasil format ===
    st.markdown("<h5 style='color:#2c3e50;'>🔹 Format Features</h5>", unsafe_allow_html=True)
    df_format = pd.DataFrame([detected])
    st.dataframe(df_format, use_container_width=True)

    st.markdown("---")

    # === Reviewer Form ===
    st.markdown("<h5 style='color:#e74c3c;'>🔴 Reviewer Evaluation</h5>", unsafe_allow_html=True)

    with st.expander(f"📄 Review: {detected['file_name']}"):
        advisor = st.text_input("Advisor:", key="review_advisor")
        reviewed_by = st.text_input("Reviewer name:", key="review_reviewer")

        def radio_with_comment(question, key_prefix):
            val = st.radio(question, ["Yes", "No"], index=None, key=f"review_{key_prefix}_val")
            comment = ""
            if val == "No":
                comment = st.text_area(f"{question} - Comments:", key=f"review_{key_prefix}_comment")
            return val, comment

        english_ok, english_issue = radio_with_comment(
            "Is the manuscript written in proper and sound English?", "english"
        )
        format_ok, format_comment = radio_with_comment(
            "Format follows author guideline?", "format"
        )
        sota_ok = st.radio(
            "Is the problem state-of-the-art?", ["Yes", "No"], index=None, key="review_sota"
        )
        clarity_ok = st.radio(
            "Is the problem clearly stated?", ["Yes", "No"], index=None, key="review_clarity"
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

        recommendations = st.text_area("Recommendations:", key="review_recommend")
        overall_eval = st.selectbox(
            "Overall Evaluation",
            ["", "Reject", "Accept with revision", "Full acceptance"],
            key="review_eval"
        )

        if st.button("Submit Review"):
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
            if "review_all" not in st.session_state:
                st.session_state.review_all = []
            st.session_state.review_all.append(summary)
            st.success("✅ Review form submitted.")


# === Tampilkan hasil review semua ===
if "review_all" in st.session_state and st.session_state.review_all:
    st.markdown("### 🚀 Final Review Summary (All Sessions)")
    df_all = pd.DataFrame(st.session_state.review_all)
    df_all.insert(0, "No", range(1, len(df_all) + 1))

    st.markdown("#### 🔹 Format Features")
    format_cols = ["No", "file_name", "title", "status"] + [h.capitalize() for h in HEADINGS]
    st.dataframe(df_all[format_cols].set_index("No"), use_container_width=True)

    st.markdown("#### 🔴 Reviewer Evaluation")
    subjective_cols = [
        "No", "file_name", "title", "student_author", "advisor", "reviewed_by",
        "english_ok", "format_ok", "sota_ok", "clarity_ok", "figures_ok",
        "conclusion_ok", "references_ok", "recommendations", "overall_eval", "timestamp"
    ]
    st.dataframe(df_all[subjective_cols].set_index("No"), use_container_width=True)

    csv = df_all.to_csv(index=False).encode("utf-8")
    st.download_button(
        "💾 Download All Review Summary as CSV",
        csv,
        "review_summary.csv",
        "text/csv"
    )
