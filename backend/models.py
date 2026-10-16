"""Typed objects shared across agents."""
from typing import Literal

from pydantic import BaseModel, Field

RoleType = Literal["internship", "full-time", "both"]
Function = Literal[
    "consulting", "finance", "tech", "marketing", "operations",
    "healthcare", "energy", "general management", "other",
]


class Employer(BaseModel):
    company: str = Field(description="Company name exactly as written in the report")
    role_type: RoleType = Field(description="Hired MBAs for internships, full-time roles, or both")
    function: Function = Field(description="Main function the company hired MBAs into")
    location: str | None = Field(None, description="City/country only if the report states it, else null")
    page: int = Field(description="Page number (from the === PAGE n === marker) where the company appears")


class ReportExtraction(BaseModel):
    school: str | None = Field(None, description="Business school that published the report, if stated")
    employers: list[Employer]
