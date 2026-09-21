# GitHub setup for the Nemetron Cloud App

## Model side

Nemotron is used through API access, not through your Modal GPU.

Set these secrets for the model API:

- `OPENROUTER_API_KEY`
- `OPENROUTER_MODEL`

## Cloud GPU side

Use Modal GPU only for your app's GPU workloads.

Add these GitHub secrets:

- `MODAL_TOKEN_ID`
- `MODAL_TOKEN_SECRET`
- `MODAL_GPU`

Suggested `MODAL_GPU` values:

- Starter: `T4`
- Pro: `A10G`
- Elite: `A100`

## GitHub OAuth app

Add these too if your app connects with GitHub:

- `GITHUB_CLIENT_ID`
- `GITHUB_CLIENT_SECRET`
- `GITHUB_CALLBACK_URL`

## Deploy

Push to `main` or run the **Deploy Modal Worker** workflow manually.

The deployed Modal worker is for app-side cloud GPU tasks from `modal_app.py` and `gpu_tasks.py`.
