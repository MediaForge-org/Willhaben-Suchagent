from abc import ABC, abstractmethod

from agent.app.core.models import Listing


class NotificationService(ABC):
    @abstractmethod
    async def notify_new_listing(self, listing: Listing) -> None:
        """Deliver a notification for a globally new listing."""


class FakeNotificationService(NotificationService):
    def __init__(self) -> None:
        self.notifications: list[Listing] = []

    async def notify_new_listing(self, listing: Listing) -> None:
        self.notifications.append(listing)
