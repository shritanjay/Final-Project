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


class ReportLink(BaseModel):
    school: str
    pdf_url: str | None = Field(None, description="Direct URL of the latest full-time MBA employment report PDF")
    report_year: str | None = Field(None, description="Class/year the report covers, e.g. 'Class of 2025'")
    page_url: str | None = Field(None, description="School page that links to the report (if no direct PDF found)")


class ReportLinks(BaseModel):
    reports: list[ReportLink]


class IndustryGroup(BaseModel):
    industry: str = Field(description="Industry name, e.g. 'Consulting', 'Banking & Investment Management', 'Technology'")
    companies: list[str] = Field(description="Company names exactly as given in the input list")


class EmployerSummary(BaseModel):
    overview: str = Field(description="2-4 sentence overview of where these schools' MBAs get hired")
    industries: list[IndustryGroup]


class CompanyResearch(BaseModel):
    company: str
    careers_url: str | None = Field(None, description="Official careers page URL")
    salary_base_low: int | None = Field(None, description="Low end of typical post-MBA base salary (annual, local currency)")
    salary_base_high: int | None = Field(None, description="High end of typical post-MBA base salary")
    salary_currency: str | None = Field(None, description="e.g. CAD, USD")
    salary_note: str | None = Field(None, description="Role/level the salary refers to and how reliable it is")
    salary_source_url: str | None = None
    mba_roles: list[str] = Field(default_factory=list, description="Typical roles they hire MBAs into, e.g. 'Associate', 'Product Manager'")
    locations: list[str] = Field(default_factory=list, description="Office cities in the target country")
    visa_sponsorship: HiresAnswer = Field("unsure", description="Whether they sponsor work visas in the country: yes/no/unsure")
    recruiting_notes: str | None = Field(None, description="MBA programs, application windows, recruiting timeline")
    custom_answer: str | None = Field(None, description="Answer to the student's extra question, if one was asked")
    sources: list[str] = Field(default_factory=list, description="URLs used")


class FitScore(BaseModel):
    company: str
    score: int = Field(ge=1, le=10, description="1-10 fit with the student's priorities")
    reason: str = Field(description="One short sentence")


class FitScores(BaseModel):
    scores: list[FitScore]
