from __future__ import annotations
from dataclasses import dataclass, field

@dataclass
class Panel:
    panel_id: int
    title: str
    label: str
    synonyms: list[str] = field(default_factory=list)
    panel_type: str = ""

@dataclass
class Dashboard:
    uid: str
    title: str
    panels: list[Panel] = field(default_factory=list)

@dataclass
class Category:
    name: str
    label: str
    dashboards: list[Dashboard] = field(default_factory=list)

@dataclass
class Candidate:
    category: str
    dashboard_uid: str
    panel_id: int
    label: str
    frm: str
    to: str
    confidence: float
    method: str
