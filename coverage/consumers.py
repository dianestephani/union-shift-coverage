import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from .realtime import group_name_for_employee


class NotificationConsumer(AsyncWebsocketConsumer):
    """
    One connection per open browser tab. Joins a group scoped to the
    logged-in employee, so notify() can push new notifications straight to
    every tab that employee has open, instead of each tab polling on a timer.
    """

    async def connect(self):
        user = self.scope["user"]
        employee = await self._get_employee(user) if user.is_authenticated else None
        if employee is None:
            await self.close()
            return

        self.group_name = group_name_for_employee(employee.id)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def notification_message(self, event):
        """Handles a channel-layer group_send with type "notification.message"."""
        await self.send(text_data=json.dumps(event["payload"]))

    @database_sync_to_async
    def _get_employee(self, user):
        return getattr(user, "employee", None)
