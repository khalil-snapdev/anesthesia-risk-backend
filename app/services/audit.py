from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from pymongo import AsyncMongoClient
from pymongo.asynchronous.client_session import AsyncClientSession

from app.models.audit_log import AuditAction, AuditLogEntry
from app.models.embedded import ActorSnapshot

_T = TypeVar("_T")


async def run_in_transaction(
    client: AsyncMongoClient[Any],
    callback: Callable[[AsyncClientSession], Awaitable[_T]],
) -> _T:
    """Run callback inside a MongoDB transaction on a fresh session.

    Per CLAUDE.md: audit log writes must happen inside the same
    transaction as the patient document update they're logging — never
    as a separate, unguaranteed step.
    """
    async with client.start_session() as session:
        return await session.with_transaction(callback)


async def record_audit_entry(
    session: AsyncClientSession,
    *,
    entity_type: str,
    entity_id: str,
    action: AuditAction,
    actor: ActorSnapshot,
    changes: dict[str, Any],
) -> None:
    entry = AuditLogEntry(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor=actor,
        changes=changes,
    )
    await entry.insert(session=session)
