from fastapi import APIRouter, Body, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Dict, Any, Optional
from sqlalchemy import select

from app.models.models import Documents, FRDVersions
from app.schema.schema import TestCaseUpdateRequest
from database.database_connection import get_db
from app.services.ai_client_services import AiClientService
from app.services.frd_agent_service import FRDAgentService
from app.services.testcase_gen_service import TestGenServies

frd_router = APIRouter()
frd_agent = FRDAgentService()
tc_agent = TestGenServies()



@frd_router.post("/project/{project_id}/document/{document_id}/analyze")
async def analyze_frd(
    project_id: int,
    document_id: int,
    db: AsyncSession = Depends(get_db)
):
    doc = await db.get(Documents, document_id)
    if not doc or doc.project_id != project_id:
        raise HTTPException(status_code=404, detail="Document not found in project")
    return await frd_agent.analyze_frd_mapreduce(db, document_id)


@frd_router.post("/project/{project_id}/documents/{document_id}/frd/propose-fix")
async def propose_fix(
    project_id: int,
    document_id: int,
    issue_ids: List[int] = Body(..., embed=True),
    db: AsyncSession = Depends(get_db)
):
    doc = await db.get(Documents, document_id)
    if not doc or doc.project_id != project_id:
        raise HTTPException(status_code=404, detail="Document not found in project")

    if not issue_ids:
        raise HTTPException(status_code=400, detail="No issue IDs provided for proposing fixes")

    # fetch latest FRD version
    frd_version = (
        await db.execute(
            select(FRDVersions)
            .where(FRDVersions.frd_id == document_id)
            .order_by(FRDVersions.created_at.desc())
        )
    ).scalars().first()

    if not frd_version or not frd_version.changes:
        raise HTTPException(status_code=404, detail="No anomalies found for this document")

    all_anomalies = frd_version.changes.get("anomalies", [])

    # filter only selected anomalies by ID
    selected_issues = [a for a in all_anomalies if a.get("id") in issue_ids]

    if not selected_issues:
        raise HTTPException(status_code=404, detail="No anomalies found for given IDs")

    return await frd_agent.propose_fixes(db, document_id, selected_issues)



@frd_router.post("/project/{project_id}/documents/{document_id}/frd/apply-fix")
async def apply_fix(
    project_id: int,
    document_id: int,
    version_id: Optional[int] = Body(None, embed=True),  # optional, apply specific version
    db: AsyncSession = Depends(get_db)
):
    doc = await db.get(Documents, document_id)
    if not doc or doc.project_id != project_id:
        raise HTTPException(status_code=404, detail="Document not found in project")
    
    return await frd_agent.apply_fix(db, document_id, version_id)


@frd_router.post("/project/{project_id}/documents/{document_id}/testcases/generate")
async def generate_testcases(
    project_id: int,
    document_id: int,
    db: AsyncSession = Depends(get_db)
):
    doc = await db.get(Documents, document_id)
    if not doc or doc.project_id != project_id:
        raise HTTPException(status_code=404, detail="Document not found in project")
    
    return await tc_agent.generate_testcases(db, document_id)


@frd_router.post("/project/{project_id}/documents/{document_id}/testcases/chat")
async def chat_update(
    project_id: int,
    document_id: int,
    request: TestCaseUpdateRequest,
    db: AsyncSession = Depends(get_db)
):
    doc = await db.get(Documents, document_id)
    if not doc or doc.project_id != project_id:
        raise HTTPException(status_code=404, detail="Document not found in project")
    
    return await tc_agent.chat_update(db, document_id, request)


@frd_router.post("/project/{project_id}/documents/{document_id}/frd/revert")
async def revert_frd(
    project_id: int,
    document_id: int,
    to_version_id: int = Body(..., embed=True),
    db: AsyncSession = Depends(get_db)
):
    doc = await db.get(Documents, document_id)
    if not doc or doc.project_id != project_id:
        raise HTTPException(status_code=404, detail="Document not found in project")
    
    return await frd_agent.revert(db, document_id, to_version_id)



@frd_router.post("/project/{project_id}/documents/{document_id}/testcases/revert")
async def revert_testcases(
    project_id: int,
    document_id: int,
    to_id: int = Body(..., embed=True),
    db: AsyncSession = Depends(get_db)
):
    doc = await db.get(Documents, document_id)
    if not doc or doc.project_id != project_id:
        raise HTTPException(status_code=404, detail="Document not found in project")
    
    return await tc_agent.revert(db, document_id, to_id)
