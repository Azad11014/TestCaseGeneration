from sqlalchemy.ext.declarative import declarative_base
import datetime
from sqlalchemy import JSON, Column, DateTime, ForeignKey, String, Integer, Boolean, Enum, Text,func
import enum
from sqlalchemy.orm import relationship

Base = declarative_base()

class DocType(enum.Enum):
    BRD = "BRD"
    FRD = "FRD"

class Status(enum.Enum):
    draft = "draft"
    in_review = "in_review"
    finalized = "finalized"

class Source(enum.Enum):
    uploaded = "uploaded"
    generated = "generated" 

class TestCaseStatus(enum.Enum):
    generated = "generated"
    approved = "approved"
    revised = "revised"


class Projects(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    description = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    documents = relationship("Documents", back_populates="project", cascade="all, delete-orphan")


class Documents(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True, index=True)

    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"))
    doctype = Column(Enum(DocType), nullable=False)

    # path to file
    file_path = Column(String, nullable=False)

    # per-project numbering
    doc_number = Column(Integer, nullable=False)  # 1,2,3 per project

    version = Column(Integer, nullable=False, default=1)  # version of this doc
    changes = Column(JSON, nullable=True)  # anomalies or metadata

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    project = relationship("Projects", back_populates="documents")
    testcases = relationship("Testcases", back_populates="document", cascade="all, delete-orphan")


class Testcases(Base):
    __tablename__ = "testcases"
    id = Column(Integer, primary_key=True, index=True)

    # link to document
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"))

    # per-document numbering
    testcase_number = Column(Integer, nullable=False)  # 1,2,3 per doc

    version = Column(Integer, nullable=False, default=1)  # for versioning testcases
    file_path = Column(String)
    status = Column(String, nullable=False, default="new")

    changes = Column(JSON, nullable=True)  # store updated chat/test details here
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    document = relationship("Documents", back_populates="testcases")



class FRDVersions(Base):
    __tablename__ = "frd_versions"

    id = Column(Integer, primary_key=True, index=True)  # version_id
    frd_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False)

    changes = Column(JSON, nullable=False)  # store diffs as JSON (user instructions + AI result)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    frd = relationship("Documents", backref="versions")

class BRDToFRDVersions(Base):
    __tablename__ = "brd_to_frd_versions"

    id = Column(Integer, primary_key=True, index=True)
    brd_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False)
    frd_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=True)

    changes = Column(JSON, nullable=False)  # store generated FRD JSON
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    brd = relationship("Documents", foreign_keys=[brd_id], backref="brd_versions")
    frd = relationship("Documents", foreign_keys=[frd_id], backref="from_brd_versions")


