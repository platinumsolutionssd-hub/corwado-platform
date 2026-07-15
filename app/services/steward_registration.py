"""
Shared land_steward creation path.

Both POST /api/stewards (web dashboard) and the Telegram NEWFARMER flow
create a new farmer record -- this is the one place that happens, so
duplicate detection and field handling exist exactly once rather than
being reimplemented per caller. See db/schema.sql's authorized_operator
migration note for the chat-registration design this supports.
"""
import re
from datetime import datetime
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app import models


def normalize_phone(raw: str) -> str:
    return re.sub(r"[\s\-]", "", raw)


def find_possible_duplicate(db: Session, phone_number: Optional[str]) -> Optional[models.LandSteward]:
    """
    Phone-number match against existing stewards. land_steward.phone_number
    deliberately has no UNIQUE constraint (a household can legitimately
    share one phone across multiple stewards), so this flags a possible
    duplicate for the caller to confirm rather than refusing outright.
    """
    if not phone_number:
        return None
    normalized = normalize_phone(phone_number)
    if not normalized:
        return None
    return db.query(models.LandSteward).filter_by(phone_number=normalized).first()


def create_steward(
    db: Session, data: dict, force_create: bool = False
) -> Tuple[Optional[models.LandSteward], Optional[models.LandSteward]]:
    """
    Creates a land_steward row from an already-validated field dict (a
    StewardIn.model_dump() from the router, or the equivalent dict the
    Telegram NEWFARMER flow builds up across its conversation).

    Returns (steward, duplicate):
    - No duplicate found: (new steward, None).
    - Duplicate found, force_create=False: (None, existing steward) --
      nothing is written; the caller shows the existing record and asks
      for confirmation.
    - Duplicate found, force_create=True: (new steward, existing steward)
      -- both are created/returned so the caller can still mention the
      match in its confirmation message.
    """
    data = dict(data)
    phone_number = data.get("phone_number")
    if phone_number:
        data["phone_number"] = normalize_phone(phone_number)

    duplicate = find_possible_duplicate(db, data.get("phone_number"))
    if duplicate and not force_create:
        return None, duplicate

    row_id = data.pop("id", None)
    registered_offline = data.get("registered_offline", False)
    db_steward = models.LandSteward(**data)
    if row_id:
        db_steward.id = row_id
    if not registered_offline:
        db_steward.synced_at = datetime.utcnow()
    db.add(db_steward)
    db.commit()
    db.refresh(db_steward)
    return db_steward, duplicate
