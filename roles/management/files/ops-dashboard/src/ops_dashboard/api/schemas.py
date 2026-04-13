"""Pydantic schemas for the FastAPI layer — mirrors models.py dataclasses."""

from pydantic import BaseModel


class ServiceSchema(BaseModel):
    name: str
    platform: str
    endpoint_type: str
    pod: str | None = None
    description: str = ""
    status: str = "unknown"
    cpu_shares: int | None = None
    memory_mb: int | None = None
    cost_per_hour: float | None = None
    ansible_tag: str | None = None
    azure_endpoint: str | None = None
    dependencies: list[str] = []
    cpu_percent: float | None = None
    memory_percent: float | None = None
    stack_group: str | None = None


class StackTierSchema(BaseModel):
    name: str
    description: str
    services: list[str]


class StackSchema(BaseModel):
    name: str
    description: str
    tiers: list[StackTierSchema]
    tier_names: list[str]
    current_tier: str | None = None


class ProfileSchema(BaseModel):
    name: str
    description: str
    services: dict[str, bool]
    stacks: dict[str, str] = {}
    estimated_cost_per_hour: float | None = None
    enabled_count: int = 0
    disabled_count: int = 0


class ProfileDiffSchema(BaseModel):
    starting: list[str]
    stopping: list[str]
    unchanged: list[str]


class SwitchProfileRequest(BaseModel):
    target_profile: str
    confirm: bool = False


class SwitchProfileResponse(BaseModel):
    diff: ProfileDiffSchema
    executed: bool
    message: str


class SetTierRequest(BaseModel):
    tier: str


class MetricsSnapshot(BaseModel):
    service_name: str
    timestamp: float = 0.0
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    memory_usage_mb: float = 0.0
    status: str = "unknown"


class ActionResponse(BaseModel):
    service: str
    action: str
    success: bool
    message: str
