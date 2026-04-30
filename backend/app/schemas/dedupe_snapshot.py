from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DedupeSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    uploaded_by: UUID
    uploaded_at: datetime
    row_count: int
    is_active: bool
    download_url: str | None = None
