"""Fixed, fictitious inventory fixture.

Shared by the `lab_inventory` MCP tool and the `/inventory` REST route. Every
entry is made up: no real identities, subscriptions or resource names. This
is a harmless fixture, not a live read of anything -- see `rest.py` for why
`/inventory` is unauthenticated.
"""

from __future__ import annotations

from pydantic import BaseModel


class LabWidget(BaseModel):
    sku: str
    name: str
    quantity: int
    unit: str


FIXED_INVENTORY: tuple[LabWidget, ...] = (
    LabWidget(sku="WID-100", name="Widget Sprocket", quantity=42, unit="each"),
    LabWidget(sku="WID-200", name="Widget Gizmo", quantity=7, unit="crate"),
    LabWidget(sku="WID-300", name="Widget Doohickey", quantity=128, unit="each"),
)


def lab_inventory_as_dicts() -> list[dict[str, object]]:
    return [widget.model_dump() for widget in FIXED_INVENTORY]
