"""Pydantic v2 models for workspace requests and responses."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

WorkspaceName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
WorkspaceDescription = Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)]
WorkspaceColor = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)
]
WorkspaceType = Literal["PERSONAL", "INSTITUTION"]
WorkspaceVisibility = Literal["PRIVATE", "SHARED"]
WorkspaceRole = Literal["OWNER", "ADMIN", "EDITOR", "VIEWER"]


class WorkspaceCreateRequest(BaseModel):
    """Details required to create a workspace."""

    model_config = ConfigDict(extra="forbid")

    workspace_name: WorkspaceName
    workspace_type: WorkspaceType
    description: WorkspaceDescription | None = None
    visibility: WorkspaceVisibility = "PRIVATE"
    storage_limit: int = Field(default=0, ge=0)
    color: WorkspaceColor = "blue"


class WorkspaceUpdateRequest(BaseModel):
    """Editable workspace settings; workspace type is immutable after creation."""

    model_config = ConfigDict(extra="forbid")

    workspace_name: WorkspaceName | None = None
    description: WorkspaceDescription | None = None
    visibility: WorkspaceVisibility | None = None
    color: WorkspaceColor | None = None

    @model_validator(mode="after")
    def require_change(self) -> "WorkspaceUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("At least one workspace setting must be provided")
        for field_name in ("workspace_name", "visibility", "color"):
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class WorkspaceStorageUpdateRequest(BaseModel):
    """The owner or an administrator's storage-limit update."""

    model_config = ConfigDict(extra="forbid")

    storage_limit: int = Field(ge=0)


class WorkspaceInvitationRequest(BaseModel):
    """An immediate membership invitation backed by ``workspace_members``."""

    model_config = ConfigDict(extra="forbid")

    user_id: int = Field(gt=0)
    role: WorkspaceRole = "VIEWER"


class WorkspaceMemberUpdateRequest(BaseModel):
    """A non-owner membership role update."""

    model_config = ConfigDict(extra="forbid")

    role: WorkspaceRole


class WorkspaceOwnershipTransferRequest(BaseModel):
    """The existing member who should become the workspace owner."""

    model_config = ConfigDict(extra="forbid")

    user_id: int = Field(gt=0)


class WorkspaceResponse(BaseModel):
    """Workspace state, including the caller's role when available."""

    workspace_id: int
    user_id: int
    workspace_name: str
    description: str | None
    workspace_type: WorkspaceType
    visibility: WorkspaceVisibility
    storage_used: int
    storage_limit: int
    color: str
    is_archived: bool
    created_at: datetime | None
    updated_at: datetime | None
    member_role: WorkspaceRole | None = None


class WorkspaceMemberResponse(BaseModel):
    """A workspace membership record."""

    member_id: int
    workspace_id: int
    user_id: int
    role: WorkspaceRole
    invited_by: int | None
    joined_at: datetime | None


class WorkspaceStorageResponse(BaseModel):
    """Storage allocation and consumption for a workspace."""

    workspace_id: int
    storage_used: int
    storage_limit: int


class WorkspaceActivityResponse(BaseModel):
    """An auditable workspace action stored through ``activity_logs``."""

    activity_id: int
    user_id: int
    activity_type: str
    activity_description: str | None
    created_at: datetime | None
