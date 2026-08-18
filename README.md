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
