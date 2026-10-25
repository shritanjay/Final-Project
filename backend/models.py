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


HiresAnswer = Literal["yes", "no", "unsure"]


class GeoCheck(BaseModel):
    careers_url: str | None = Field(None, description="Official careers page URL on the company's own domain or its ATS")
    hires_in_country: HiresAnswer = Field(description="yes = offices or job postings found in the country; no = clear evidence it doesn't; unsure = otherwise")
    evidence_url: str | None = Field(None, description="URL of the page that proves the answer")
    evidence_text: str | None = Field(None, description="Short quote or summary from that page (max ~200 chars)")


class MBAProgram(BaseModel):
    school: str = Field(description="Business school name, e.g. 'Rotman School of Management, University of Toronto'")
    city: str | None = Field(None, description="City where the program is based")
    qs_rank: str | None = Field(None, description="QS Global MBA rank as shown (e.g. '45', '101-110'), null if not found")
    source_url: str = Field(description="URL where the ranking/program info was found")
    employment_report_url: str | None = Field(None, description="URL of the school's MBA employment report page or PDF, if found")


class ProgramList(BaseModel):
    programs: list[MBAProgram] = Field(description="Top MBA programs in the country, best ranked first")
