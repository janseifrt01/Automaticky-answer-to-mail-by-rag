# Epic 7 — Sending: Pilot Drafts, Gated Auto-Send & Hardening — Detailed Plan

Detailed plan for Epic 7 — the **only** epic that actually transmits mail.
Builds on Epics 0–6. Turns the dashboard's "Approve & Send" into a real Gmail
send and adds **gated Auto-send** to the cycle, while preserving the safety
guarantees in `CLAUDE.md`.

**Goal:** send a reviewed reply (Pilot) or auto-send a qualifying one (Auto),
correctly threaded, idempotently, through the `MailProvider` facade — with a
native Gmail draft as the Pilot safety net.

**Definition of done:** "Approve & Send" sends the current (possibly edited)
reply via Gmail with correct threading and flips the email to `sent`; Auto mode
sends only when every gate passes; nothing sends twice; tests cover the gate
matrix and threading offline.

---

## Safety guarantees (mapping to `CLAUDE.md`)
| Guarantee | How Epic 7 honors it |
| --- | --- |
| **Pilot by default; nothing sent without explicit action** | Sending only happens on the user's "Approve & Send" click, or in Auto mode when all gates pass. |
| **Gated Auto-send** | Auto requires: `reply_mode == auto` **and** triage `answerable` **and** `confidence ≥ threshold` **and** model `should_send` **and** safe-sender guards passed **and** (if set) `auto_send_rules` match. |
| **Safe-sender / loop prevention** | Already enforced upstream (E4 guards); only guard-survivors ever reach a draft, so only they can be sent. |
| **Idempotency** | Send only when email status ∈ {`drafted`,`approved`}; set `sent` immediately on success. A `sent` email is never re-sent. |
| **Native Gmail drafts as the safety net** | In Pilot, the cycle creates a Gmail draft (visible/sendable in Gmail too). |
| **Minimal scopes / tokens encrypted / no secrets logged** | Scopes already minimal (E2); tokens encrypted (E2); E7 adds a logging audit to ensure no token/PII is logged. |

---

## Design

### Reply builder (`app/mail/sender.py`)
`build_outgoing(email, reply) -> OutgoingMessage`:
- `to` = address parsed from `email["sender"]` (`email.utils.parseaddr`).
- `subject` = `email["subject"]` prefixed with `Re: ` (unless already present).
- `body_text` = `reply["reply_text"]` (the **current** text, post-edit).
- `thread_id` = `email["thread_id"]`.
- `in_reply_to` = `email.headers["message-id"]`.
- `references` = `email.headers["references"]` (split) + the message-id.

These map straight onto the `OutgoingMessage` Epic 2 already defined and the
`In-Reply-To`/`References`/`threadId` wiring Epic 2's `GmailProvider` already
emits — so threading is correct by construction.

### Facade addition: `delete_draft`
Add `delete_draft(draft_id)` to `MailProvider` + `GmailProvider`/`GmailClient`
(Gmail `drafts().delete`) + the test `FakeMailProvider`. Lets us discard a stale
Pilot draft after sending fresh text. (Completes the create/send/send_draft set.)

### Send service (`app/mail/sender.py`)
- `create_gmail_draft(conn, provider, email, reply)` — `provider.create_draft`;
  store the returned id in `replies.gmail_draft_id`.
- `send_reply(conn, provider, email, reply) -> str` — **idempotent**:
  - if email status == `sent`: no-op, return existing.
  - else `provider.send(build_outgoing(...))` using current text; on success set
    `replies.status='sent'`, `emails.status='sent'`; best-effort
    `delete_draft(gmail_draft_id)` if present. Errors propagate to the caller to
    surface (UI message / cycle error count); status stays `drafted` on failure.
- `should_auto_send(email, reply, settings) -> bool` — the Auto gate above
  (pure function; testable as a matrix).

### Where sending happens (thread-safety, again)
Gmail/httplib2 is **not thread-safe**, so all sends are **sequential**:
- **UI "Approve & Send"** (`POST /emails/{id}/approve`) runs in one request
  thread → one `send_reply` call. Safe.
- **Auto-send in the cycle** happens in a new **sequential dispatch phase**
  *after* the concurrent `process_email` phase (which stays mail-agnostic):
  ```
  run_cycle: … concurrent process_email …            (E4/E5, unchanged)
             └─ SEQUENTIAL dispatch (E7):
                  for each freshly drafted email+reply:
                    if reply_mode==auto and should_auto_send(...):
                        send_reply(...)            → summary.sent++
                    elif create_gmail_drafts:        # Pilot safety net
                        create_gmail_draft(...)
  ```
  This reuses the exact pattern that made E5 safe: LLM concurrent, mail
  sequential.

### Config (`app/config.py`)
| Field | Default | Purpose |
| --- | --- | --- |
| `create_gmail_drafts` | `true` | Pilot: create a native Gmail draft per reply (safety net) |
| (existing) `reply_mode`, `confidence_threshold`, `auto_send_rules` | — | drive the Auto gate |

### UI changes (`app/routers/web.py` + `email_card.html`)
- `POST /emails/{id}/approve` → builds the mail provider, calls `send_reply`;
  on success returns the card in **`sent`** state; if not connected or send
  fails, returns the card with an inline error and status unchanged.
- Card gains a `sent` state ("sent ✓", read-only) and surfaces send errors.

---

## Task breakdown

### 7.0 (P0) Reply builder
`build_outgoing` with address parsing + `Re:`/threading headers. **Acceptance:**
recipient, subject prefix, `in_reply_to`/`references`/`thread_id` correct
(including no double `Re:`).

### 7.1 (P0) `delete_draft` on the facade
Protocol + Gmail client/provider + FakeMailProvider. **Acceptance:** Gmail
`drafts().delete` called; fake records deletions.

### 7.2 (P0) Send service
`create_gmail_draft`, `send_reply` (idempotent), `should_auto_send`.
**Acceptance:** send marks `sent` + records; second `send_reply` is a no-op;
gate matrix returns expected booleans.

### 7.3 (P0) Pilot Gmail draft creation in the cycle
Sequential dispatch creates a Gmail draft per drafted reply when
`create_gmail_drafts` and mode is Pilot. **Acceptance:** with a FakeMailProvider,
drafts are recorded and ids stored; no sends happen in Pilot.

### 7.4 (P0) Gated Auto-send in the cycle
Sequential dispatch sends qualifying replies in Auto mode; summary gains a
`sent` count. **Acceptance:** Auto + all gates → sent; any gate failing →
left `drafted` (falls back to Pilot review).

### 7.5 (P0) UI "Approve & Send"
Wire the route to `send_reply`; `sent` state + error handling.
**Acceptance:** approve on a drafted email → `sent` (FakeMailProvider records
it); not-connected → inline error, still `drafted`.

### 7.6 (P1) Hardening
- Logging audit: ensure no tokens/credentials/PII are logged (review
  `logger.*` calls; redact where needed).
- Confirm send idempotency under a repeated cycle (status guard).
- Document the minimal-scope + encrypted-token posture in the README.

### 7.7 (P1) Tests
Reply builder threading; `delete_draft`; send idempotency; auto-send gate
matrix (mode/confidence/should_send/triage/rules); cycle dispatch (Pilot draft
vs Auto send); UI approve→sent + not-connected error. All offline with
`FakeMailProvider`.

---

## Risks / decisions
- **Send-then-persist gap.** If `provider.send` succeeds but the DB status
  update fails, a later cycle could resend. Mitigation: send only `drafted`
  emails and update status immediately; the window is tiny and single-user.
  (A fully transactional outbox is overkill for v1 — noted for later.)
- **Stale Pilot Gmail draft after an edit.** We always send the *current* text
  via `provider.send` (not `send_draft`), then best-effort `delete_draft`, so
  edits are never lost and stale drafts are cleaned up.
- **Auto-send blast radius.** Auto stays opt-in (`reply_mode=auto`) and is
  double-gated by the model's `should_send` **and** the confidence threshold
  **and** optional keyword rules; default remains Pilot.
- **httplib2 thread-safety.** All sends sequential (UI request thread or the
  cycle's dispatch phase) — never inside the concurrent workers.

## Definition of done checklist (Epic 7)
- [ ] `build_outgoing` with correct recipient + `Re:` + threading headers.
- [ ] `delete_draft` across facade + Gmail + fake.
- [ ] `send_reply` idempotent; `create_gmail_draft`; `should_auto_send` gate.
- [ ] Cycle dispatch: Pilot drafts vs gated Auto-send; `sent` in the summary.
- [ ] UI "Approve & Send" sends + `sent` state + error handling.
- [ ] Hardening: no secrets logged; idempotency confirmed.
- [ ] `pytest` green offline (threading, gate matrix, dispatch, UI).
