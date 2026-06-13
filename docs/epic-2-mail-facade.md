# Epic 2 — Mail Integration (Provider Facade) — Detailed Plan

Detailed, implementation-ready plan for Epic 2 of the MVP backlog
(`BACKLOG.md`). Builds on Epics 0–1. Architecture per `CLAUDE.md`: local
single-user, Python, stdlib `sqlite3`, OpenAI; mail via **Gmail (OAuth2)**.

**Reframing (this plan supersedes the Gmail-specific wording of Epic 2 in
`BACKLOG.md`):** mail access is hidden behind a provider-agnostic **`MailProvider`
facade** for *receiving* and *sending*. **Gmail (OAuth2)** is the only
implementation shipped in v1; a future Outlook/IMAP provider is a new class
implementing the same interface — callers (scheduler, RAG pipeline, UI) never
import Gmail directly. This mirrors the existing `VectorStore` and LLM
`Provider` abstractions.

**Goal of Epic 2:** the `MailProvider` interface + provider-agnostic domain
models, a Gmail implementation (OAuth2 connect/refresh, incremental receive,
send + draft with correct threading), encrypted credential storage, and an
idempotent "sync once" ingestion service — all unit-tested with a fake provider
and a mocked Gmail client. **No scheduling here** (that's Epic 5); Epic 2
exposes a callable `sync_once()`.

**Definition of done**
- `MailProvider` protocol + domain models (`EmailMessage`, `OutgoingMessage`,
  `SyncResult`) with no Gmail types leaking across the boundary.
- `GmailProvider` implements every method; Gmail API ⇄ domain mapping tested.
- OAuth2 connect/disconnect + token refresh; tokens **encrypted at rest**.
- Incremental receive via opaque cursor (Gmail `historyId`) with full-sync
  fallback; new messages persisted idempotently via the emails repo.
- Send + create-draft set `In-Reply-To` / `References` and reuse the thread.
- `get_mail_provider()` factory selects the provider from config.
- `pytest` green offline (mocked Gmail service, fake provider, cipher round-trip).

---

## The facade (design)

### Provider-agnostic domain models (`app/mail/models.py`)
```python
@dataclass(frozen=True)
class EmailMessage:
    provider_message_id: str        # provider's message id
    thread_id: str | None           # provider's conversation id
    rfc_message_id: str | None      # RFC 5322 Message-ID header (threading)
    sender: str
    recipients: list[str]
    subject: str
    body_text: str                  # plaintext (HTML stripped if needed)
    headers: dict[str, str]         # selected headers, lowercased keys
    received_at: str | None         # ISO-8601

@dataclass
class OutgoingMessage:
    to: str
    subject: str
    body_text: str
    thread_id: str | None = None    # reply within this provider thread
    in_reply_to: str | None = None  # RFC Message-ID being answered
    references: list[str] = field(default_factory=list)

@dataclass
class SyncResult:
    messages: list[EmailMessage]
    cursor: str                     # new opaque cursor to persist
    full_sync: bool = False         # True if cursor expired → full resync
```
> Standard RFC headers (`Message-ID`, `In-Reply-To`, `References`) are the
> provider-agnostic threading mechanism; `thread_id` is an opaque provider
> extra. Safe-sender headers (`List-Id`, `Auto-Submitted`, `Precedence`) are
> surfaced in `headers` but **interpreted in Epic 4**, not here.

### `MailProvider` interface (`app/mail/base.py`)
```python
class MailProvider(Protocol):
    # identity / connection
    def is_connected(self) -> bool: ...
    def account_email(self) -> str | None: ...
    # receiving
    def fetch_new(self, cursor: str | None) -> SyncResult: ...
    def get_message(self, message_id: str) -> EmailMessage: ...
    def get_thread(self, thread_id: str) -> list[EmailMessage]: ...
    # sending
    def create_draft(self, message: OutgoingMessage) -> str: ...  # -> draft id
    def send(self, message: OutgoingMessage) -> str: ...          # -> sent id
    def send_draft(self, draft_id: str) -> str: ...               # -> sent id
```

### Proposed layout
```
app/mail/
├── __init__.py          # exports MailProvider, models, get_mail_provider
├── base.py              # MailProvider protocol
├── models.py            # EmailMessage / OutgoingMessage / SyncResult
├── factory.py           # get_mail_provider() by config
├── crypto.py            # TokenCipher (Fernet) for credential encryption
├── ingest.py            # sync_once(provider, conn): fetch_new -> emails repo
└── gmail/
    ├── __init__.py
    ├── auth.py          # OAuth2: authorize URL, code exchange, refresh, store
    ├── client.py        # thin Gmail API wrapper + retry/backoff
    └── provider.py      # GmailProvider implements MailProvider (mapping)
app/db/repositories/credentials.py   # encrypted credential storage
app/routers/auth.py                   # /auth/gmail/connect + /callback (minimal)
```

---

## New dependencies (add to `requirements.txt`)
`google-api-python-client`, `google-auth`, `google-auth-oauthlib`,
`cryptography` (Fernet). (File-parsing deps belong to Epic 3.)

## New config (`app/config.py` + `.env.example`)
| Field                  | Default                                  | Notes                         |
| ---------------------- | ---------------------------------------- | ----------------------------- |
| `mail_provider`        | `gmail`                                   | selects the implementation    |
| `token_encryption_key` | — (required to connect)                   | Fernet key; encrypts creds    |
| `google_redirect_uri`  | `http://localhost:8000/auth/gmail/callback` | OAuth2 loopback redirect    |
| `gmail_scopes`         | `gmail.readonly`, `gmail.compose`         | minimal: read + send/drafts   |

> **Scopes:** `gmail.readonly` (read messages + history) + `gmail.compose`
> (create drafts and send) is the minimal set for the MVP. Use `gmail.modify`
> instead only if we later need to manage labels (e.g., mark read). We track
> processed state in our own DB, so label writes aren't required.

---

## Task breakdown

### 2.0 (P0) Facade: models + `MailProvider` interface
Define the dataclasses and protocol above. **Acceptance:** a `FakeMailProvider`
in tests satisfies `isinstance(..., MailProvider)`.

### 2.1 (P0) Encrypted credential storage
- New `credentials` table (added to `schema.py`, idempotent):
  ```sql
  CREATE TABLE IF NOT EXISTS credentials (
      provider   TEXT PRIMARY KEY,     -- 'gmail'
      account    TEXT,                 -- account email
      secret_enc BLOB NOT NULL,        -- Fernet-encrypted token JSON
      updated_at TEXT NOT NULL
  );
  ```
- `app/mail/crypto.py` — `TokenCipher` wrapping Fernet (key from config);
  `encrypt(str)->bytes` / `decrypt(bytes)->str`.
- `app/db/repositories/credentials.py` — `save(provider, account, secret)`,
  `load(provider) -> secret|None`, `delete(provider)`; stores ciphertext only.
- **Acceptance:** cipher round-trip; repo never persists plaintext; load after
  save returns the original token JSON.

### 2.2 (P0) Gmail OAuth2 flow (`app/mail/gmail/auth.py`)
- Build authorization URL (offline access, configured scopes).
- Exchange callback `code` → credentials; persist encrypted via 2.1; record
  account email in `settings` (`gmail_connected=1`, `gmail_email`).
- Load + **auto-refresh** credentials on use; `disconnect()` clears creds and
  flips `settings.gmail_connected=0`.
- Minimal routes in `app/routers/auth.py`: `GET /auth/gmail/connect` (redirect)
  and `GET /auth/gmail/callback` (exchange). UI links to these in Epic 6.
- **Acceptance:** token exchange + refresh tested with a mocked flow/creds
  object; disconnect clears stored credentials and settings.

### 2.3 (P0) Gmail client wrapper (`app/mail/gmail/client.py`)
- Thin wrapper over `googleapiclient` `users().messages/threads/history/drafts`:
  `list_history`, `get_message`, `get_thread`, `create_draft`, `send`,
  `send_draft`.
- Retry/backoff on transient errors (HTTP 429/5xx) with capped exponential
  backoff; surface auth errors distinctly.
- **Acceptance:** wrapper calls verified against a mocked `service`; retry path
  covered.

### 2.4 (P0) `GmailProvider` (`app/mail/gmail/provider.py`)
- Implements `MailProvider` using the client; **maps Gmail API dicts ⇄ domain
  models** (decode base64 body, prefer `text/plain`, strip HTML fallback,
  lowercase selected headers).
- `account_email`/`is_connected` from stored credentials/settings.
- **Acceptance:** mapping tests from a recorded Gmail message payload →
  `EmailMessage`; thread fetch returns ordered messages.

### 2.5 (P0) Incremental receive (opaque cursor)
- `fetch_new(cursor)` → if `cursor` is `None` or expired (Gmail 404 on stale
  `historyId`), do a bounded **full sync** and return `full_sync=True`;
  otherwise page the History API since `cursor`. Returns new `EmailMessage`s +
  the new cursor.
- Cursor persistence reuses `sync_state.last_history_id` (treated as an
  **opaque token**, not Gmail-specific at the facade level — see Risks).
- **Acceptance:** incremental path returns only new messages + advances cursor;
  expired-cursor path triggers full sync.

### 2.6 (P0) Send + draft with correct threading
- `create_draft` / `send` build a MIME message, base64url-encode it, set
  `In-Reply-To` + `References` from the original, and reuse `thread_id`.
- `send_draft(draft_id)` sends a previously created draft (Pilot → approve path).
- **Acceptance:** generated MIME contains correct `In-Reply-To`/`References`;
  Gmail send called with the right `threadId`.

### 2.7 (P0) Provider factory + config
- `get_mail_provider()` builds the configured provider (Gmail only today),
  cached like `get_provider()`. Add the config fields above.
- **Acceptance:** factory returns a `MailProvider`; unknown provider raises a
  clear error.

### 2.8 (P0) Ingestion service (`app/mail/ingest.py`)
- `sync_once(provider, conn) -> int` — calls `fetch_new(cursor)`, upserts each
  message via `repositories.emails.upsert_email` (idempotent on
  `message_id`), persists the new cursor via `repositories.sync_state`.
  Returns count of newly stored emails. This is the unit the Epic 5 scheduler
  will call.
- **Acceptance:** running `sync_once` twice over the same fake batch stores each
  message once (idempotency) and advances the cursor.

### 2.9 (P1) Tests & fixtures
- `FakeMailProvider` (in `tests/`) implementing the protocol with in-memory
  inboxes/threads + recorded sends — reusable by Epics 4–6.
- Mocked Gmail `service` fixture for client/provider tests.
- Coverage: cipher round-trip, credentials repo, OAuth refresh, Gmail mapping,
  incremental + full-sync cursor logic, threading headers, `sync_once`
  idempotency, factory.

---

## Risks / decisions

- **Sync-cursor column name.** Epic 1's `sync_state.last_history_id` is
  Gmail-flavored but stores an **opaque** cursor; the facade treats it as such.
  Option to rename to `sync_cursor` in a later migration for cleanliness —
  deferred to avoid churn now. Document the opaque contract at the repo.
- **historyId expiry.** Stale `historyId` returns 404; provider must fall back
  to a bounded full sync and return `full_sync=True`.
- **Scope minimization.** `readonly` + `compose` chosen over `modify`
  (no label writes needed — processed state lives in our DB).
- **Token encryption key management.** `TOKEN_ENCRYPTION_KEY` (Fernet) is
  required to connect; losing it invalidates stored creds (re-auth). Document
  generation (`Fernet.generate_key()`); never log it.
- **OAuth redirect.** Local single-user uses a loopback redirect URI that must
  be registered in the Google Cloud OAuth client.
- **HTML-only emails.** Prefer `text/plain`; when absent, strip HTML to text
  (lightweight) — full HTML handling is out of scope for MVP.

## Definition of done checklist (Epic 2)
- [ ] `MailProvider` interface + domain models; no provider types leak.
- [ ] `credentials` table + `TokenCipher`; tokens encrypted at rest.
- [ ] Gmail OAuth2 connect / callback / disconnect + auto-refresh.
- [ ] Gmail client wrapper with retry/backoff (mocked-service tests).
- [ ] `GmailProvider` mapping Gmail ⇄ domain models.
- [ ] Incremental receive via opaque cursor + full-sync fallback.
- [ ] Send + create-draft with `In-Reply-To`/`References`/thread reuse.
- [ ] `get_mail_provider()` factory + config fields.
- [ ] `sync_once()` idempotent ingestion into the emails repo.
- [ ] `pytest` green offline; `FakeMailProvider` available for later epics.
