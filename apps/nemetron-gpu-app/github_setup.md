# GitHub setup for the Nemetron App

Add these in your app secrets or deployment secrets:

- `OPENROUTER_API_KEY`
- `OPENROUTER_MODEL`
- `GITHUB_CLIENT_ID`
- `GITHUB_CLIENT_SECRET`
- `GITHUB_CALLBACK_URL`

If you use Streamlit Cloud, put them in:

- **App Settings**
- **Secrets**

Example:

```toml
OPENROUTER_API_KEY = "your-openrouter-key"
OPENROUTER_MODEL = "nvidia/llama-3.1-nemotron-70b-instruct"
GITHUB_CLIENT_ID = "your-github-client-id"
GITHUB_CLIENT_SECRET = "your-github-client-secret"
GITHUB_CALLBACK_URL = "https://your-app.streamlit.app/github/callback"
```
