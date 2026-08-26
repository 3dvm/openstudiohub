# =========================================================================================
# OPENSTUDIOHUB
# Module: src/domain/shared_kernel/events.py
# Architectural role: Shared Kernel / Domain Event base type
# =========================================================================================

"""Base type for domain events, shared across bounded contexts."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import uuid


@dataclass(frozen=True)
class DomainEvent:
    """Base class for all domain events."""

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
