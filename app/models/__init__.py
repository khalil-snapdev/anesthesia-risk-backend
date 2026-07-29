from beanie import Document

from app.models.patient import Patient
from app.models.user import User

document_models: list[type[Document]] = [User, Patient]

__all__ = ["Patient", "User", "document_models"]
