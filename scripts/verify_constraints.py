"""Standalone, manually-run check against the real dev database.

Confirms the unique indexes declared on User.email and
Patient.patient_identifier are actually enforced by MongoDB by inserting a
duplicate of each and checking that DuplicateKeyError is raised. Not part of
CI — run this by hand:

    python scripts/verify_constraints.py

Any documents it creates are deleted again before it exits, even on failure.
"""

import asyncio
import sys
import uuid
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from beanie import init_beanie
from pymongo import AsyncMongoClient
from pymongo.errors import DuplicateKeyError

from app.config import settings
from app.models import document_models
from app.models.patient import Patient, Sex
from app.models.user import User


async def verify_user_email_uniqueness(marker: str) -> bool:
    email = f"verify-constraints-{marker}@example.com"
    first = User(email=email, full_name="Constraint Check", google_sub_id=f"sub-{marker}-1")
    await first.insert()

    duplicate = User(email=email, full_name="Constraint Check Dup", google_sub_id=f"sub-{marker}-2")
    duplicate_was_inserted = False
    passed = False
    try:
        await duplicate.insert()
        duplicate_was_inserted = True
        print("FAIL: duplicate User.email insert succeeded — unique index is NOT enforced")
    except DuplicateKeyError:
        print("OK:   duplicate User.email insert raised DuplicateKeyError as expected")
        passed = True
    finally:
        await first.delete()
        if duplicate_was_inserted:
            await duplicate.delete()

    return passed


async def verify_patient_identifier_uniqueness(marker: str) -> bool:
    owner = User(
        email=f"verify-constraints-owner-{marker}@example.com",
        full_name="Constraint Check Owner",
        google_sub_id=f"sub-owner-{marker}",
    )
    await owner.insert()

    identifier = f"PT-verify-{marker}"
    first = Patient(
        patient_identifier=identifier,
        full_name="Constraint Check",
        dob=date(1990, 1, 1),
        sex=Sex.OTHER,
        surgery_date=date(2026, 8, 1),
        created_by=owner,
    )
    await first.insert()

    duplicate = Patient(
        patient_identifier=identifier,
        full_name="Constraint Check Dup",
        dob=date(1990, 1, 1),
        sex=Sex.OTHER,
        surgery_date=date(2026, 8, 1),
        created_by=owner,
    )
    duplicate_was_inserted = False
    passed = False
    try:
        await duplicate.insert()
        duplicate_was_inserted = True
        print(
            "FAIL: duplicate Patient.patient_identifier insert succeeded — "
            "unique index is NOT enforced"
        )
    except DuplicateKeyError:
        print(
            "OK:   duplicate Patient.patient_identifier insert raised "
            "DuplicateKeyError as expected"
        )
        passed = True
    finally:
        await first.delete()
        if duplicate_was_inserted:
            await duplicate.delete()
        await owner.delete()

    return passed


async def main() -> int:
    client: AsyncMongoClient[Any] = AsyncMongoClient(settings.MONGODB_URI)
    try:
        await init_beanie(database=client.get_default_database(), document_models=document_models)

        marker = uuid.uuid4().hex[:8]
        print(f"Connected. Running constraint checks (marker={marker})...\n")

        results = [
            await verify_user_email_uniqueness(marker),
            await verify_patient_identifier_uniqueness(marker),
        ]
    finally:
        await client.close()

    print()
    if all(results):
        print("All unique constraints verified.")
        return 0
    print("One or more unique constraints are NOT enforced — see FAIL lines above.")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
