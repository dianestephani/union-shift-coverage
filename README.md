# Shift Coverage

Django app for catering shift coverage. Employees log in with their phone number, post a shift they need covered, and the app cascades a text message down the seniority roster until someone says YES.

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
│   ├── models.py          # Employee, ShiftRequest, ShiftResponse, CoverageEvent
│   ├── views.py           # Auth, dashboard, request form, Twilio webhook
│   ├── urls.py
│   ├── forms.py
│   ├── sms.py             # Twilio helpers + message text
│   └── coverage_service.py  # State machine (YES/NO/UNSURE logic)
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
| `TWILIO_ACCOUNT_SID` | From your Twilio console |
| `TWILIO_AUTH_TOKEN` | From your Twilio console |
| `TWILIO_PHONE_NUMBER` | Your Twilio number in E.164 format, e.g. `+15551234567` |

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
- **Name** – display name used in SMS messages
- **Phone number** – in E.164 format, e.g. `+15551234567`
- **Seniority rank** – `1` = most senior. Coverage requests cascade from the requester toward higher numbers (less senior).
- **Is active** – uncheck to remove someone from the rotation without deleting them.

### 6. Run the dev server

```bash
python manage.py runserver
```

Visit `http://127.0.0.1:8000/` and log in with your phone number.

---

## Twilio webhook setup

Twilio needs to be able to POST inbound SMS messages to your app. For local development, use [ngrok](https://ngrok.com/):

```bash
ngrok http 8000
```

Copy the `https://xxxx.ngrok.io` URL. In your [Twilio console](https://console.twilio.com/):

1. Go to **Phone Numbers → Manage → Active Numbers → your number**
2. Under **Messaging → A message comes in**, set:
   - **Webhook**: `https://xxxx.ngrok.io/sms/inbound/`
   - **HTTP method**: `POST`

### Twilio signature validation (production)

The webhook is currently open. For production, add validation by installing `django-twilio` or using Twilio's `RequestValidator` manually. Add this to `twilio_webhook` in `views.py`:

```python
from twilio.request_validator import RequestValidator
from django.conf import settings

validator = RequestValidator(settings.TWILIO_AUTH_TOKEN)
url = request.build_absolute_uri()
signature = request.META.get("HTTP_X_TWILIO_SIGNATURE", "")
if not validator.validate(url, request.POST, signature):
    return HttpResponse(status=403)
```

---

## How the coverage flow works

1. Employee logs in, creates a shift request (date / start / end / notes).
2. They can **Save as draft** or click **Find coverage**.
3. On Find coverage, the app finds the employee immediately below the requester in seniority and texts them.
4. **YES** → both parties get a confirmation text; search ends.
5. **NO** → requester is notified; next person down the roster is texted.
6. **UNSURE** → requester is notified; the request simultaneously continues to the next person.
7. If someone further down says YES while earlier people are still UNSURE, everyone who replied UNSURE (plus the requester) gets a text asking them to finalize with YES or NO.
8. If the entire roster is exhausted, the request is marked **Uncovered**.

All state changes are recorded in the **CoverageEvent** log, visible on the shift request detail page and in the Django admin.

---

## Timezone

The app defaults to `America/Chicago`. Change `TIME_ZONE` in `settings.py` if needed.

---

## Stretch goals (not yet built)

- Reminder SMS for UNSURE respondents who haven't resolved
- Manager admin view showing all open requests across all employees
- Email/push notification fallback
- Twilio signature validation middleware
