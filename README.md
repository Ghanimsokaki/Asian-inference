# ⚡ Asian Inference

AI dataset generator, model fine-tuner and community hub — your own private AI hub.

Chat with an assistant that answers questions about machine learning and generates
synthetic datasets on request, then turns any of them into a ready-to-run Google
Colab fine-tuning notebook.

The chat works with no model token configured — it falls back to built-in
answers about the platform rather than failing.

---

## Features

| Feature | Description |
|---|---|
| Dataset Chat | A general assistant: ask it anything about ML, datasets or training — and it generates datasets on request |
| Persistent memory | Optional Supabase-backed chat memory that survives new sessions |
| Model fine-tuner | Pick a base model → get a generated Colab training notebook |
| Apps builder | Generate Apache-2.0 app bundles with GitHub workflow files and Modal GPU worker templates |
| Dataset Hub | Browse, preview and download community datasets (CSV / JSON / JSONL) |
| Model Hub | Browse community models and run live inference |
| API keys | Your own `asi-` key, plus slots for third-party registry credentials |
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

```text
app.py              Streamlit pages — collect input, call core, render
core.py             Domain rules: accounts, plans, quotas, tokens, ownership
store.py            SQLite persistence (WAL, transactions, migrations)
config.py           Secrets, plans and constants — one source of truth
ui.py               Design tokens, components, navigation, HTML escaping
inference.py        Managed inference, dataset synthesis, Colab notebooks
hf_storage.py       Private remote registry storage (optional offsite mirror)
supabase_memory.py  Optional Supabase-backed persistent chat memory
supabase_backend.py Optional Supabase mirror for core app data and recovery
billing.py          Stripe checkout + Traakteer, with verified webhooks
webhook_server.py   Standalone HTTP endpoint for payment webhooks
tests/              pytest suite
```

`core` never imports Streamlit, so every rule is testable without a browser.

### Storage

**SQLite is the source of truth.** `asian_inference.db` holds users, datasets, models,
API keys, tickets, token history and billing events. It is created automatically on first
run, and a pre-existing `db.json` from an older version is imported once on startup.

When `MODEL_PROVIDER_TOKEN` is configured, dataset rows are also mirrored to a private
remote registry owned by the platform. If a user saves their own registry token in the
app, generation, inference and model provisioning can use that too.

When Supabase is configured, Dataset Chat remembers previous turns across sessions using
`supabase_memory.py`, and the app can also store its core product data there for better
durability. With `SUPABASE_PRIMARY_BACKEND = true`, Streamlit keeps the UI while Supabase
becomes the primary backend for users, datasets, models, API keys, tickets, token logs,
billing events and webhook claims.

On a fresh deploy with an empty local SQLite file, the app can restore users, datasets,
models, API keys, token logs, billing events and support tickets from Supabase
automatically.

Run `supabase_schema.sql` once in your Supabase SQL editor to create both the chat memory
table and the backend tables.

> **Note on hosting:** Streamlit Community Cloud gives each app an ephemeral filesystem, so
> the local database does not survive a redeploy there. For durable local data, run the app
> somewhere with a persistent disk and point `DATA_DIR` at it.

---

## Running locally

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

The app works with no secrets at all: sign up, chat, browse and manage your account.
Dataset generation and managed inference need a registry token; paid plans need Stripe or
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
SECRET_KEY = "a long random string"                # required in production
MODEL_PROVIDER_TOKEN = "..."                      # inference + offsite storage
ADMIN_EMAIL = "you@example.com"                   # who gets the admin panel

# Optional — persistent chat memory
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = "..."
SUPABASE_SCHEMA = "public"
SUPABASE_CHAT_TABLE = "chat_memories"
SUPABASE_APP_PREFIX = "ai"
SUPABASE_PRIMARY_BACKEND = true

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
AUTH_COOKIE_NAME = "asian_inference_session"
AUTH_SESSION_PERMANENT = true
PERMANENT_SESSION_DAYS = 36500
# AUTH_SESSION_DAYS = 180  # only when AUTH_SESSION_PERMANENT = false
MUSIC_URL  = "https://example.com/ambient.mp3"
```

| Secret | Effect when missing |
|---|---|
| `SECRET_KEY` | A placeholder is used and the admin panel warns. Set it in production. |
| `MODEL_PROVIDER_TOKEN` | Generation and managed inference are unavailable unless the user saves their own registry token in API Keys. Datasets still save locally. |
| `SUPABASE_*` | Chat memory becomes session-only, and the Supabase-backed primary/mirror backend is disabled. |
| `SUPABASE_PRIMARY_BACKEND` | When `true`, core app reads prefer Supabase while SQLite remains a local fallback/cache. |
| `AUTH_COOKIE_NAME` / `AUTH_SESSION_DAYS` | The cookie name and legacy finite-session lifetime (when `AUTH_SESSION_PERMANENT = false`). |
| `AUTH_SESSION_PERMANENT` / `PERMANENT_SESSION_DAYS` | Defaults to permanent saved sign-ins with a far-future database expiry. Cookies are capped at 400 days and renewed on visits; browser privacy policies (e.g. Safari ITP) may expire them sooner. Signing out and password changes revoke sessions. |
| `STRIPE_*` / `TRAAKTEER_SECRET` | Paid upgrade buttons are disabled rather than linking to a checkout whose payment could never be credited. |
| `ADMIN_EMAIL` | Falls back to the built-in default. |

Install `stripe` (commented out in `requirements.txt`) only if you use Stripe Checkout.

---

## Supabase setup

1. Create a Supabase project.
2. Open the SQL editor and run `supabase_schema.sql`.
3. Add `SUPABASE_URL` and a key to top-level Streamlit secrets (or environment). Accepted names in priority order: `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_SECRET_KEY`, `SUPABASE_ANON_KEY`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_KEY`. The generic name is the last fallback.
4. Set `SUPABASE_PRIMARY_BACKEND = true` if you want Supabase to be the main backend.
5. Restart the app.

Modern `sb_secret_` / `sb_publishable_` keys must be sent as `apikey` headers,
not as `Authorization: Bearer` JWTs. Legacy service-role / anon JWT keys can use
both headers. Never expose a secret key to browser code.

Using the service-role key is recommended because the Streamlit backend writes memory
and mirrored app data server-side. If you choose to use an anon/publishable key instead, reads and writes are subject
to row-level security (RLS) on both chat and app tables. A successful 200 [] read
does not prove a write persisted. See the commented Case 1 / Case 2 guidance at
the end of `supabase_schema.sql`; it does not modify policies when re-run.

`.streamlit/secrets.toml.example` lists the settings; copy it to
`.streamlit/secrets.toml` and fill it in. Place keys at the TOML top level, before
any `[section]` header. A malformed file is called out with its error line.

Run `python scripts/check_supabase.py` to see each setting's source without printing
credentials. Use `python scripts/check_supabase.py --write-test` to insert, read back
and delete disposable probe rows in chat memory and app sessions. It uses the reserved
`__diagnostic__@asian-inference.invalid` address and may create a temporary app user
to satisfy the session foreign key; check cleanup warnings. Do not use that address
for real accounts.

### Reading the Supabase banners

The admin panel and the dashboard pills report three different states, so the wording
tells you where to look:

| Banner | Meaning | Fix |
|---|---|---|
| `… is not configured` | `SUPABASE_URL` and/or a key are missing — an unedited template value counts as missing | Add the settings and restart the app (reboot it on Streamlit Cloud) |
| `… could not be reached` | Settings are present but the host did not answer | Check the project URL and outbound network access |
| `… rejected the configured credentials` | Supabase answered HTTP 401/403 | For secret/service-role keys, check the project and key; for anon/publishable keys, inspect RLS policies |
| `… request failed (HTTP …)` | Supabase answered with a non-auth error; check the status code and table/schema, without logging secrets | Check table name, schema and project status |
| `… tables are missing` | The project is reachable but `supabase_schema.sql` was never run | Run it once in the SQL editor |

Chat memory and the mirrored backend are both optional: the app keeps running on
session-only chat and the local SQLite database when they are switched off.

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
5. Run all. The notebook prompts for your repository access token at runtime — it is never
   written into the file.

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
