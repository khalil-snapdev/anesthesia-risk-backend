from datetime import UTC, datetime
from enum import StrEnum
from typing import ClassVar

from beanie import Document, Save, before_event
from pydantic import EmailStr, Field
from pymongo import IndexModel


class Role(StrEnum):
    SURGEON = "surgeon"
    NURSE = "nurse"
    OFFICE_STAFF = "office_staff"


class User(Document):
    email: EmailStr
    full_name: str
    role: Role | None = None
    google_sub_id: str
    is_active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "users"
        indexes: ClassVar[list[IndexModel]] = [
            IndexModel("email", unique=True),
            IndexModel("google_sub_id", unique=True),
        ]

    @before_event(Save)
    def refresh_updated_at(self) -> None:
        self.updated_at = datetime.now(UTC)
