from abc import ABC, abstractmethod


class MessageSource(ABC):
    """
    Abstract interface for incoming promotion message sources
    (Telegram listener, WhatsApp listener, etc.).
    """

    @abstractmethod
    async def start(self) -> None:
        """Initializes the connection to the message source platform."""
        pass

    @abstractmethod
    async def listen(self) -> None:
        """Starts listening or polling for new incoming messages."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully disconnects and stops the listener."""
        pass
