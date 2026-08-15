"""Pydantic v2 request and response models for workspace folders."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.schemas.workspace import WorkspaceColor, WorkspaceDescription

FolderName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]


class FolderCreateRequest(BaseModel):
    """Details required to create a folder in an accessible workspace."""

    model_config = ConfigDict(extra="forbid")

    workspace_id: int = Field(gt=0)
    parent_folder_id: int | None = Field(default=None, gt=0)
    folder_name: FolderName
    description: WorkspaceDescription | None = None
    color: WorkspaceColor = "blue"


class FolderUpdateRequest(BaseModel):
    """Editable folder properties excluding its parent relationship."""

    model_config = ConfigDict(extra="forbid")

    folder_name: FolderName | None = None
    description: WorkspaceDescription | None = None
    color: WorkspaceColor | None = None
    is_favorite: bool | None = None

    @model_validator(mode="after")
    def require_change(self) -> "FolderUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("At least one folder field must be provided")
        for field_name in ("folder_name", "color", "is_favorite"):
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class FolderMoveRequest(BaseModel):
    """A new parent folder; ``null`` moves a folder to the workspace root."""

    model_config = ConfigDict(extra="forbid")

    parent_folder_id: int | None = Field(..., gt=0)


class FolderResponse(BaseModel):
    """A folder record from the existing ``folders`` table."""

    folder_id: int
    workspace_id: int
    parent_folder_id: int | None
    folder_name: str
    description: str | None
    color: str
    is_favorite: bool
    is_archived: bool
    created_by: int
    created_at: datetime | None
    updated_at: datetime | None


class FolderTreeResponse(FolderResponse):
    """A folder with its active child folders nested below it."""

    children: list["FolderTreeResponse"] = Field(default_factory=list)


FolderTreeResponse.model_rebuild()
