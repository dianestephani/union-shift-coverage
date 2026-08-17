# Shift Coverage

Django app for catering shift coverage. Employees sign in with Google, post a shift they need covered, and the app cascades an in-app notification down the seniority roster until someone hits **Yes**.

---

## Project layout

```
shift_coverage/
├── manage.py
├── requirements.txt
├── .env.example
├── shift_coverage/        # Django project config
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── coverage/              # Main app
│   ├── models.py          # Employee, ShiftRequest, ShiftResponse, CoverageEvent, Notification
│   ├── views.py           # Auth, dashboard, request form, respond/notification endpoints
│   ├── urls.py
│   ├── forms.py
│   ├── adapters.py        # Google OAuth signup gating (must match a provisioned Employee)
│   ├── signals.py         # Links a new Google-authenticated User to its Employee
│   ├── notifications.py   # In-app notification helpers + message text
│   └── coverage_service.py  # State machine (YES/NO logic)
└── templates/coverage/    # HTML templates
```

---

## Setup

### 1. Clone / copy this folder, then create a virtual environment

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

```bash
python manage.py migrate
```

### 4. Create a superuser (for the admin panel)

```bash
python manage.py createsuperuser
```

### 5. Add employees via the admin

```
python manage.py runserver
# Then visit http://127.0.0.1:8000/admin/
```

Go to **Employees → Add employee**. Fill in:
- **Name** – display name used in notifications
- **Email** – must match the Google account the employee will sign in with; Google logins with no matching employee email are rejected
- **Seniority rank** – `1` = most senior. Coverage requests cascade from the requester toward higher numbers (less senior)
- **Is active** – uncheck to remove someone from the rotation without deleting them
- **Phone number** – optional, kept only as a contact field (no longer used for login or delivery)

### 6. Run the dev server

```bash
python manage.py runserver
```

Visit `http://127.0.0.1:8000/` and sign in with Google.

---

## How the coverage flow works

1. Employee signs in with Google, creates a shift request (date / start / end / notes).
2. They can **Save as draft** or click **Find coverage**.
3. On Find coverage, the app finds the employee immediately below the requester in seniority and sends them an in-app notification with **Yes / No** buttons (shown on their dashboard under "Requests waiting on you").
4. **Yes** → both parties get a confirmation notification; search ends.
5. **No** → requester is notified; the next person down the roster is notified.
6. If the entire roster is exhausted, the request is marked **Uncovered**.

Notifications are delivered by lightweight polling — the header bell in the app polls every 15 seconds for unread items. No push service, WebSockets, or third-party messaging is involved.

All state changes are recorded in the **CoverageEvent** log, visible on the shift request detail page and in the Django admin.

---

## Timezone

The app defaults to `America/Chicago`. Change `TIME_ZONE` in `settings.py` if needed.

---

## Stretch goals (not yet built)

- Manager admin view showing all open requests across all employees
- Real-time delivery (WebSockets/Channels) instead of polling
- Email notification fallback
