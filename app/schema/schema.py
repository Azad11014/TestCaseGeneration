import datetime
from pydantic import BaseModel
from typing import List, Optional


# ------------------------
# Project + Document
# ------------------------
class ProjectBase(BaseModel):
    name: str
    description: Optional[str] = None


class ProjectCreate(ProjectBase):
    pass


class ProjectRead(ProjectBase):
    id: int
    created_at: datetime.datetime
    documents: List["DocumentRead"] = []


class DocumentBase(BaseModel):
    filename: str
    doctype: str
    file_path: str


class DocumentRead(DocumentBase):
    id: int
    created_at: datetime.datetime


class DocumentResponse(BaseModel):
    id: int
    project_id: int
    doctype: str
    file_path: str
    created_at: datetime.datetime

    class Config:
        orm_mode = True


class ProjectResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    created_at: Optional[datetime.datetime] = None 
    documents: List[DocumentResponse] = []

    class Config:
        orm_mode = True


# ------------------------
# FRD / BRD DTOs
# ------------------------
class FRDDocument(BaseModel):
    project_name: str
    doctype: str


class BRDDocument(BaseModel):
    project_name: str
    doctype: str


# ------------------------
# Update Requests
# ------------------------
class TestCaseUpdateRequest(BaseModel):
    """Payload for updating testcases (chat-style)."""
    message: str
    commit: bool = False


class UpdateBRDToFRD(BaseModel):
    """Payload for chat update of FRD converted from BRD."""
    message: str
    commit: bool = False

class Anomaly(BaseModel):
    section: str
    issue: str
    severity: str
    suggestion: Optional[str] = None

class SelectedIssuesModel(BaseModel):
    frd_id: int
    analysis_version_id: int
    anomalies: List[Anomaly]


class TestCaseChatRequest(BaseModel):
    message: str