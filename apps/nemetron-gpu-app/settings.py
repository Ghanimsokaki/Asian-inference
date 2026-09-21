"""Read config from Streamlit secrets first, then environment variables."""
from __future__ import annotations

import os


def secret(name: str, default: str = "") -> str:
    try:
        import streamlit as st

        value = st.secrets.get(name)
        if value is not None:
            return str(value)
    except Exception:
        pass
    return os.getenv(name, default)
