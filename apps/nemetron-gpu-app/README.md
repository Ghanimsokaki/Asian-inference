# Nemetron Cloud App Starter

This starter keeps **Nemotron as an API model** and keeps **GPU for your app workloads**.

## Architecture

- `app.py` → normal Streamlit app UI
- `nemotron_client.py` → calls Nemotron through an API key
- `modal_app.py` → cloud GPU worker for app-side GPU jobs
- `gpu_tasks.py` → place your GPU-heavy code here
- `.github/workflows/modal-deploy.yml` → deploy the cloud GPU worker with GitHub Actions

## Important idea

Nemotron does **not** need your Modal GPU here.

Use Nemotron through:
- `OPENROUTER_API_KEY`
- `OPENROUTER_MODEL`

Use Modal GPU for things like:
- image processing
- embeddings
- local model inference
- audio / vision pipelines
- custom GPU agents
- app-side acceleration similar to a cloud app / Space backend

## Streamlit secrets

This starter now reads **Streamlit secrets first**, then environment variables.

Example `.streamlit/secrets.toml`:

```toml
OPENROUTER_API_KEY = "your-openrouter-key"
OPENROUTER_MODEL = "nvidia/llama-3.1-nemotron-70b-instruct"
GITHUB_CLIENT_ID = "your-github-client-id"
GITHUB_CLIENT_SECRET = "your-github-client-secret"
GITHUB_CALLBACK_URL = "https://your-app.streamlit.app/github/callback"
```

## Suggested GPU defaults by plan

- Starter → `T4`
- Pro → `A10G`
- Elite → `A100`

## Environment variables

### Nemotron API
- `OPENROUTER_API_KEY`
- `OPENROUTER_MODEL`

### Modal cloud GPU
- `MODAL_GPU`
- `MODAL_TOKEN_ID`
- `MODAL_TOKEN_SECRET`

### GitHub OAuth app
- `GITHUB_CLIENT_ID`
- `GITHUB_CLIENT_SECRET`
- `GITHUB_CALLBACK_URL`

## Files

- `app.py` — frontend
- `settings.py` — Streamlit secrets/env reader
- `nemotron_client.py` — Nemotron API helper
- `gpu_tasks.py` — your GPU task stubs
- `modal_app.py` — cloud GPU runner
- `github_oauth_config.py` — GitHub OAuth settings reader
- `github_setup.md` — GitHub setup notes

## Security

Keep real API keys and OAuth secrets in Streamlit secrets, environment variables, or GitHub/hosting secrets.
Do not commit them into source code.
