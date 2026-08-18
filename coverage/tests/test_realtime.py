import json

from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TransactionTestCase

from coverage.consumers import NotificationConsumer
from coverage.notifications import notify
from coverage.realtime import push_notification
from .factories import make_employee, make_shift_request

User = get_user_model()


class NotificationConsumerTests(TransactionTestCase):
    """
    Uses TransactionTestCase (not TestCase) because the consumer's DB
    access runs via database_sync_to_async on a separate thread — a plain
    TestCase's transaction wrapping isn't visible across threads on SQLite.

    Tests the consumer directly with a manually-set scope["user"], the same
    thing AuthMiddlewareStack would populate from the session in production
    — that middleware itself is Channels' own code, not ours to re-test.
    """

    async def _communicator(self, user):
        communicator = WebsocketCommunicator(NotificationConsumer.as_asgi(), "/ws/notifications/")
        communicator.scope["user"] = user
        return communicator

    async def test_anonymous_user_is_rejected(self):
        communicator = await self._communicator(AnonymousUser())
        connected, _ = await communicator.connect()
        self.assertFalse(connected)
        await communicator.disconnect()

    async def test_user_without_employee_is_rejected(self):
        orphan = await database_sync_to_async(User.objects.create_user)(
            username="orphan", email="orphan@example.com"
        )
        communicator = await self._communicator(orphan)
        connected, _ = await communicator.connect()
        self.assertFalse(connected)
        await communicator.disconnect()

    async def test_employee_connects_successfully(self):
        employee = await database_sync_to_async(make_employee)("Alice", 1)
        communicator = await self._communicator(employee.user)
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        await communicator.disconnect()

    async def test_receives_a_directly_pushed_message(self):
        employee = await database_sync_to_async(make_employee)("Alice", 1)
        communicator = await self._communicator(employee.user)
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        await database_sync_to_async(push_notification)(employee.id, {"message": "hello"})

        message = await communicator.receive_from()
        self.assertEqual(json.loads(message), {"message": "hello"})
        await communicator.disconnect()

    async def test_only_the_targeted_employee_receives_the_push(self):
        alice = await database_sync_to_async(make_employee)("Alice", 1)
        bob = await database_sync_to_async(make_employee)("Bob", 2)
        alice_comm = await self._communicator(alice.user)
        bob_comm = await self._communicator(bob.user)
        await alice_comm.connect()
        await bob_comm.connect()

        await database_sync_to_async(push_notification)(alice.id, {"message": "for alice only"})

        message = await alice_comm.receive_from()
        self.assertEqual(json.loads(message)["message"], "for alice only")
        self.assertTrue(await bob_comm.receive_nothing())

        await alice_comm.disconnect()
        await bob_comm.disconnect()

    async def test_notify_pushes_new_notification_to_connected_employee(self):
        alice = await database_sync_to_async(make_employee)("Alice", 1)
        bob = await database_sync_to_async(make_employee)("Bob", 2)
        sr = await database_sync_to_async(make_shift_request)(alice)
        communicator = await self._communicator(bob.user)
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        await database_sync_to_async(notify)(bob, sr, "Alice needs coverage")

        message = await communicator.receive_from()
        data = json.loads(message)
        self.assertEqual(data["message"], "Alice needs coverage")
        self.assertEqual(data["unread_count"], 1)
        await communicator.disconnect()
