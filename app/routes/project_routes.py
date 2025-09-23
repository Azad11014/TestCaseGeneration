from app.models.models import Documents, Testcases
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import os
import json

from database.database_connection import get_db
from app.schema.schema import ProjectCreate, ProjectRead, ProjectResponse
from app.services.project_services import ProjectService

project_router = APIRouter()
testcase_route = APIRouter()
project_service = ProjectService()


# ------------------ Projects ------------------

@project_router.post("/create", response_model=ProjectRead)
async def create_project(project: ProjectCreate, db: AsyncSession = Depends(get_db)):
    return await project_service.create_project(db, project)

@project_router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: int, db: AsyncSession = Depends(get_db)):
    return await project_service.get_project(db, project_id)

@project_router.get("/projects", response_model=list[ProjectResponse])
async def list_projects(db: AsyncSession = Depends(get_db)):
    return await project_service.list_projects(db)


# ------------------ Testcases ------------------

@testcase_route.get("/{project_id}/testcases")
async def list_project_testcases(project_id: int, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Testcases)
        .join(Documents, Testcases.document_id == Documents.id)
        .where(Documents.project_id == project_id)
    )
    result = await db.execute(stmt)
    testcases = result.scalars().all()

    if not testcases:
        raise HTTPException(status_code=404, detail="No test cases found for this project")

    return [
        {
            "id": tc.id,
            "document_id": tc.document_id,
            "testcase_number": tc.testcase_number,
            "version": tc.version,
            "file_path": tc.file_path,
            "status": tc.status,  # plain string now
            "created_at": tc.created_at
        }
        for tc in testcases
    ]


@testcase_route.get("/testcases/{document_id}/versions")
async def get_testcase_versions(document_id: int, db: AsyncSession = Depends(get_db)):
    stmt = select(Testcases).where(Testcases.document_id == document_id).order_by(Testcases.version.asc())
    result = await db.execute(stmt)
    versions = result.scalars().all()

    if not versions:
        raise HTTPException(status_code=404, detail="No versions found for this document")

    return [
        {
            "id": v.id,
            "document_id": v.document_id,
            "testcase_number": v.testcase_number,
            "version": v.version,
            "file_path": v.file_path,
            "status": v.status,
            "created_at": v.created_at
        }
        for v in versions
    ]


@testcase_route.get("/testcases/{testcase_id}/preview")
async def preview_testcase(testcase_id: int, db: AsyncSession = Depends(get_db)):
    stmt = select(Testcases).where(Testcases.id == testcase_id)
    result = await db.execute(stmt)
    testcase = result.scalar_one_or_none()

    if not testcase:
        raise HTTPException(status_code=404, detail="Test case not found")

    if not testcase.file_path or not os.path.exists(testcase.file_path):
        raise HTTPException(status_code=404, detail="Test case file not found on disk")

    try:
        with open(testcase.file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read test case file: {str(e)}")

    return {
        "id": testcase.id,
        "document_id": testcase.document_id,
        "testcase_number": testcase.testcase_number,
        "version": testcase.version,
        "status": testcase.status,
        "created_at": testcase.created_at,
        "content": data
    }


@testcase_route.get("/project/{project_id}/document/{document_id}/testcases")
async def list_testcases_by_document(project_id: int, document_id: int, db: AsyncSession = Depends(get_db)):
    return await project_service.get_testcases_by_document(db, document_id)
