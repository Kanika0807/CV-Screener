import streamlit as st
import pandas as pd
import pdfplumber
import docx2txt
import json
import time
from groq import Groq

st.set_page_config(page_title="CV Screener", page_icon="📋", layout="wide")

st.title("📋 CV Screener")
st.markdown("Upload a Job Description and multiple CVs to get ranked screening results.")

# --- API Key ---
api_key = st.secrets.get("GROQ_API_KEY", None)
if not api_key:
    st.error("API key not configured. Please contact the app administrator.")
    st.stop()

client = Groq(api_key=api_key)


def extract_text(file) -> str:
    name = file.name.lower()
    if name.endswith(".pdf"):
        with pdfplumber.open(file) as pdf:
            return "\n".join(p.extract_text() or "" for p in pdf.pages)
    elif name.endswith(".docx"):
        return docx2txt.process(file)
    else:
        return file.read().decode("utf-8", errors="ignore")


def screen_cv(jd_text: str, cv_text: str, candidate_name: str) -> dict:
    prompt = f"""
You are an expert HR recruiter. Screen the following CV against the Job Description.

JOB DESCRIPTION:
{jd_text[:3000]}

CANDIDATE CV:
{cv_text[:3000]}

Return a JSON object with exactly these fields:
{{
  "score": <integer 0-100>,
  "verdict": "<Strong Match | Good Match | Partial Match | Poor Match>",
  "top_strengths": "<2-3 key strengths matching the JD>",
  "gaps": "<2-3 key gaps or missing requirements>",
  "summary": "<2-3 sentence overall summary>",
  "email": "<candidate email address, or 'Not found' if not present>",
  "phone": "<candidate phone number, or 'Not found' if not present>",
  "companies": "<comma separated list of all companies the candidate has worked at>"
}}

Return only valid JSON, no extra text.
"""
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            text = response.choices[0].message.content.strip()
            result = json.loads(text)
            result["candidate"] = candidate_name
            return result
        except Exception as e:
            if attempt < 2:
                time.sleep(3)
            else:
                return {
                    "candidate": candidate_name,
                    "score": 0,
                    "verdict": "Error",
                    "top_strengths": "Could not parse",
                    "gaps": str(e),
                    "summary": "Screening failed for this CV."
                }


# --- Upload Section ---
col1, col2 = st.columns(2)

with col1:
    st.subheader("1. Upload Job Description")
    jd_file = st.file_uploader("JD file (PDF, DOCX, or TXT)", type=["pdf", "docx", "txt"], key="jd")

with col2:
    st.subheader("2. Upload CVs")
    cv_files = st.file_uploader("CV files (PDF, DOCX, or TXT)", type=["pdf", "docx", "txt"],
                                 accept_multiple_files=True, key="cvs")

if jd_file and cv_files:
    if st.button("🚀 Start Screening", type="primary", use_container_width=True):
        jd_text = extract_text(jd_file)

        if not jd_text.strip():
            st.error("Could not extract text from the JD. Please check the file.")
            st.stop()

        results = []
        progress = st.progress(0, text="Starting screening...")
        total = len(cv_files)

        for i, cv_file in enumerate(cv_files):
            candidate_name = cv_file.name.replace(".pdf", "").replace(".docx", "").replace(".txt", "")
            progress.progress((i) / total, text=f"Screening {candidate_name}... ({i+1}/{total})")
            cv_text = extract_text(cv_file)
            result = screen_cv(jd_text, cv_text, candidate_name)
            results.append(result)
            time.sleep(2)

        progress.progress(1.0, text="Screening complete!")
        results.sort(key=lambda x: x.get("score", 0), reverse=True)
        st.session_state["results"] = results
        st.success(f"Screened {total} CVs successfully!")

# --- Display Results (persists across page interactions) ---
if "results" in st.session_state and st.session_state["results"]:
    results = st.session_state["results"]

    col_title, col_btn = st.columns([6, 1])
    with col_title:
        st.subheader("📊 Ranked Results")
    with col_btn:
        if st.button("🗑️ Clear Results"):
            del st.session_state["results"]
            st.rerun()

    df = pd.DataFrame([{
        "Rank": i + 1,
        "Candidate": r["candidate"],
        "Email": r.get("email", "Not found"),
        "Phone": r.get("phone", "Not found"),
        "Companies Worked At": r.get("companies", "Not found"),
        "Score": r["score"],
        "Verdict": r["verdict"],
        "Top Strengths": r["top_strengths"],
        "Gaps": r["gaps"],
        "Summary": r["summary"],
    } for i, r in enumerate(results)])

    def color_verdict(val):
        colors = {
            "Strong Match": "background-color: #d4edda; color: #155724",
            "Good Match": "background-color: #cce5ff; color: #004085",
            "Partial Match": "background-color: #fff3cd; color: #856404",
            "Poor Match": "background-color: #f8d7da; color: #721c24",
            "Error": "background-color: #e2e3e5; color: #383d41",
        }
        return colors.get(val, "")

    styled = df.style.map(color_verdict, subset=["Verdict"])
    st.dataframe(styled, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("📄 Detailed Breakdown")
    for i, r in enumerate(results):
        verdict_emoji = {"Strong Match": "🟢", "Good Match": "🔵", "Partial Match": "🟡", "Poor Match": "🔴"}.get(r["verdict"], "⚪")
        with st.expander(f"{i+1}. {r['candidate']} — Score: {r['score']}/100 {verdict_emoji} {r['verdict']}"):
            c1, c2 = st.columns(2)
            with c1:
                st.markdown(f"**Top Strengths:**\n{r['top_strengths']}")
            with c2:
                st.markdown(f"**Gaps:**\n{r['gaps']}")
            st.markdown(f"**Summary:** {r['summary']}")

    st.markdown("---")
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="⬇️ Download Results as CSV",
        data=csv,
        file_name="screening_results.csv",
        mime="text/csv",
        use_container_width=True,
        type="primary"
    )
