from pathlib import Path
from decouple import config

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config("SECRET_KEY", default="change-me-in-production")
DEBUG = config("DEBUG", default=True, cast=bool)
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="localhost,127.0.0.1").split(",")

# Render (like Heroku) terminates TLS at its edge and forwards plain HTTP to
# the app, so without this Django thinks every request is insecure — that
# breaks CSRF validation and secure cookies on login.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CSRF_TRUSTED_ORIGINS = [
    origin for origin in config("CSRF_TRUSTED_ORIGINS", default="").split(",") if origin
]

# Without this, a plain http:// request is served as-is instead of being
# redirected to https:// — which is why allauth was building an http://
# Google OAuth callback URL that Google's non-localhost redirect URIs reject.
SECURE_SSL_REDIRECT = not DEBUG

# Lets visitors skip Google OAuth entirely and log in as a seeded demo
# Employee instead — for letting someone try the app without owning a
# Google account that matches a provisioned Employee. Off by default;
# flip on temporarily (e.g. for a portfolio review) via the env var.
DEMO_LOGIN_ENABLED = config("DEMO_LOGIN_ENABLED", default=False, cast=bool)
DEMO_EMPLOYEE_EMAIL = config("DEMO_EMPLOYEE_EMAIL", default="demo@example.com")

INSTALLED_APPS = [
    # Must be first: this is what makes `manage.py runserver` serve ASGI
    # (HTTP + WebSockets) via Daphne instead of Django's default WSGI dev server.
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "phonenumber_field",
    "channels",
    "coverage",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "coverage.middleware.EmployeePreferencesMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

SITE_ID = 1

ROOT_URLCONF = "shift_coverage.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "shift_coverage.wsgi.application"
ASGI_APPLICATION = "shift_coverage.asgi.application"

# In-memory channel layer: fine for local dev (single process) but does NOT
# work across multiple worker processes. A production deployment running
# more than one process needs a shared backend instead, e.g. channels_redis:
#   CHANNEL_LAYERS = {"default": {"BACKEND": "channels_redis.core.RedisChannelLayer",
#                                  "CONFIG": {"hosts": [config("REDIS_URL", default="redis://localhost:6379")]}}}
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    }
}

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/Chicago"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Phone number field format
PHONENUMBER_DEFAULT_REGION = "US"

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
ACCOUNT_LOGOUT_ON_GET = True

# Google OAuth (django-allauth)
SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "SCOPE": ["profile", "email"],
        "APP": {
            "client_id": config("GOOGLE_CLIENT_ID", default=""),
            "secret": config("GOOGLE_CLIENT_SECRET", default=""),
            "key": "",
        },
    }
}
SOCIALACCOUNT_LOGIN_ON_GET = True
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_ADAPTER = "coverage.adapters.CoverageSocialAccountAdapter"
# Without this, a Google login whose email already belongs to an existing
# User (e.g. one created manually via /admin/) fails signup outright
# instead of linking the two — surfacing as a generic "Third-Party Login
# Failure" page rather than a specific error.
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True
