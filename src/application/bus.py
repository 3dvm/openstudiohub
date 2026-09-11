# =========================================================================================
# OPENSTUDIOHUB
# Module: src/application/bus.py
# Architectural role: In-process message bus for domain events
# =========================================================================================

"""Minimal synchronous, in-process pub/sub for domain events."""

from collections import defaultdict
from typing import Callable, DefaultDict, List, Type

from src.domain.shared_kernel.events import DomainEvent

Handler = Callable[[DomainEvent], None]


class MessageBus:
    """Routes domain events to registered handlers (same process, synchronous)."""

    def __init__(self) -> None:
        self._handlers: DefaultDict[Type[DomainEvent], List[Handler]] = defaultdict(list)

    def subscribe(self, event_type: Type[DomainEvent], handler: Handler) -> None:
        """Register a handler for a concrete event type."""
        self._handlers[event_type].append(handler)

    def publish(self, event: DomainEvent) -> None:
        """Deliver an event to every handler registered for its exact type."""
        for handler in self._handlers.get(type(event), []):
            handler(event)
