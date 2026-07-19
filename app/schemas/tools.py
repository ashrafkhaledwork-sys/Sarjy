import re

from pydantic import BaseModel, Field, field_validator

KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class SaveMemoryArgs(BaseModel):
    category: str = Field(description="identity | preference | context")
    key: str = Field(description="snake_case fact name, e.g. favorite_color")
    value: str = Field(min_length=1, max_length=500)

    @field_validator("category")
    @classmethod
    def category_allowed(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in {"identity", "preference", "context"}:
            raise ValueError("category must be identity, preference, or context")
        return v

    @field_validator("key")
    @classmethod
    def key_snake_case(cls, v: str) -> str:
        v = v.strip().lower().replace(" ", "_").replace("-", "_")
        if not KEY_RE.match(v):
            raise ValueError("key must be snake_case (letters, digits, underscores)")
        return v


class SearchRestaurantsArgs(BaseModel):
    near: str = Field(min_length=2, max_length=120, description="city, neighborhood, or area")
    query: str = Field(default="restaurant", max_length=80, description="cuisine or kind of food")
    limit: int = Field(default=3, ge=1, le=5)

    @field_validator("query")
    @classmethod
    def default_query(cls, v: str) -> str:
        return v.strip() or "restaurant"


class UpdateBookingArgs(BaseModel):
    """Loose types only - semantic validation happens per-field in the FSM so
    one bad value doesn't discard the good ones from the same turn."""

    cuisine: str | None = None
    area: str | None = None
    party_size: int | str | None = None
    date: str | None = None
    time: str | None = None

    def provided(self) -> dict:
        return {k: v for k, v in self.model_dump().items() if v is not None}


class SelectOptionArgs(BaseModel):
    n: int = Field(ge=1, le=9)


class DeleteMemoryArgs(BaseModel):
    key: str = Field(min_length=1, max_length=64)

    @field_validator("key")
    @classmethod
    def normalize(cls, v: str) -> str:
        return v.strip().lower().replace(" ", "_").replace("-", "_")
