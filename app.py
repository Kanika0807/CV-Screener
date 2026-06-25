import streamlit as st
import pandas as pd
import pdfplumber
import docx2txt
import google.generativeai as genai
import json
import io
import time

st.set_page_config(page_title="CV Screener", page_icon="📋", layout="wide")

st.title("📋 CV Screener")
st.markdown("Upload a Job Description and multiple CVs to get ranked screening results.")

# --- API Key ---
api_key = st.secrets.get("GEMINI_API_KEY", None)
if not api_key:
    api_key = st.sidebar.text_input("Enter Gemini API Key", type="password")
if not api_key:
    st.warning("Please enter your Gemini API key in the sidebar to continue.")
    st.stop()

genai.configure(api_key=api_key)
model = genai.GenerativeModel("gemini-2.0-flash")


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
  "summary": "<2-3 sentence overall summary>"
}}

Return only valid JSON, no extra text.
"""
    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        result = json.loads(text)
        result["candidate"] = candidate_name
        return result
    except Exception as e:
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
            time.sleep(0.5)  # avoid rate limiting

        progress.progress(1.0, text="Screening complete!")

        # Sort by score descending
        results.sort(key=lambda x: x.get("score", 0), reverse=True)

        st.success(f"Screened {total} CVs successfully!")
        st.markdown("---")
        st.subheader("📊 Ranked Results")

        # Summary table
        df = pd.DataFrame([{
            "Rank": i + 1,
            "Candidate": r["candidate"],
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

        # Detailed cards
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

        # Download CSV
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
