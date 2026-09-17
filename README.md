# ⚡ Asian Inference

AI dataset generator, model fine-tuner and community hub — like Hugging Face, but yours.

Chat with an assistant that answers questions about machine learning and generates
synthetic datasets on request, then turns any of them into a ready-to-run Google
Colab fine-tuning notebook.

The chat works with no inference token configured — it falls back to built-in
answers about the platform rather than failing.

---

## Features

| Feature | Description |
|---|---|
| Dataset Chat | A general assistant: ask it anything about ML, datasets or training — and it generates datasets on request |
| Model fine-tuner | Pick a base model → get a generated Colab training notebook |
| Dataset Hub | Browse, preview and download community datasets (CSV / JSON / JSONL) |
| Model Hub | Browse community models and run live inference |
| API keys | Your own `asi-` key, plus slots for third-party credentials |
| Account | Change your password, review token history and billing events |
| Admin panel | Users, datasets, models, tickets, token grants and config diagnostics |

## Plans

| Plan | Tokens/month | Rows per dataset | Datasets | Models | API keys | Public sharing |
|---|---|---|---|---|---|---|
| 🆓 Starter (free) | 500 | 50 | 2 | 2 | 1 | ✗ |
| ⚡ Pro ($9.99/mo) | 15,000 | 2,000 | 6 | 6 | 5 | ✓ |
| 👑 Elite ($29.99/mo) | 999,999 | 50,000 | Unlimited | Unlimited | Unlimited | ✓ |

Each generated row costs **10 tokens**. Tokens are charged only after rows are generated
successfully, and refunded automatically if saving then fails.

---

## Architecture

```
app.py              Streamlit pages — collect input, call core, render
core.py             Domain rules: accounts, plans, quotas, tokens, ownership
store.py            SQLite persistence (WAL, transactions, migrations)
config.py           Secrets, plans and constants — one source of truth
ui.py               Design tokens, components, navigation, HTML escaping
inference.py        Hugging Face inference, dataset synthesis, Colab notebooks
hf_storage.py       Private Hugging Face Hub storage (optional offsite mirror)
billing.py          Stripe checkout + Traakteer, with verified webhooks
webhook_server.py   Standalone HTTP endpoint for payment webhooks
tests/              pytest suite
```

`core` never imports Streamlit, so every rule is testable without a browser.

### Storage

**SQLite is the source of truth.** `asian_inference.db` holds users, datasets, models,
API keys, tickets, token history and billing events. It is created automatically on first
run, and a pre-existing `db.json` from an older version is imported once on startup.

When `HF_TOKEN` is configured, dataset rows are **also** mirrored to a private Hugging Face
dataset repository owned by the platform, and each model gets its own private model repo.
Users never see or manage a repository. If the mirror is unavailable the dataset still
saves and is recorded as `local` — the Admin panel shows the connection status.

> **Note on hosting:** Streamlit Community Cloud gives each app an ephemeral filesystem, so
> the database does not survive a redeploy there. For durable data, run the app somewhere
> with a persistent disk and point `DATA_DIR` at it.

---

## Running locally

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

The app works with no secrets at all: sign up, chat, browse and manage your account.
Dataset generation needs an inference token (`HF_TOKEN`); paid plans need Stripe or
Traakteer credentials.

### Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

---

## Configuration

All settings are read from Streamlit secrets first, then environment variables.
Create `.streamlit/secrets.toml` locally (it is gitignored) or paste into
**App settings → Secrets** on Streamlit Cloud:

```toml
SECRET_KEY = "a long random string"       # required in production
HF_TOKEN   = "hf_..."                     # inference + offsite storage
ADMIN_EMAIL = "you@example.com"           # who gets the admin panel

# Optional — card payments
STRIPE_SECRET_KEY     = "sk_live_..."
STRIPE_WEBHOOK_SECRET = "whsec_..."
STRIPE_PRICE_PRO      = "price_..."
STRIPE_PRICE_ELITE    = "price_..."

# Optional — Traakteer fallback
TRAAKTEER_SECRET = "..."

# Optional
PUBLIC_URL = "https://your-app.streamlit.app"
DATA_DIR   = "/var/lib/asian-inference"
MUSIC_URL  = "https://example.com/ambient.mp3"
```

| Secret | Effect when missing |
|---|---|
| `SECRET_KEY` | A placeholder is used and the admin panel warns. Set it in production. |
| `HF_TOKEN` | Generation and inference are unavailable; datasets save locally only. |
| `STRIPE_*` / `TRAAKTEER_SECRET` | Paid upgrade buttons are disabled rather than linking to a checkout whose payment could never be credited. |
| `ADMIN_EMAIL` | Falls back to the built-in default. |

Install `stripe` (commented out in `requirements.txt`) only if you use Stripe Checkout.

---

## Payment webhooks

Streamlit serves a single app and cannot expose extra routes, so webhooks are handled by a
separate process:

```bash
python webhook_server.py --port 8787
```

| Route | Provider | Signature header |
|---|---|---|
| `POST /stripe` | Stripe | `Stripe-Signature` |
| `POST /traakteer` | Traakteer | `X-Traakteer-Signature` |
| `GET /health` | — | — |

Both handlers verify the signature **before** touching an account, and event ids are
recorded so a replayed webhook cannot grant tokens twice.

---

## Training flow

1. **My Models → Create & fine-tune** — name your model, pick a base model and a dataset.
2. Download the generated `.ipynb`.
3. Open it at [colab.research.google.com](https://colab.research.google.com).
4. Runtime → Change runtime type → **T4 GPU** (free tier).
5. Run all. The notebook prompts for your Hugging Face token at runtime — it is never
   written into the file — then LoRA fine-tunes and pushes the weights.

---

## Security

- **Passwords** — PBKDF2-HMAC-SHA256, 240,000 iterations, unique per-user salt. Accounts
  created under the old unsalted scheme are re-hashed transparently on next sign-in.
- **Output escaping** — all user-supplied text is HTML-escaped before rendering; chat
  bubbles render a safe Markdown subset only.
- **Authorisation** — ownership is checked in the domain layer on every delete and
  visibility change, and admin rights are re-derived from the account on each run.
- **Webhooks** — signatures verified, events deduplicated.
- **Rate limits** — sign-in 10/min, sign-up 5/min, generation 3/min, inference 5/min,
  tickets 3/min, enforced transactionally.
- **Token grants** — clamped, fully audited, and more than 5 manual grants an hour flags
  the account automatically.
- **Secrets** — never rendered in the UI, never written into generated notebooks.
