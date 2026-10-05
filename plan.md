# Community Agent Web Surface

## Product direction
A web-first community bot for fast, safe conversations: onboarding, supported intents, context-aware follow-ups, useful actions, safe fallback, human escalation, moderation controls, analytics, and polished loading/empty/error/recovery states.

## Design
- **Movement:** Dark control-room minimalism with a warm editorial accent.
- **Principles:** Calm hierarchy, visible safety boundaries, fast scanning, conversational warmth.
- **Color philosophy:** Ink surfaces reduce distraction; amber marks user intent/actions; cyan marks live/system state; violet marks agent intelligence; green signals safe completion.
- **Layout paradigm:** Persistent left rail + single conversation stage + contextual right rail rather than dashboard tiles.
- **Signature elements:** Agent constellation mark, status pills, confirmation gates for risky actions.
- **Interaction:** One-click intents, inline clarifying questions, explicit confirmation before risky work, human handoff always visible.
- **Animation:** Subtle glow/pulse for live state, short slide/fade for messages and panels; no distracting loops.
- **Typography:** Bricolage Grotesque for display, IBM Plex Sans for UI, IBM Plex Mono for technical metadata.
- **Brand essence:** A safety-first community operator that helps members get unstuck quickly without pretending to be human. Personality: calm, capable, accountable.
- **Voice:** “Tell me what you’re trying to ship.” / “I can prepare that, but I need your approval before I take a risky action.”
- **Wordmark:** “orbit / community agent” with a four-node orbit mark.
- **Signature color:** Warm amber #ffb454.

## Implementation
- Add `web/index.html`, `web/styles.css`, and `web/app.js` as a self-contained static prototype.
- Add `web/server.py` for local preview on ChromeOS/Linux and document runtime configuration in `web/.env.example`.
- Keep NVIDIA NIM / GLM configuration server-side via environment variables; the static demo uses deterministic local fallback responses until the secret is supplied.
- Treat GitHub and computer control as connectors with permission scopes. Dangerous or irreversible actions always create an approval card before execution.
- Include route manifest at `web/manus-routes.json`.
