# ✦ Gemby Platform

AI dataset generator + model fine-tuner + community hub.
Similar to HuggingFace — browse, share, train, deploy.

---

## Features

| Feature | Description |
|---|---|
| Dataset Generator | Describe your data, Gemby Agent 3B builds it row by row |
| Model Fine-tuner | Pick a base model → auto-generates Google Colab training notebook |
| Dataset Hub | Browse & download community datasets (CSV / JSON / JSONL) |
| Model Hub | Browse community models, run live inference |
| API Keys | Generate your Gemby API key and manage optional external keys |
| Plans | Starter (free) / Pro $9.99 / Elite $29.99 via Traakteer |
| Admin Panel | Full control: users, datasets, models, tickets, tokens |

---

## Slot limits (like HuggingFace private repo limits)

| Plan | Datasets | Models | Total |
|---|---|---|---|
| Starter (free) | 2 | 2 | 4 |
| Pro ($9.99/mo) | 6 | 6 | 12 |
| Elite ($29.99/mo) | ∞ | ∞ | ∞ |

---

## Deploy to Streamlit Cloud

### Step 1 — Create a private GitHub repo
Go to https://github.com/new → name it `gemby-platform` → Private → Create.

### Step 2 — Upload these files (keep the structure)
```
gemby-platform/
├── app.py
├── core.py
├── hf_storage.py
├── ui.py
├── inference.py
├── requirements.txt
├── .gitignore
├── README.md
└── .streamlit/
    ├── config.toml
    └── secrets.toml   ← DO NOT upload this (blocked by .gitignore)
```

### Step 3 — Deploy
1. Go to https://share.streamlit.io
2. New app → select your repo → branch: main → file: app.py
3. Click Advanced settings → paste secrets (see below)
4. Deploy!

### Step 4 — Add secrets in Streamlit Cloud
App Settings → Secrets → paste:
```toml
HF_TOKEN = "hf_your_new_huggingface_token"
TRAAKTEER_SECRET = "your_traakteer_secret"
SECRET_KEY = "any_long_random_string_32plus_chars"
```

---

## Admin account
Register with **emir.erningpraja@gmail.com** to get:
- Automatic Elite plan (unlimited slots & tokens)
- 👑 Admin Panel in the sidebar
- Full control over all users, datasets, models, tickets, tokens

---

## Google Colab training flow
1. User creates a model in "My Models"
2. Platform auto-generates a `.ipynb` Colab notebook
3. User downloads it, opens in https://colab.research.google.com
4. Selects T4 GPU (free) → Run All
5. Model trains with LoRA fine-tuning and pushes to platform-managed Hugging Face storage
6. The model is now live and can be used for inference on Gemby Platform

## Storage architecture

Users never need to create or manage a model repository. Dataset payloads and trained model
artifacts are stored in private Hugging Face Hub repositories managed by the platform; the
application database keeps only lightweight metadata and opaque object paths. Configure the
server-side `HF_TOKEN` secret with a Hugging Face write token. Do not expose that token in the
Streamlit UI or commit it to the repository.

Storage follows the subscription plan limits: Starter allows 2 datasets and 2 model artifacts,
Pro allows 6 of each, and Elite has effectively unlimited slots. Dataset row limits are enforced
server-side as 50, 2,000, and 50,000 rows respectively. Each model slot receives its own private,
platform-managed Hugging Face repository, while a user’s datasets share a private platform
dataset repository. If Hugging Face storage is unavailable, the operation fails cleanly and no
local-only artifact is created.

---

## Traakteer billing setup
1. Create plans in Traakteer dashboard with IDs: `plan_pro_monthly`, `plan_elite_monthly`
2. Webhook URL: `https://your-app.streamlit.app/traakteer-webhook`
3. Copy the webhook signing secret into Streamlit Secrets as `TRAAKTEER_SECRET`

---

## Anti-cheat & security
- Passwords: SHA-256 hashed with secret key
- Tokens: every change logged with timestamp + reason
- Rate limits: 3 generations/min, 10 logins/min, 5 inference calls/min
- Max single token grant: 100,000
- Auto-flag: >5 manual grants in 1 hour
- Webhook HMAC: forged Traakteer events return 401
- API keys: masked in UI, only shown once on creation
- Plan limits enforced server-side (not just UI)
