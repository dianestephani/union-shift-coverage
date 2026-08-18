# Shift Coverage

A Django app that helps a team find coverage for a shift. An employee signs in with their Google account, posts a shift they need covered, and the app works its way down the seniority list — sending an in-app notification to one person at a time — until someone accepts.

There's no texting, email, or push notifications involved. Everything happens inside the app itself.

---

## How the whole thing fits together (the big picture)

This is a classic Django app: the server renders HTML and sends it to the browser, rather than a React/JS frontend calling a separate API. If you're used to a MERN stack, think of Django as playing the role of Express + a templating engine, all in one framework, with the database access (the "M" in MERN) built in via Django's ORM instead of something like Mongoose.

There are three moving pieces worth understanding before you touch the code:

1. **Employees and seniority.** Every person who can request or give coverage is an `Employee` row with a `seniority_rank` (1 = most senior). This rank is what drives everything — when someone needs coverage, the app asks the *next* person down the list, not everyone at once.
2. **The coverage state machine.** A shift request moves through a small set of statuses (`DRAFT` → `SEARCHING` → `COVERED` or `UNCOVERED`). All of the logic for what happens on each step lives in one file, `coverage/coverage_service.py`, so you don't have to hunt through views to understand the flow.
3. **In-app notifications.** Instead of texting or emailing people, the app creates `Notification` rows that show up in a bell icon in the header (polled every 15 seconds) and on a dedicated `/notifications/` page.

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
│   └── wsgi.py
├── coverage/                # The one app that contains all the feature code
│   ├── models.py            # Employee, ShiftRequest, ShiftResponse, CoverageEvent, Notification
│   ├── views.py              # Dashboard, roster, shift request forms, respond/notification endpoints
│   ├── urls.py                # Maps URLs to the views above
│   ├── forms.py                # The "New shift request" form
│   ├── admin.py                 # Configures how these models look in /admin/
│   ├── adapters.py               # Google OAuth signup gating (must match a provisioned Employee)
│   ├── signals.py                 # Links a new Google-authenticated User to its Employee
│   ├── notifications.py            # Creates notifications + the message text + retention/cleanup
│   ├── coverage_service.py          # The state machine — start a search, handle YES/NO
│   └── tests/                        # Unit tests, one file per area of the app
│       ├── factories.py               # Shortcuts for building test data
│       ├── test_models.py
│       ├── test_forms.py
│       ├── test_views.py
│       ├── test_coverage_service.py
│       ├── test_auth_linking.py
│       └── test_admin.py
└── templates/coverage/       # The actual HTML pages
    ├── base.html               # Shared layout: header, nav, notification bell + dropdown
    ├── dashboard.html            # The homepage after login
    ├── roster.html                 # List of everyone in the seniority order
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
- **Phone number** – optional, kept only as a contact field (no longer used for login or delivery)

### 6. Run the dev server

```bash
python manage.py runserver
```

Visit `http://127.0.0.1:8000/` and sign in with Google.

---

## How the coverage flow works

1. An employee signs in with Google and creates a shift request (date, start time, end time, notes).
2. They choose **Save as draft** (does nothing else yet) or **Find coverage** (starts the search immediately).
3. On **Find coverage**, the app looks up the next employee below the requester in seniority and sends them an in-app notification with **Yes / No** buttons. That person will see it in their notification bell and on their dashboard, under "Waiting on you."
4. **Yes** → the shift is marked `COVERED`, and both the requester and the person covering get a confirmation notification. The search stops.
5. **No** → the requester is notified that this person declined, and the app moves on to the *next* person down the seniority list.
6. If the app runs out of people to ask (nobody left below the requester, or everyone declined), the request is marked `UNCOVERED`.

Every one of these transitions — request created, notification sent, response received, covered, uncovered — is written to a `CoverageEvent` row. You can see the full history for a request on its detail page, or browse all of them in the Django admin. Think of it as an audit log: nothing about a request's history is ever overwritten, only added to.

---

## The dashboard

The dashboard (the homepage after logging in) is organized top to bottom by what's most relevant to *you*:

1. **Shifts you've offered** — a table of every shift request you've created, with its current status.
2. **My coverage requests** — two side-by-side cards:
   - **Waiting on you** — requests where someone needs your Yes/No.
   - **You're covering** — shifts you've already said yes to.
3. **You declined** — tucked behind a collapsed `<details>` toggle at the bottom, since it's the least actionable information but still worth keeping around.

---

## Notifications

Notifications are how the app tells you something needs your attention — a new coverage request, a confirmation that your shift got covered, or someone declining your request.

- **The bell icon** in the header (visible on every page once logged in) polls the server every 15 seconds for unread notifications and shows a red count badge. Clicking it opens a dropdown where you can respond directly.
- **The `/notifications/` page** (linked from the header, and from "See all notifications" in the dropdown) shows your full notification history — read and unread — in one place.
- **Retention:** to keep this from growing forever, notifications are automatically deleted after **24 hours**, and each employee's list is capped at their **10 most recent** notifications — older ones are removed as new ones arrive. This cleanup logic lives in `coverage/notifications.py` (`prune_notifications`), and runs whenever a notification is created or either notification view is loaded.

No push service, WebSockets, or third-party messaging (like the Twilio SMS this project used to use) is involved — it's all polling plus regular page loads.

---

## Testing

Tests live in `coverage/tests/`, split by what they're testing:

| File | What it covers |
|---|---|
| `test_models.py` | Model behavior — display helpers, `__str__` output, roster ordering |
| `test_forms.py` | The shift request form's validation rules |
| `test_coverage_service.py` | The state machine — starting a search, handling YES/NO, edge cases like an exhausted roster |
| `test_views.py` | Every page/endpoint a logged-in employee touches — dashboard, roster, notifications, responding to a request |
| `test_auth_linking.py` | Google login gating and linking a new login to its Employee record |
| `test_admin.py` | Smoke tests that each admin page loads without error |

Run the whole suite with:

```bash
python manage.py test coverage
```

A couple of tests are intentionally named `test_..._is_currently_accepted` (for example, in `test_forms.py`) — these pin down behavior that isn't actually validated today, like a shift's end time being before its start time. They're not bugs you need to fix; they exist so that if you *do* add that validation later, you'll get a clear test failure telling you exactly what changed, instead of silently changing behavior.

---

## Timezone

The app defaults to `America/Chicago`. Change `TIME_ZONE` in `shift_coverage/settings.py` if needed.

---

## Known gaps / stretch goals (not yet built)

- Deactivating an employee (`is_active=False`) stops them from being asked for coverage, but does **not** stop them from logging in — see `coverage/adapters.py`. Worth revisiting if that matters for your use case.
- Manager admin view showing all open requests across all employees (the Django admin works today, but isn't tailored for this)
- Real-time delivery (WebSockets/Channels) instead of polling
- Email notification fallback
