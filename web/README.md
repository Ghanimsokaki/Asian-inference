# Orbit / Community Agent

A responsive, web-first prototype for a welcome and moderation agent. It is intentionally safe by default: connector actions are permissioned, and risky actions show an approval gate before anything happens.

## Run locally

```bash
python3 web/server.py
```

Open `http://127.0.0.1:5173` in ChromeOS Chrome, Linux, or any modern browser.

## Runtime configuration

Copy `.env.example` into your deployment secret store. Add the NVIDIA NIM key later; do not place it in browser JavaScript. The UI currently uses deterministic fallback replies so onboarding and recovery states work without a model secret.

## Scope

- Welcome/onboarding flows with context-aware follow-up questions
- Supported intents and quick sample responses
- Moderation review, human escalation, connector permissions, and approval gates
- Basic room pulse and recent activity analytics
- Loading, empty, fallback, error-safe, and recovery states
- GitHub, NVIDIA NIM, and ChromeOS control connector placeholders
