from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


CompendiumCategory = Literal["item", "weapon", "armor", "spell", "condition", "monster", "action"]


class CompendiumEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    slug: str
    name: str
    category: CompendiumCategory
    system_pack: Optional[str] = None
    description: str = ""
    rules_text: str = ""
    tags: list[str] = Field(default_factory=list)
    action_cost: str = ""
    range_feet: int | None = None
    roll_expression: str = ""
    modifier: int = 0
    equipment_slot: str = ""
    armor_class_bonus: int = 0
    charges_max: int = 0
    restores_on: str = ""
    resource_costs: dict[str, int] = Field(default_factory=dict)
    applies_conditions: list[str] = Field(default_factory=list)
    is_builtin: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
