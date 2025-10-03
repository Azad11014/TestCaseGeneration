"""
project_routes.py
Routes for project and testcase operations
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database.database_connection import get_db
from app.schema.schema import ProjectCreate, ProjectRead, ProjectResponse
from app.services.project_services import ProjectService

project_router = APIRouter()
testcase_router = APIRouter()
project_service = ProjectService()


# ------------------ Projects ------------------

@project_router.post("/create", response_model=ProjectRead)
async def create_project(
    project: ProjectCreate, 
    db: AsyncSession = Depends(get_db)
):
    """Create a new project"""
    return await project_service.create_project(db, project)


@project_router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: int, 
    db: AsyncSession = Depends(get_db)
):
    """Get a single project with documents and testcases"""
    return await project_service.get_project(db, project_id)


@project_router.get("/projects", response_model=list[ProjectResponse])
async def list_projects(db: AsyncSession = Depends(get_db)):
    """List all projects"""
    return await project_service.list_projects(db)


@project_router.get("/projects/{project_id}/hierarchy")
async def get_project_hierarchy(
    project_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    Get project with organized BRD → FRD → TestCases hierarchy
    
    Returns nested structure showing relationships between documents
    """
    return await project_service.get_project_hierarchy(db, project_id)


@project_router.get("/projects/{project_id}/stats")
async def get_project_stats(
    project_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get document statistics for a project"""
    return await project_service.get_document_stats(db, project_id)


# ------------------ Testcases ------------------

@testcase_router.get("/projects/{project_id}/testcases")
async def list_project_testcases(
    project_id: int, 
    db: AsyncSession = Depends(get_db)
):
    """
    Get all testcases across all documents in a project
    
    Returns list of testcases with their document associations
    """
    testcases = await project_service.get_testcases_for_project(db, project_id)
    
    if not testcases:
        raise HTTPException(
            status_code=404, 
            detail="No test cases found for this project"
        )
    
    return [
        {
            "id": tc.id,
            "document_id": tc.document_id,
            "testcase_number": tc.testcase_number,
            "title": tc.title,
            "description": tc.description,
            "version": tc.version,
            "file_path": tc.file_path,
            "status": tc.status.value,
            "created_at": tc.created_at.isoformat() if tc.created_at else None
        }
        for tc in testcases
    ]


@testcase_router.get("/projects/{project_id}/documents/{document_id}/testcases")
async def list_document_testcases(
    project_id: int,
    document_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    Get all testcases for a specific document
    
    - **project_id**: ID of the project
    - **document_id**: ID of the document
    """
    return await project_service.get_testcases_by_document(db, document_id)


@testcase_router.get("/testcases/{document_id}/versions")
async def get_testcase_versions(
    document_id: int, 
    db: AsyncSession = Depends(get_db)
):
    """
    Get all versions of testcases for a specific document
    
    - **document_id**: ID of the document
    
    Returns testcases ordered by version
    """
    from sqlalchemy import select
    from app.models.models import Testcases
    
    stmt = (
        select(Testcases)
        .where(Testcases.document_id == document_id)
        .order_by(Testcases.version.asc())
    )
    result = await db.execute(stmt)
    versions = result.scalars().all()

    if not versions:
        raise HTTPException(
            status_code=404, 
            detail="No versions found for this document"
        )

    return [
        {
            "id": v.id,
            "document_id": v.document_id,
            "testcase_number": v.testcase_number,
            "title": v.title,
            "version": v.version,
            "file_path": v.file_path,
            "status": v.status.value,
            "created_at": v.created_at.isoformat() if v.created_at else None
        }
        for v in versions
    ]


@testcase_router.get("/testcases/{testcase_id}/preview")
async def preview_testcase(
    testcase_id: int, 
    db: AsyncSession = Depends(get_db)
):
    """
    Preview testcase content from stored JSON file
    
    - **testcase_id**: ID of the testcase
    
    Returns testcase metadata and full content
    """
    import os
    import json
    from sqlalchemy import select
    from app.models.models import Testcases
    
    stmt = select(Testcases).where(Testcases.id == testcase_id)
    result = await db.execute(stmt)
    testcase = result.scalar_one_or_none()

    if not testcase:
        raise HTTPException(status_code=404, detail="Test case not found")

    if not testcase.file_path or not os.path.exists(testcase.file_path):
        raise HTTPException(
            status_code=404, 
            detail="Test case file not found on disk"
        )

    try:
        with open(testcase.file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to read test case file: {str(e)}"
        )

    return {
        "id": testcase.id,
        "document_id": testcase.document_id,
        "testcase_number": testcase.testcase_number,
        "title": testcase.title,
        "version": testcase.version,
        "status": testcase.status.value,
        "created_at": testcase.created_at.isoformat() if testcase.created_at else None,
        "content": data
    }