from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, ClassVar

from beanie import Document
from pydantic import Field
from pymongo import IndexModel

from app.models.embedded import ActorSnapshot


class AuditAction(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    PDF_GENERATED = "pdf_generated"


class AuditLogEntry(Document):
    entity_type: str
    entity_id: str
    action: AuditAction
    actor: ActorSnapshot
    changes: dict[str, Any]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "audit_log"
        indexes: ClassVar[list[IndexModel]] = [
            IndexModel("entity_id"),
            IndexModel("timestamp"),
        ]
