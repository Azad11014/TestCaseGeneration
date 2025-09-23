from fastapi import APIRouter, Depends, Form, HTTPException
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
    selected_issues: SelectedIssuesModel,  # now validated JSON
    db: AsyncSession = Depends(get_db),
):
    return await brd_agent.propose_fix_to_btf(
        db,
        document_id,                   # brd_id or document_id
        selected_issues.dict()         # pass as Python dict to the service
    )



# ------------------------
# Apply fixes to FRD
# ------------------------
@brd_router.post("/project/{project_id}/document/{document_id}/brd/apply-fix/{version_id}")
async def apply_fix(
    project_id: int,
    document_id: int,
    version_id: int,
    db: AsyncSession = Depends(get_db),
):
    return await brd_agent.apply_fix_to_btf(db, document_id, version_id)


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
    return await brd_agent.generate(db, document_id)


# ------------------------
# Update testcases (chat-style)
# ------------------------
@brd_router.post("/project/{project_id}/document/{document_id}/testcases/update")
async def update_testcases(
    project_id: int,
    document_id: int,
    request: TestCaseUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    return await brd_agent.update_testcases(db, document_id, request=request, commit=request.commit)

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
