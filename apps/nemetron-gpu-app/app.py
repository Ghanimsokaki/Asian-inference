"""Streamlit frontend for the Nemetron app starter."""
from __future__ import annotations

import streamlit as st

from github_oauth_config import github_oauth_ready
from nemotron_client import (
    DEFAULT_MODEL,
    NemotronConfigError,
    NemotronRequestError,
    generate_nemotron_reply,
)

APP_NAME = "Nemetron App"

st.set_page_config(page_title=APP_NAME, page_icon="🚀", layout="wide")

st.title(f"🚀 {APP_NAME}")
st.caption("Nemotron via API key with GitHub-ready secret settings")

col1, col2 = st.columns(2)
col1.metric("Nemotron model", DEFAULT_MODEL)
col2.metric("GitHub OAuth", "configured" if github_oauth_ready() else "not set")

system_prompt = st.text_area(
    "System prompt",
    value="You are an agentic assistant inside a custom app. Answer directly and do not trigger unrelated build flows.",
    height=100,
)
prompt = st.text_area("Prompt", placeholder="Ask Nemotron something…", height=180)

if st.button("Run Nemotron", type="primary"):
    try:
        result = generate_nemotron_reply(prompt, system_prompt=system_prompt)
    except (NemotronConfigError, NemotronRequestError) as exc:
        st.error(str(exc))
    else:
        st.markdown("### Nemotron response")
        st.write(result)

st.markdown("### Streamlit secrets example")
st.code(
    'OPENROUTER_API_KEY = "..."\n'
    'OPENROUTER_MODEL = "nvidia/llama-3.1-nemotron-70b-instruct"\n'
    'GITHUB_CLIENT_ID = "..."\n'
    'GITHUB_CLIENT_SECRET = "..."\n'
    'GITHUB_CALLBACK_URL = "https://your-app.streamlit.app/github/callback"\n',
    language="toml",
)
