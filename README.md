# Shift Coverage

A Django app that helps a team find coverage for a shift. An employee signs in with their Google account, posts a shift they need covered, and the app works its way down the seniority list — sending an in-app notification to one person at a time — until someone accepts.

There's no texting, email, or push notifications involved. Everything happens inside the app itself.

---

## How the whole thing fits together (the big picture)

This is a classic Django app: the server renders HTML and sends it to the browser, rather than a React/JS frontend calling a separate API. If you're used to a MERN stack, think of Django as playing the role of Express + a templating engine, all in one framework, with the database access (the "M" in MERN) built in via Django's ORM instead of something like Mongoose.

There are three moving pieces worth understanding before you touch the code:

1. **Employees and seniority.** Every person who can request or give coverage is an `Employee` row with a `seniority_rank` (1 = most senior). This rank is what drives everything — when someone needs coverage, the app asks the *next* person down the list, not everyone at once.
2. **The coverage state machine.** A shift request moves through a small set of statuses (`DRAFT` → `SEARCHING` → `COVERED` or `UNCOVERED`, or `CANCELLED` at any point before it resolves). All of the logic for what happens on each step lives in one file, `coverage/coverage_service.py`, so you don't have to hunt through views to understand the flow.
3. **In-app notifications.** Instead of texting or emailing people, the app creates `Notification` rows that show up in a bell icon in the header and on a dedicated `/notifications/` page. Delivery is real-time over a WebSocket (Django Channels) — the moment a notification is created server-side, it's pushed straight to every open tab for that employee, no polling loop involved.
4. **Two roles, one model.** There's no separate "manager" account type — a manager is just an `Employee` with `is_manager=True`, granted through the admin. That one flag is what unlocks the extra manager dashboard and view-any-request access described below; everything else about how they use the app is identical to anyone else.

---

## Project layout

```
shift_coverage/
├── manage.py
├── requirements.txt
├── .env.example
├── db.sqlite3              # local dev database (SQLite — nothing to install)
├── shift_coverage/         # Django project config
│   ├── settings.py
│   ├── urls.py
│   ├── asgi.py               # Routes HTTP to Django as usual, WebSockets to Channels
│   └── wsgi.py
├── coverage/                # The one app that contains all the feature code
│   ├── models.py            # Employee, ShiftRequest, ShiftResponse, CoverageEvent, Notification
│   ├── views.py              # Dashboard, roster, manager views, shift request forms, respond/notification endpoints
│   ├── urls.py                # Maps URLs to the views above
│   ├── routing.py              # Maps ws:// URLs to consumers (the WebSocket equivalent of urls.py)
│   ├── consumers.py             # NotificationConsumer — one per open browser tab
│   ├── realtime.py               # Shared group-naming + push helper used by notify() and the consumer
│   ├── middleware.py              # Activates each employee's timezone + time-format preference per request
│   ├── time_format.py              # The 12h/24h preference itself (a contextvar, same pattern as Django's own timezone.activate())
│   ├── templatetags/
│   │   └── coverage_extras.py       # Template filters that format timestamps per the active preferences
│   ├── forms.py                    # ShiftRequestForm + EmployeeSettingsForm
│   ├── admin.py                     # Configures how these models look in /admin/
│   ├── adapters.py                   # Google OAuth signup gating (must match a provisioned Employee)
│   ├── signals.py                     # Links a new Google-authenticated User to its Employee
│   ├── notifications.py                # Creates notifications + the message text + retention/cleanup
│   ├── coverage_service.py              # The state machine — start a search, handle YES/NO
│   └── tests/                            # Unit tests, one file per area of the app
│       ├── factories.py               # Shortcuts for building test data
│       ├── test_models.py
│       ├── test_forms.py
│       ├── test_views.py
│       ├── test_coverage_service.py
│       ├── test_auth_linking.py
│       ├── test_admin.py
│       └── test_realtime.py           # WebSocket consumer tests
└── templates/coverage/       # The actual HTML pages
    ├── base.html               # Shared layout: header, nav, notification bell + dropdown
    ├── dashboard.html            # The homepage after login
    ├── roster.html                 # List of everyone in the seniority order, with contact info
    ├── settings.html                # Per-employee preferences: timezone, 12h/24h time
    ├── manager_dashboard.html        # Manager-only: every open request, the roster, recent activity
    ├── manager_employee_detail.html   # Manager-only: one employee's full request/response history
    ├── notifications.html           # The dedicated notifications page
    ├── shift_request_form.html       # "New shift request" form
    ├── shift_request_detail.html      # One shift request's full history
    └── login.html
```

---

## Setup

### 1. Clone / copy this folder, then create a virtual environment

A virtual environment keeps this project's Python packages separate from anything else on your machine.

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Create your `.env` file

```bash
cp .env.example .env
```

Edit `.env` and fill in:

| Variable | Description |
|---|---|
| `SECRET_KEY` | Any long random string |
| `DEBUG` | `True` for local dev, `False` in production |
| `ALLOWED_HOSTS` | Comma-separated hostnames |
| `GOOGLE_CLIENT_ID` | From your [Google Cloud Console](https://console.cloud.google.com/apis/credentials) OAuth client |
| `GOOGLE_CLIENT_SECRET` | From the same OAuth client |

To create the OAuth client: **Google Cloud Console → APIs & Services → Credentials → Create Credentials → OAuth client ID** (type "Web application"), with an authorized redirect URI of `http://127.0.0.1:8000/accounts/google/login/callback/` for local dev.

### 3. Run migrations

Migrations are Django's way of turning your Python model definitions into actual database tables.

```bash
python manage.py migrate
```

### 4. Create a superuser (for the admin panel)

```bash
python manage.py createsuperuser
```

### 5. Add employees via the admin

```bash
python manage.py runserver
# Then visit http://127.0.0.1:8000/admin/
```

Go to **Employees → Add employee**. Fill in:
- **Name** – display name used in notifications
- **Email** – must match the Google account the employee will sign in with; a Google login with no matching employee email is rejected before an account is ever created (see `coverage/adapters.py`)
- **Seniority rank** – `1` = most senior. Coverage requests cascade from the requester toward higher numbers (less senior)
- **Is active** – uncheck to remove someone from the rotation without deleting them. Note: this only skips them when the app is *choosing who to ask next* — it does not currently block them from logging in.
- **Is manager** – gives them the [manager dashboard](#manager-dashboard) and lets them view any employee's request/response history. Off by default; check it for whoever should have that access (e.g. yourself).
- **Phone number** – optional, kept only as a contact field (no longer used for login or delivery). Shows up on the roster page for other employees to see.
- **Timezone** / **Military time** – each employee's own display preferences; they can change these themselves later from [Settings](#settings) once logged in, so you don't need to set them up front.

### 6. Run the dev server

```bash
python manage.py runserver
```

This looks like the normal Django command, but because `daphne` is listed first in `INSTALLED_APPS`, it actually serves the app over ASGI instead of Django's default WSGI dev server — that's what lets it handle both regular HTTP requests and the WebSocket connection used for real-time notifications, from a single `runserver` command. Nothing else about running it locally changes.

Visit `http://127.0.0.1:8000/` and sign in with Google.

**Heads up:** logging in only works with a real Google account — there's no test/sandbox login for OAuth. Whatever Google account you sign in with has to match the email on an `Employee` you created in step 5, or the app rejects it. If you don't have a Google account handy for testing, use a spare one rather than your main one, since you'll be signing into this app with it repeatedly.

---

## Deploying to Render (free tier)

This section walks through putting the app on the internet using [Render](https://render.com), which has a genuinely free tier — no credit card, no trial period that expires. The tradeoff: a free instance spins down after about 15 minutes of no traffic, so the first request after a quiet stretch takes a few extra seconds to wake back up. Fine for a demo or portfolio project; not something you'd want for a real team relying on it.

### Before you start, you'll need

- **A GitHub account with this repo pushed to it.** Render deploys straight from a GitHub repo — you connect your GitHub account once, then pick the repo from a list.
- **A Google Cloud OAuth client** (the same kind you set up for local dev in step 2 above) — you'll add a second redirect URI to it for the live site, rather than making a whole new one.
- **A real Google account to test with**, same as local dev — and an `Employee` row with that same email, added through the live site's `/admin/`.

### 1. Why the app needs a few production-only settings

Everything below already lives in `shift_coverage/settings.py` — you don't need to write any of it. This is just explaining *why* it's there, since it's easy to assume a Django app runs the same everywhere and get confused when it doesn't:

- **`SECURE_PROXY_SSL_HEADER`** — Render (like most hosts) terminates HTTPS at its own edge, then talks to your app over plain HTTP internally. Without telling Django to trust the header Render adds (`X-Forwarded-Proto`), Django thinks every request is insecure, which quietly breaks login and form submissions (CSRF checks fail).
- **`SECURE_SSL_REDIRECT`** — forces any plain `http://` request to redirect to `https://`. Without this, a stray `http://` link (or someone typing the URL without `https`) generates insecure URLs elsewhere in the app, including Google's OAuth callback URL — which Google flatly refuses for anything other than `localhost`.
- **`CSRF_TRUSTED_ORIGINS`** — an allowlist of origins Django will accept form submissions from. You set this to your live URL via an environment variable (see below).

### 2. Create the Web Service on Render

1. Sign up / log in at [render.com](https://render.com) with your GitHub account.
2. **New → Web Service**, then pick this repo and the branch you want to deploy.
3. Render will try to auto-detect a Python project. Set these two fields explicitly (its defaults skip steps this app actually needs):
   - **Build Command:**

     ```bash
     pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate
     ```

     (`collectstatic` gathers every static file — including Django admin's own CSS/JS — into one folder for production. Skip it and *every* admin page 500s, not just the ones you'd expect.)
   - **Start Command:**

     ```bash
     daphne -b 0.0.0.0 -p $PORT shift_coverage.asgi:application
     ```

     (Uses `daphne`, not Django's dev server or a plain WSGI server — the app needs ASGI to handle the WebSocket connection real-time notifications depend on.)
4. **Instance Type:** Free.

### 3. Set environment variables

In the service's **Environment** tab:

| Variable | Value |
|---|---|
| `SECRET_KEY` | Click Render's "Generate" button — don't reuse your local dev one |
| `DEBUG` | `False` |
| `ALLOWED_HOSTS` | `<your-app-name>.onrender.com` (Render assigns this after the first deploy) |
| `CSRF_TRUSTED_ORIGINS` | `https://<your-app-name>.onrender.com` |
| `GOOGLE_CLIENT_ID` | Same value as your local `.env` |
| `GOOGLE_CLIENT_SECRET` | Same value as your local `.env` — copy carefully, a stray trailing space in this field is a surprisingly common way to break Google login |

### 4. Add the production redirect URI in Google Cloud Console

Go back to **Google Cloud Console → Credentials → your OAuth client → Authorized redirect URIs**, and add (keeping the `127.0.0.1` one for local dev too):

```text
https://<your-app-name>.onrender.com/accounts/google/login/callback/
```

It has to be `https://`, with the trailing slash, matching your Render URL exactly — Google does an exact string match, not a fuzzy one.

### 5. Create an admin login without shell access

Render's free tier doesn't include a shell into the running instance, so `python manage.py createsuperuser` isn't something you can run *on* Render directly. The workaround for a small/demo project: create the superuser **locally**, and since this project's SQLite database (`db.sqlite3`) gets deployed along with the rest of the code, that superuser comes along for the ride.

```bash
python manage.py createsuperuser
```

Then commit and push `db.sqlite3` like any other file. (Normally a database file is the last thing you'd want in git — it's only reasonable here because this is SQLite, a single file, on a demo project where you don't mind the data resetting on every deploy.)

Once deployed, log into `/admin/` on the live site with that superuser and add your `Employee` row the same way you did locally in Setup step 5.

### 6. Known limitations of this setup

- **Data doesn't persist.** Render's free-tier disk is wiped and reset to whatever's in your last git push on every deploy or restart. Anything entered through the live app (new shift requests, employees added via `/admin/`, etc.) vanishes the next time you deploy. Fine for a demo; not something to build real usage on top of without adding a real database.
- **One process only.** The real-time notification system uses `channels.layers.InMemoryChannelLayer`, which only works within a single running process — which is exactly what the free tier gives you, so it's fine as-is. If you ever scale to more than one worker/instance, see the note in `shift_coverage/settings.py`'s `CHANNEL_LAYERS` about switching to `channels_redis`.

---

## How the coverage flow works

1. An employee signs in with Google and creates a shift request (date, start time, end time, notes).
2. They choose **Save as draft** (does nothing else yet) or **Find coverage** (starts the search immediately).
3. On **Find coverage**, the app looks up the next employee below the requester in seniority and sends them an in-app notification with **Yes / No** buttons. That person will see it in their notification bell and on their dashboard, under "Waiting on you."
4. **Yes** → the shift is marked `COVERED`, and both the requester and the person covering get a confirmation notification. The search stops.
5. **No** → the requester is notified that this person declined, and the app moves on to the *next* person down the seniority list.
6. If the app runs out of people to ask (nobody left below the requester, or everyone declined), the request is marked `UNCOVERED`.

Every one of these transitions — request created, notification sent, response received, covered, uncovered, cancelled — is written to a `CoverageEvent` row. You can see the full history for a request on its detail page, or browse all of them in the Django admin. Think of it as an audit log: nothing about a request's history is ever overwritten, only added to.

### Cancelling a request

The requester can cancel their own request from its detail page — a "Cancel request" button shows up for as long as it's `DRAFT` or `SEARCHING` (behind a confirm dialog, since it's not reversible). Once it's `COVERED`, `UNCOVERED`, or already `CANCELLED`, the button disappears; those are all terminal states.

If it was actively `SEARCHING`, whoever was currently being asked gets an informational notification ("no response needed") so they're not left wondering. This is handled by `coverage_service.cancel_request()`, and it deliberately does **not** touch that person's `ShiftResponse` row — it's left `PENDING` as an honest historical record ("this is where things stood when it got cancelled"). Instead, `handle_response()` itself checks that the request is still `SEARCHING` before accepting a Yes/No — so if that notification arrives late, or someone clicks a stale Yes/No button from before the cancellation, it's rejected with a clear error rather than silently re-opening a cancelled request. The dashboard's "waiting on you" list and the notification bell's Yes/No buttons both apply that same check, so a cancelled ask stops looking actionable everywhere at once, not just where you happened to cancel it from.

---

## The dashboard

The dashboard (the homepage after logging in) is organized top to bottom by what's most relevant to *you*:

1. **Shifts you've offered** — a table of every shift request you've created, with its current status.
2. **My coverage requests** — two side-by-side cards:
   - **Waiting on you** — requests where someone needs your Yes/No.
   - **You're covering** — shifts you've already said yes to.
3. **You declined** — tucked behind a collapsed `<details>` toggle at the bottom, since it's the least actionable information but still worth keeping around.

---

## Roster

`/roster/` lists everyone in seniority order — the same order coverage requests cascade through — along with each person's email, phone number (`—` if they haven't given one), and active/inactive status. Any logged-in employee can see this; it's meant to answer "who's more senior than me, and how do I reach them" without digging through the admin.

---

## Settings

`/settings/` lets each employee control how the app displays things *to them* — it doesn't affect anything anyone else sees. Two preferences, both on the `Employee` model:

- **Timezone** — a dropdown of common IANA timezones (defaults to `America/Chicago`, the app's overall default). This affects *timestamps* — when a notification was sent, when a request was answered — not the shift's actual start/end time. A shift's time is entered as a plain clock time (e.g. "9:00 AM") with no timezone attached, so it always displays exactly as entered, regardless of who's viewing it.
- **24-hour time** — toggles `2:00 PM` vs `14:00` everywhere a time is shown, including shift start/end times.

Both preferences are applied by `coverage/middleware.py`'s `EmployeePreferencesMiddleware`, which runs on every request for a logged-in employee: it calls Django's own `timezone.activate()` for the timezone, and sets a small custom contextvar (`coverage/time_format.py`, deliberately mirroring how `timezone.activate()` works) for the 12h/24h choice. `ShiftRequest.time_display()` reads that contextvar directly; everywhere else a timestamp is shown, it goes through the `user_datetime` / `user_datetime_short` template filters in `coverage/templatetags/coverage_extras.py` so both preferences are honored consistently instead of only affecting shift times.

---

## Manager dashboard

Some employees are managers (`Employee.is_manager`, granted via the admin — not tied to Django's own `is_staff`/superuser flag, which is a separate concept for backend admin access). A manager gets an extra **Manager** link in the nav, leading to `/manager/`:

- **Open requests** — every request across *all* employees that's still `DRAFT` or `SEARCHING`, with a link into full detail.
- **Roster** — same as the public roster page, plus a "History" link per person.
- **Recent activity** — the last 25 `CoverageEvent` entries system-wide.

Clicking "History" on anyone goes to `/manager/employees/<id>/` — their profile info plus every request they've ever made and every coverage response they've ever given, regardless of status.

A manager can also open *any* request's detail page (`/request/<id>/`), not just their own — that view checks `sr.requester_id == employee.id or employee.is_manager`. They can't take actions on someone else's request on their behalf, though (no "Find coverage now" button shows up there) — starting a search is still the requester's own call.

Non-managers hitting `/manager/...` URLs directly get a 404, not a 403 — the same "don't reveal it exists" pattern used elsewhere in the app (e.g. trying to view someone else's shift request).

---

## Notifications

Notifications are how the app tells you something needs your attention — a new coverage request, a confirmation that your shift got covered, or someone declining your request.

- **The bell icon** in the header (visible on every page once logged in) shows a red count badge and a dropdown where you can respond directly.
- **The `/notifications/` page** (linked from the header, and from "See all notifications" in the dropdown) shows your full notification history — read and unread — in one place.
- **Delivery is real-time, not polling.** Each open browser tab opens a WebSocket connection to `/ws/notifications/`. The moment `coverage/notifications.py`'s `notify()` creates a `Notification`, it pushes it straight down that socket to every tab that employee has open — see `coverage/consumers.py` (the server side, one consumer per tab) and `coverage/realtime.py` (the shared "which group does this employee's messages go to" helper both `notify()` and the consumer use). The bell's JavaScript just re-fetches the current state whenever a push arrives, so it can't drift out of sync with the server. If the socket drops (lost wifi, laptop sleep, etc.) it automatically reconnects with backoff, and reconnects immediately when the tab becomes visible again.
- **Retention:** to keep this from growing forever, notifications are automatically deleted after **24 hours**, and each employee's list is capped at their **10 most recent** notifications — older ones are removed as new ones arrive. This cleanup logic lives in `coverage/notifications.py` (`prune_notifications`), and runs whenever a notification is created or either notification view is loaded.

### How the real-time plumbing fits together

This uses [Django Channels](https://channels.readthedocs.io/), which extends Django to speak ASGI (Django's normal request/response cycle plus long-lived connections like WebSockets) instead of just WSGI (request/response only). Concretely:

- `shift_coverage/asgi.py` is the entry point: HTTP still goes to Django as normal, but `/ws/notifications/` gets routed to `coverage/consumers.py`'s `NotificationConsumer` instead.
- A **channel layer** is what lets one part of the app (a view calling `notify()`) hand a message to a completely different part of the app (a consumer holding open a WebSocket in another connection) — think of it as an internal message bus. Locally this uses `channels.layers.InMemoryChannelLayer`, which only works within a single process. **A production deployment running more than one worker process needs a shared backend instead** (`channels_redis`, configured in `shift_coverage/settings.py`'s `CHANNEL_LAYERS` — the swap is commented there).
- No third-party push service or messaging provider (like the Twilio SMS this project used to use) is involved — it's all your own server talking to your own open browser tabs.

---

## Testing

Tests live in `coverage/tests/`, split by what they're testing:

| File | What it covers |
|---|---|
| `test_models.py` | Model behavior — display helpers, `__str__` output, roster ordering |
| `test_forms.py` | Form validation rules — the shift request form (date/time sanity checks) and the settings form (valid timezone choices, the 24h checkbox) |
| `test_coverage_service.py` | The state machine — starting a search, handling YES/NO, cancelling a request, edge cases like an exhausted roster or a stale Yes/No arriving after cancellation |
| `test_views.py` | Every page/endpoint a logged-in employee touches — dashboard, roster, settings, notifications, responding to a request, cancelling a request — plus the manager dashboard and per-employee history pages, and that the timezone/time-format middleware activates correctly |
| `test_auth_linking.py` | Google login gating and linking a new login to its Employee record |
| `test_admin.py` | Smoke tests that each admin page loads without error |
| `test_realtime.py` | The WebSocket consumer — connection gating, and that `notify()` actually pushes to the right employee (and only that employee) |

Run the whole suite with:

```bash
python manage.py test coverage
```

A couple of tests are intentionally named `test_..._is_currently_accepted` (for example, in `test_forms.py`) — these pin down behavior that isn't actually validated today, like a shift's end time being before its start time. They're not bugs you need to fix; they exist so that if you *do* add that validation later, you'll get a clear test failure telling you exactly what changed, instead of silently changing behavior.

---

## Timezone

`shift_coverage/settings.py`'s `TIME_ZONE` is the app-wide fallback — what an anonymous request gets, and what a new employee's `timezone` field defaults to. See [Settings](#settings) for how individual employees override it for themselves.

---

## Known gaps / stretch goals (not yet built)

- Deactivating an employee (`is_active=False`) stops them from being asked for coverage, but does **not** stop them from logging in — see `coverage/adapters.py`. Worth revisiting if that matters for your use case.
- The in-memory channel layer (real-time notifications) only works with a single server process — see the "How the real-time plumbing fits together" note above before deploying with more than one worker.
- Email notification fallback

---

*A couple of things in this repo — the seeded `db.sqlite3` (including its demo superuser credentials) and `study-questions.md` — are here on purpose, left visible rather than cleaned up or gitignored, as a record of the reasoning and tradeoffs behind this project rather than something a real production app should ship with.*
