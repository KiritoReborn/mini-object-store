"""Validation and errors at the controller's HTTP boundaries."""
import json
import re
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import config

SYSTEM_FIELDS = frozenset({"object_id", "name", "size", "content_type", "created_at",
                           "updated_at", "sha256", "num_chunks", "chunks", "status"})


class StoreError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class ErrorResponse(BaseModel):
    error: str
    message: str


def validate_metadata(value: object) -> dict:
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
        raise ValueError("Metadata must be a JSON object with string keys")
    if SYSTEM_FIELDS.intersection(value):
        raise ValueError("System-maintained metadata keys cannot be changed")
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
    if len(encoded.encode("utf-8")) > config.MAX_METADATA_BYTES:
        raise ValueError(f"Metadata must not exceed {config.MAX_METADATA_BYTES} bytes")
    return value


def parse_metadata(text: str | None) -> dict:
    try:
        if text is not None and len(text.encode("utf-8")) > config.MAX_METADATA_BYTES:
            raise ValueError("Metadata exceeds the size limit")
        return validate_metadata(json.loads(text) if text is not None else {})
    except (ValueError, TypeError, RecursionError) as exc:
        raise StoreError(400, "INVALID_METADATA", "Metadata must be a finite JSON object within the size limit, without system keys") from exc


class Heartbeat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    worker_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$", strict=True)


class Registration(Heartbeat):
    base_url: str = Field(max_length=2048, strict=True)

    @field_validator("base_url")
    @classmethod
    def valid_base_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
                or any(ord(c) <= 32 or ord(c) == 127 for c in value)):
            raise ValueError("base_url must be an HTTP(S) origin without credentials or a path")
        parsed.port  # Validate malformed or out-of-range ports as well.
        return value.rstrip("/")


class MetadataPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metadata: dict

    @field_validator("metadata")
    @classmethod
    def valid_metadata(cls, value: dict) -> dict:
        return validate_metadata(value)


def safe_filename(value: str | None) -> str:
    name = (value or "").replace("\\", "/").rsplit("/", 1)[-1]
    if not name or name in {".", ".."} or len(name) > 255 or any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise StoreError(400, "INVALID_FILENAME", "File must have a safe name of at most 255 characters")
    return name


def safe_content_type(value: str | None) -> str:
    mime = (value or "").split(";", 1)[0].strip()
    return mime if re.fullmatch(r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+", mime) else "application/octet-stream"
