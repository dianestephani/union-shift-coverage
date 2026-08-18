"""
ASGI config for shift_coverage. Handles both regular HTTP requests and the
WebSocket connections used for real-time notification delivery.

get_asgi_application() must run before anything that touches Django models
gets imported (it populates the app registry) — that's why the channels
routing import happens below it rather than at the top of the file.
"""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "shift_coverage.settings")

django_asgi_app = get_asgi_application()

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402

from coverage.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter(websocket_urlpatterns)
    ),
})
