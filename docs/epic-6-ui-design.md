# Epic 6 — Web UI Design

Design for the single-user review web app (the front end over Epics 1–5).
Stack per `CLAUDE.md`: **FastAPI + Jinja2 + HTMX + Tailwind, no JS build**.
This doc precedes implementation; `docs/` plans drive the build.

## Principles
- **Single-user, local, no login.** No auth screen; the app trusts the local
  operator. (Multi-user is explicitly out of scope.)
- **Server-rendered + HTMX.** Pages are Jinja2 templates; interactions swap HTML
  **fragments** returned by the server — no client-side JSON templating, no JS
  build step.
- **Pilot-first.** The dashboard is a review queue: nothing leaves without an
  explicit action. Sending itself is **Epic 7** — Epic 6 wires the buttons and
  implements review/edit/approve/discard state; the actual Gmail send lands in
  E7.
- **Responsive.** Tailwind utility classes; usable on phone and desktop.
- **Honest states.** Every list/panel has empty / loading / error states.

## Tech choices
- **Templates:** `Jinja2Templates` (FastAPI), templates in `app/templates/`.
- **HTMX:** via CDN `<script>` in `base.html` (`hx-get/post`, `hx-swap`,
  `hx-target`, `hx-trigger`). No bundler.
- **Tailwind:** Play CDN for the MVP (no build). *Note:* fine for a local
  single-user tool; switch to a precompiled stylesheet if this is ever hosted.
- **Fragments over JSON for the UI.** The existing JSON routes (`/kb`, `/sync`,
  `/auth/*`) remain the programmatic API + test surface; the UI calls **new
  HTML-fragment routes** so HTMX can swap markup directly.

---

## Pages (information architecture)

A shared `base.html` provides the top nav (Dashboard · Knowledge Base ·
Settings) and a global **status bar** (Gmail connection + reply mode + "Sync
now").

### 1. Dashboard (`GET /`)
The email review queue — the core screen.

```
┌───────────────────────────────────────────────────────────────┐
│ RAG Mail Auto-Reply      [Dashboard] Knowledge  Settings         │
│ Gmail: me@example.com ✓   Mode: PILOT   [ Sync now ]  synced 2m ago│
├───────────────────────────────────────────────────────────────┤
│ Filters: [All] [Drafted] [Needs human] [Skipped] [Sent]          │
├───────────────────────────────────────────────────────────────┤
│ ▸ alice@acme.com — "Pricing question"        DRAFTED  conf 0.88  │
│     Draft: "Our standard plan is …"                              │
│     Sources: faq.pdf (0.91), pricing.txt (0.84)                  │
│     [ Approve & Send ]  [ Edit ]  [ Discard ]                    │
│ ─────────────────────────────────────────────────────────────  │
│ ▸ bob@x.com — "Refund?"                       NEEDS_HUMAN         │
│     (no confident answer — flagged for review)                   │
│ ─────────────────────────────────────────────────────────────  │
│ ▸ news@list.com — "Weekly digest"             SKIPPED (list)     │
└───────────────────────────────────────────────────────────────┘
```

**Each card shows:** sender, subject, status badge, triage category; for
drafted items: the AI reply, cited sources (name + score), confidence. Actions
depend on status (below).

**Per-status actions**
| Status | Actions |
| --- | --- |
| `drafted` | Approve & Send · Edit · Discard |
| `needs_human` | View · Discard (and, post-E7, "Write manually") |
| `skipped` | View (reason); collapsed by default |
| `approved`/`sent` | View (read-only); `sent` shows timestamp |
| `error` | View error · Re-queue (reset to `pending`) |

**Interactions (HTMX)**
- **Filter tabs** → `hx-get="/emails?status=…"` swaps the list fragment.
- **Expand a card** → `hx-get="/emails/{id}"` loads the detail fragment
  (full email body + thread context + editable draft).
- **Edit** → inline `<textarea>`; **Save** `hx-post="/emails/{id}/reply"` →
  returns the updated card.
- **Approve & Send** → `hx-post="/emails/{id}/approve"` → updated card. (E6
  marks `approved`; E7 performs the Gmail send and flips to `sent`.)
- **Discard** → `hx-post="/emails/{id}/discard"` → updated card.
- **Sync now** → `hx-post="/actions/sync"` → swaps the status bar with the run
  summary; queue auto-refreshes.
- **Live-ish refresh** → the list polls `hx-get="/emails" hx-trigger="every
  15s"` (cheap; single-user).

### 2. Knowledge Base (`GET /knowledge`)
Manage what the assistant can answer from.

```
┌───────────────────────────────────────────────┐
│ Add knowledge                                    │
│  ( ) Upload file [Choose: pdf/docx/txt] [Add]    │
│  ( ) Paste text  [label____] [textarea] [Add]    │
├───────────────────────────────────────────────┤
│ Sources                          (12 chunks)     │
│  faq.pdf            file   8 chunks   [Delete]   │
│  pricing.txt        paste  4 chunks   [Delete]   │
└───────────────────────────────────────────────┘
```
- **Upload** → `hx-post="/knowledge/upload"` (multipart) → returns the sources
  table fragment + a toast (chunks added / unsupported-type error).
- **Paste** → `hx-post="/knowledge/paste"`.
- **Delete** → `hx-post="/knowledge/{source}/delete"` (POST, since HTML forms
  don't DELETE) → updated table.
- Shows per-source chunk counts; namespace is hidden in the MVP (always
  `default`) but the column is ready for the future multi-stream UI.

### 3. Settings (`GET /settings`)
```
┌───────────────────────────────────────────────┐
│ Gmail            me@example.com ✓  [Disconnect] │
│                  (or: Not connected [Connect])  │
├───────────────────────────────────────────────┤
│ Reply mode       (•) Pilot   ( ) Auto           │
│ Confidence gate  [▮▮▮▮▮▯▯] 0.75                  │
│ Auto-send rules  keywords/categories (Auto only)│
│                                      [ Save ]    │
└───────────────────────────────────────────────┘
```
- **Connect** links to existing `GET /auth/gmail/connect`; **Disconnect** →
  `hx-post` wrapper around `/auth/gmail/disconnect` → updated panel.
- **Save** → `hx-post="/settings"` updates `reply_mode`,
  `confidence_threshold`, `auto_send_rules` via the settings repo → returns the
  form fragment with a "saved" indicator.
- Auto-send rule fields are disabled unless mode = Auto (guards still apply at
  send time in E7).

---

## Route map (Epic 6 additions)

All render HTML (full pages or fragments) and call existing repos/services.

| Method & path | Purpose | Backed by |
| --- | --- | --- |
| `GET /` | Dashboard page | emails + replies repos |
| `GET /emails` | Queue list fragment (`?status=` filter) | `emails.list_emails` |
| `GET /emails/{id}` | Email detail fragment (body, thread, draft) | emails + replies |
| `POST /emails/{id}/reply` | Save edited draft text | `replies.update_reply` |
| `POST /emails/{id}/approve` | Mark approved (E7 sends) | replies/emails repos |
| `POST /emails/{id}/discard` | Discard draft / skip email | replies/emails repos |
| `POST /emails/{id}/requeue` | Reset `error`→`pending` | `emails.update_status` |
| `GET /knowledge` | KB page | `knowledge.list_sources` |
| `POST /knowledge/upload` | Ingest file → sources fragment | `rag.ingest` |
| `POST /knowledge/paste` | Ingest text → sources fragment | `rag.ingest` |
| `POST /knowledge/{source}/delete` | Delete source → fragment | `knowledge.delete_by_source` |
| `GET /settings` | Settings page | `settings.get_settings_row` |
| `POST /settings` | Save settings → form fragment | `settings.update_settings` |
| `POST /actions/sync` | Trigger cycle → status-bar fragment | `scheduler.service.run_once` |
| `GET /partials/status-bar` | Status bar fragment (poll) | settings + `sync.status` |

**Reused as-is:** `GET /auth/gmail/connect`, `/callback`, `POST
/auth/gmail/disconnect`, `POST /sync/now`, `GET /sync/status`, and the JSON
`/kb/*` API (kept for programmatic use + existing tests).

---

## Templates layout
```
app/templates/
├── base.html              # nav, status bar, HTMX + Tailwind includes
├── dashboard.html
├── knowledge.html
├── settings.html
└── partials/
    ├── email_list.html    # the queue (list of cards)
    ├── email_card.html    # one email + draft + actions
    ├── email_detail.html  # expanded body/thread/editable draft
    ├── kb_sources.html     # KB sources table
    ├── settings_form.html
    └── status_bar.html
app/static/                # (optional) small css/js if needed later
```
Action endpoints return the **smallest** fragment that changed (a single
`email_card`, the `kb_sources` table, the `settings_form`) so HTMX swaps are
minimal.

## States & feedback
- **Empty:** dashboard "No emails yet — connect Gmail and Sync now"; KB "No
  knowledge yet — upload a file or paste text".
- **Loading:** HTMX `hx-indicator` spinner on buttons/sync.
- **Error:** unsupported upload type → inline message (maps the existing 415);
  failed action → toast; email `error` status surfaced with the message.
- **Confidence** shown as a value + colored badge (≥ threshold green, below
  amber).

## Accessibility / responsive
- Semantic headings, labelled form controls, focus styles, adequate contrast.
- Single-column stacked cards on mobile; two-column (list + detail drawer) on
  wide screens.

## Testing approach (Epic 6)
- `TestClient` GET each page → 200 + key markers (HTMX isn't executed, so we
  assert the returned HTML/fragments, not browser behavior).
- Action endpoints → correct fragment + persisted state via repos (provider
  overridden offline for KB ingest, as in the existing KB route tests).
- Reuse the temp-DB `client` fixture (scheduler disabled).

## Scope boundaries (MVP UI)
- No login/multi-user; no multi-stream management screen (namespace stays
  `default`, column reserved); no analytics. The **send** action's behavior is
  delivered by Epic 7 — Epic 6 ships the queue, review/edit/approve/discard,
  KB management, and settings.

## Open decisions (sensible defaults chosen; flag if you disagree)
- **Tailwind Play CDN** vs precompiled CSS → CDN for MVP (no build).
- **Queue polling interval** → 15s default.
- **"Approve & Send" in Pilot before E7** → marks `approved` and shows
  "queued to send"; E7 turns that into an actual Gmail send.
