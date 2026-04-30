"""Merge negative_area_pincodes + cam_discrepancy_resolutions migration heads.

Revision ID: f7c8d9e0a1b2
Revises: c3d4e5f6a7b8, e2f3a4b5c6d7
Create Date: 2026-04-26
"""
from typing import Sequence, Union


revision: str = "f7c8d9e0a1b2"
down_revision: Union[str, Sequence[str], None] = ("c3d4e5f6a7b8", "e2f3a4b5c6d7")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
