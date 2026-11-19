# Medication Tracker API

FastAPI backend for the Medication Tracker UI. It replaces the Next.js server actions and
route handlers with a REST API, and uses the **same MongoDB database, collections, OTP hashing
and session format**, so existing accounts and data keep working.

## Layout

```
app/
├── main.py              # app factory, lifespan (Mongo connect + indexes), CORS, error handlers
├── dependencies.py      # DI wiring: db -> repositories -> services; auth + cron guards
├── controllers/         # HTTP layer: routing, status codes, cookies. No business logic.
├── services/            # business logic; talks to repositories and integrations only
├── db/
│   ├── mongo.py         # async client lifecycle
│   ├── indexes.py       # collection indexes (mirror the Mongoose ones)
│   ├── base.py          # ObjectId / timestamp helpers
│   └── repositories/    # one class per collection; the only code that builds queries
├── schemas/             # Pydantic request/response models (camelCase JSON)
├── integrations/        # external systems: Brevo email, Firebase Cloud Messaging
├── tasks/               # background jobs (the in-process reminder timer)
├── core/                # settings, constants, exceptions, security primitives
└── utils/               # pure helpers: IST time, streaks, schedule rules
scripts/                 # one-off ops, e.g. migrate_user_scope.py
tests/                   # unit/ (pure logic) and api/ (routing/auth smoke, no DB needed)
```

Dependencies flow one way: `controllers → services → db/integrations`, with `utils` and
`core` usable from anywhere.

## Run

```powershell
python -m venv .venv                      # already created
.venv\Scripts\pip install -r requirements-dev.txt
copy .env.example .env                    # then fill in values
.venv\Scripts\uvicorn app.main:app --reload --port 8000
```

Interactive docs: <http://localhost:8000/docs>, available in every environment including production.
Every data endpoint still needs a session; use the **Authorize** button with the `token` returned
by `POST /api/v1/auth/otp/verify`.

```powershell
.venv\Scripts\python -m scripts.migrate_user_scope   # one-off index migration
.venv\Scripts\pytest          # tests
.venv\Scripts\ruff check .    # lint
.venv\Scripts\mypy app        # type check
```

## Endpoints

Everything except `/health*`, `/auth/otp/*`, `/auth/signout` and `/cron/*` requires a session
(HttpOnly cookie `session`, or `Authorization: Bearer <token>`). Base path: `/api/v1`.

| Method & path | Replaces (Next.js) | Notes |
|---|---|---|
| `POST /auth/otp/request` | `requestOtp` | body `{email, purpose: "signup" \| "signin"}` |
| `POST /auth/otp/verify` | `verifyOtp` | body `{email, purpose, code, useRefreshToken?}`; sets the session cookie, also returns `token`. With `useRefreshToken: true` the token is short-lived (15 min) and a `refreshToken` (HttpOnly cookie, path `/api/v1/auth`) is issued too |
| `POST /auth/refresh` | - | refresh token from the cookie or body `{refreshToken}`; returns a new `token` + `refreshToken` and the old pair stops working. A refresh token works once: replaying a used one revokes the session (two tabs refreshing within 10 s are only rejected) |
| `POST /auth/signout` | `signOut` | idempotent; drops this device's push tokens |
| `GET /auth/me` | `getCurrentUser` | |
| `DELETE /auth/me` | — | permanently erases the account and all its data (medications, dose logs, wellness, notes, push tokens, reminders, OTPs, sessions); clears the cookie |
| `GET /dashboard` | `getDashboardData` | home page |
| `GET /today` | `getTodayData` | timeline |
| `GET /statistics` | `getStatisticsData` | |
| `GET /medications` | `getMedicationsPageData` | with today's doses + 14-day history |
| `POST /medications` | `upsertMedication` (no id) | 201, returns the medication |
| `PUT /medications/{id}` | `upsertMedication` (with id) | |
| `PATCH /medications/{id}/enabled` | `setMedicationEnabled` | body `{enabled}` |
| `DELETE /medications/{id}` | `deleteMedication` | |
| `PUT /doses/completion` | `setDoseCompletion` | body `{medicationName, scheduledTime, completed, date?}` |
| `GET /wellness` | `getWellnessData` | |
| `POST /wellness/count/increment?date=` | `incrementCount` | returns `{ok, count}` |
| `POST /wellness/count/decrement?date=` | `decrementCount` | never below 0 |
| `POST /wellness/count/reset?date=` | `resetCount` | |
| `PUT /wellness/notes` | `setDayNotes` | body `{notes, date?}` |
| `POST /push/tokens` | `savePushToken` | body `{token, userAgent?}` |
| `DELETE /push/tokens` | `removePushToken` | body `{token}` |
| `POST /push/test` | `sendTestNotification` | |
| `POST /family/invite` | - | the followed person (father) creates a one-time code, valid 24 h; a new code replaces the old one |
| `POST /family/connect` | - | body `{code}`; the follower (son) connects, single-use code |
| `GET /family/patients` / `GET /family/caregivers` | - | accounts I follow / people who follow me |
| `DELETE /family/patients/{id}` / `DELETE /family/caregivers/{id}` | - | stop following / revoke someone's access |
| `POST /reports/send` | - | body `{period: "last7"}`; emails the signed-in user a 7-day adherence report (HTML body + PDF attached), 1 per minute |
| `GET /reports/download?period=last7` | - | the same report as a PDF download |
| `GET /family/patients/{id}/overview` | - | read-only dashboard, missed doses, medication change log |
| `POST /family/patients/{id}/remind` | - | pushes a missed-dose notification; `409` unless a dose was missed, `429` within 5 min of the last one |
| `GET`/`POST /cron/send-reminders` | `/api/cron/send-reminders` | `Authorization: Bearer $CRON_SECRET`; call every minute |
| `GET /health`, `GET /health/ready` | — | liveness / readiness (pings MongoDB) |

`/firebase-messaging-sw.js` is intentionally **not** here: it is a static asset the browser
must load from the UI's own origin, so it stays in the Next.js app.

### Used by the UI

The Next.js UI (`../tracker`) calls this API through a same-origin proxy (`/api/v1/*` rewrite),
so the session cookie stays first-party and CORS isn't needed. Server Components call it directly
with `API_URL` and forward the cookie. Run both: API on `:8000`, UI on `:3000`.

### Reminders

Due dose reminders are sent by an in-process timer (`app/tasks/reminder_loop.py`) every
`REMINDER_INTERVAL_SECONDS` (default 60), started with the app. It replaces the Next.js
instrumentation timer. Overlapping runs are safe: each dose is claimed once in `remindersents`.
Set `REMINDER_TIMER_ENABLED=false` if you instead call `GET/POST /api/v1/cron/send-reminders`
every minute from an external scheduler (`Authorization: Bearer $CRON_SECRET`), e.g. when the API
runs on a serverless host that freezes between requests.

### Conventions

- JSON is camelCase, matching the existing UI types (`todayKey`, `scheduleTimes`, ...).
- Mutations return `{"ok": true, ...}`. Errors return `{"ok": false, "error": "<message>"}`
  with a real status code (400/401/404/409/422/429/502/503). Validation errors (422) also carry
  `details: [{field, message}]`. Error messages match the old action messages.
- Dates are IST (`Asia/Kolkata`) `YYYY-MM-DD` keys, as in the UI.

## Differences from the server actions

- Real HTTP status codes instead of always-200 `{ok:false}`.
- Updating/deleting/toggling a medication that doesn't exist (or isn't yours) is a `404`
  instead of a silent success.
- Wellness `increment`/`decrement` are atomic (single Mongo update) instead of read-then-write.
- Unexpected errors return a generic 500 message instead of leaking the exception text.

## Deployment notes

- Set `AUTH_SECRET` to the **same value** the Next.js app uses.
- UI and API on different sites: set `CORS_ORIGINS` to the UI origin, `COOKIE_SAMESITE=none`
  (implies `Secure`), and make the UI `fetch` with `credentials: "include"`.
- Push uses the FCM HTTP v1 API directly (no `firebase-admin`), configured by the same
  `FIREBASE_SERVICE_ACCOUNT` value.
- On a network that intercepts HTTPS, set `USE_SYSTEM_CA=true` to trust the OS certificate store for the Brevo and Firebase calls
  (MongoDB TLS is unaffected; truststore must never be injected globally, it breaks PyMongo).
