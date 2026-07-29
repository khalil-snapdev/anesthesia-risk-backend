from beanie import Document

from app.models.audit_log import AuditLogEntry
from app.models.patient import Patient
from app.models.user import User

document_models: list[type[Document]] = [User, Patient, AuditLogEntry]

__all__ = ["AuditLogEntry", "Patient", "User", "document_models"]
