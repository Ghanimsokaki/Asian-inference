# Nemetron App Starter

This starter uses **Nemotron through API access** and **GitHub through secrets**.

## What it uses

- `OPENROUTER_API_KEY`
- `OPENROUTER_MODEL`
- `GITHUB_CLIENT_ID`
- `GITHUB_CLIENT_SECRET`
- `GITHUB_CALLBACK_URL`

## Streamlit secrets

This starter reads **Streamlit secrets first**, then environment variables.

Example `.streamlit/secrets.toml`:

```toml
OPENROUTER_API_KEY = "your-openrouter-key"
OPENROUTER_MODEL = "nvidia/llama-3.1-nemotron-70b-instruct"
GITHUB_CLIENT_ID = "your-github-client-id"
GITHUB_CLIENT_SECRET = "your-github-client-secret"
GITHUB_CALLBACK_URL = "https://your-app.streamlit.app/github/callback"
```

## Files

- `app.py` — Streamlit frontend
- `settings.py` — Streamlit secrets/env reader
- `nemotron_client.py` — Nemotron API helper
- `github_oauth_config.py` — GitHub OAuth settings reader
- `github_setup.md` — GitHub setup notes
- `.env.example` — optional local env example

## Security

Keep real API keys and OAuth secrets in Streamlit secrets, hosting secrets, or environment variables.
Do not commit them into source code.
