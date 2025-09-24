from typing import List
from fastapi import APIRouter, Depends, Form, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession

from app.schema.schema import (
    SelectedIssuesModel,
    UpdateBRDToFRD,
    TestCaseUpdateRequest,
)
from database.database_connection import get_db
from app.services.brd_agent_service import BRDAgentService

brd_router = APIRouter()
brd_agent = BRDAgentService()


# ------------------------
# Convert BRD -> FRD
# ------------------------
@brd_router.post("/project/{project_id}/document/{document_id}/convert")
async def convert_brd_to_frd(
    project_id: int,
    document_id: int,
    db: AsyncSession = Depends(get_db),
):
    return await brd_agent.brd_to_frd(db, document_id)

@brd_router.post("/project/{project_id}/document/{document_id}/bfrd/analyze")
async def analyze_brd_frd(
    project_id: int,
    document_id: int,   # BRD id
    db: AsyncSession = Depends(get_db),
):
    return await brd_agent.analyze_brd_frd(db, document_id)


@brd_router.post("/project/{project_id}/document/{document_id}/brd/propose-fix")
async def propose_fix(
    project_id: int,
    document_id: int,
    issue_ids: List[int] = Body(..., embed=True),  # now validated JSON
    db: AsyncSession = Depends(get_db),
):
    return await brd_agent.propose_fix_to_btf(
        db,
        document_id,                   # brd_id or document_id
        issue_ids         # pass as Python dict to the service
    )



# ------------------------
# Apply fixes to FRD
# ------------------------
@brd_router.post("/project/{project_id}/document/{document_id}/brd/apply-fix/{version_id}")
async def apply_fix(
    project_id: int,
    document_id: int,
    version_id: int,  # pass 0 to use latest anomalies if no proposed fixes
    db: AsyncSession = Depends(get_db),
):
    # Treat 0 as None to fallback to latest anomalies
    version_to_apply = None if version_id == 0 else version_id

    return await brd_agent.apply_fix_to_btf(
        db,
        brd_id=document_id,
        version_id=version_to_apply
    )


# ------------------------
# Chat update FRD
# ------------------------
# @brd_router.post("/project/{project_id}/document/{document_id}/update")
# async def chat_update(
#     project_id: int,
#     document_id: int,
#     request: UpdateBRDToFRD,
#     db: AsyncSession = Depends(get_db),
# ):
#     return await brd_agent.update_frd(db, document_id, request.message)





# ------------------------
# Generate testcases
# ------------------------
@brd_router.post("/project/{project_id}/document/{document_id}/testcases/generate")
async def generate_testcases(
    project_id: int,
    document_id: int,
    db: AsyncSession = Depends(get_db),
):
    return await brd_agent.generate_testcases(db, document_id)


# ------------------------
# Update testcases (chat-style)
# ------------------------
@brd_router.post("/project/{project_id}/document/{document_id}/testcases/update")
async def update_testcases(
    project_id: int,
    document_id: int,  # this is BRD id
    request: TestCaseUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Update testcases for the FRD derived from a BRD document.
    """
    return await brd_agent.update_testcases(
        db=db,
        brd_id=document_id,         # treat incoming document_id as BRD id
        request=request,
        commit=request.commit       # forward commit flag
    )


# ------------------------
# Revert FRD to older version
# ------------------------
@brd_router.post("/project/{project_id}/document/{document_id}/revert/{version_id}")
async def revert(
    project_id: int,
    document_id: int,
    version_id: int,
    db: AsyncSession = Depends(get_db),
):
    return await brd_agent.revert(db, document_id, version_id)
