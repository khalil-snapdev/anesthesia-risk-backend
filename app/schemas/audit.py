from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.models.audit_log import AuditAction, AuditLogEntry
from app.models.embedded import ActorSnapshot


class AuditLogEntryRead(BaseModel):
    id: str
    entity_type: str
    entity_id: str
    action: AuditAction
    actor: ActorSnapshot
    changes: dict[str, Any]
    timestamp: datetime

    @classmethod
    def from_entry(cls, entry: AuditLogEntry) -> "AuditLogEntryRead":
        return cls(
            id=str(entry.id),
            entity_type=entry.entity_type,
            entity_id=entry.entity_id,
            action=entry.action,
            actor=entry.actor,
            changes=entry.changes,
            timestamp=entry.timestamp,
        )
