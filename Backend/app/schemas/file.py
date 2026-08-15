"""Pydantic v2 request and response models for file metadata operations."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

FileName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]
FileExtension = Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)]
MimeType = Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]
StoragePath = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
FileHash = Annotated[str, StringConstraints(pattern=r"^[A-Fa-f0-9]{64}$")]
VersionNote = Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)]


class FileCreateRequest(BaseModel):
    """Metadata required for a new file record in an existing folder."""

    model_config = ConfigDict(extra="forbid")

    folder_id: int = Field(gt=0)
    file_name: FileName
    original_file_name: FileName
    file_extension: FileExtension | None = None
    mime_type: MimeType | None = None
    file_size: int = Field(ge=0)
    storage_path: StoragePath
    file_hash: FileHash
    ai_enabled: bool = False


class FileUpdateRequest(BaseModel):
    """Mutable file metadata that does not replace the underlying content."""

    model_config = ConfigDict(extra="forbid")

    file_name: FileName | None = None
    mime_type: MimeType | None = None
    ai_enabled: bool | None = None

    @model_validator(mode="after")
    def require_change(self) -> "FileUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("At least one file field must be provided")
        if "file_name" in self.model_fields_set and self.file_name is None:
            raise ValueError("file_name cannot be null")
        return self


class FileVersionCreateRequest(BaseModel):
    """Metadata for the next database-managed version of a file."""

    model_config = ConfigDict(extra="forbid")

    storage_path: StoragePath
    file_size: int = Field(ge=0)
    file_hash: FileHash
    version_note: VersionNote | None = None


class FileResponse(BaseModel):
    """File metadata visible to a caller with workspace access."""

    file_id: int
    folder_id: int
    uploaded_by: int
    file_name: str
    original_file_name: str
    file_extension: str | None
    mime_type: str | None
    file_size: int
    storage_path: str
    file_hash: str
    ai_enabled: bool
    is_archived: bool
    is_deleted: bool
    is_favorite: bool
    created_at: datetime | None
    updated_at: datetime | None


class FileVersionResponse(BaseModel):
    """An immutable metadata entry from the existing ``file_versions`` table."""

    version_id: int
    file_id: int
    version_number: int
    storage_path: str
    file_size: int
    file_hash: str
    uploaded_by: int
    version_note: str | None
    created_at: datetime | None
