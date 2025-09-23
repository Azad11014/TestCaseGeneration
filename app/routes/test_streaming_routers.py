# app/routes/streaming_routes.py
import json
from typing import List
from app.services.ai_client_services import AiClientService
from app.services.content_extraction_service import ContentExtractionService
from fastapi import APIRouter, Depends, HTTPException, Body
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.models import Documents, FRDVersions
from app.services.frd_agent_service import FRDAgentService
from app.services.brd_agent_service import BRDAgentService
from app.services.testcase_gen_service import TestGenServies
from database.database_connection import get_db
from app.schema.schema import TestCaseChatRequest, TestCaseUpdateRequest

test_streaming_router = APIRouter()
brd_stream_router = APIRouter()
frd_agent = FRDAgentService()
tc_service = TestGenServies()
brd_agent = BRDAgentService()

ai_client = AiClientService()
extractor = ContentExtractionService()
tc_agent = TestGenServies()


# ----------------------FRD Stream FLOW ------------------------------------------------------
async def _check_document_in_project(db: AsyncSession, document_id: int, project_id: int):
    """Reusable doc/project checker."""
    doc = await db.get(Documents, document_id)
    if not doc or doc.project_id != project_id:
        raise HTTPException(status_code=404, detail="Document not found in project")
    return doc

@test_streaming_router.get("/project/{project_id}/frd/{document_id}/analyze/stream")
async def analyze_frd_stream(
    project_id: int,
    document_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Streaming analysis of an FRD document as SSE events.
    """
    doc = await db.get(Documents, document_id)
    if not doc or doc.project_id != project_id:
        raise HTTPException(status_code=404, detail="Document not found in project")

    async def event_generator():
        # await to get the async generator
        agen = await frd_agent.analyze_frd_mapreduce_stream(db, document_id)
        async for token in agen:
            yield f"data: {json.dumps({'text': token})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# @test_streaming_router.get("/project/{project_id}/frd/{document_id}/testcases/generate/stream")
# async def stream_testcases(document_id: int, db: AsyncSession = Depends(get_db)):
#     service = TestGenServies()
#     event_gen = await service.generate_testcases_stream(db, document_id)
#     return StreamingResponse(event_gen, media_type="text/event-stream")


# @test_streaming_router.get("/project/{project_id}/frd/{document_id}/testcases/generate/stream")
# async def generate_testcases_stream_endpoint(document_id: int, db: AsyncSession = Depends(get_db)):
    
#     generator = await tc_agent.generate_testcases_stream(db, document_id, ai_client, extractor)
#     return StreamingResponse(generator, media_type="text/event-stream")

@test_streaming_router.post("/project/{project_id}/documents/{document_id}/frd/propose-fix/stream")
async def propose_fix_stream(
    project_id: int,
    document_id: int,
    issue_ids: List[int] = Body(..., embed=True),
    db: AsyncSession = Depends(get_db)
):
    # Fetch document
    doc = await db.get(Documents, document_id)
    if not doc or doc.project_id != project_id:
        raise HTTPException(status_code=404, detail="Document not found in project")

    if not issue_ids:
        raise HTTPException(status_code=400, detail="No issue IDs provided for proposing fixes")

    # Fetch latest FRD version
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
    # Filter only selected anomalies
    selected_issues = {"anomalies": [a for a in all_anomalies if a.get("id") in issue_ids]}

    if not selected_issues["anomalies"]:
        raise HTTPException(status_code=404, detail="No anomalies found for given IDs")

    # Reuse existing service function
    return StreamingResponse(
        await frd_agent.propose_fix_stream(db, document_id, selected_issues["anomalies"]),
        media_type="text/event-stream"
    )


@test_streaming_router.get(
    "/project/{project_id}/frd/{document_id}/testcases/generate/stream"
)
async def generate_testcases_stream_endpoint(
    project_id: int,
    document_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Generate test cases for an FRD document and stream events as SSE.
    Logs & token-by-token updates first, final JSON of testcases at end.
    """
    # check doc belongs to project
    doc = await db.get(Documents, document_id)
    if not doc or doc.project_id != project_id:
        raise HTTPException(status_code=404, detail="Document not found in project")

    # get async generator from service
    generator = await tc_agent.generate_testcases_stream(
        db=db,
        document_id=document_id,
        ai_client=ai_client,
        content_extractor=extractor,
    )

    # return as SSE
    return StreamingResponse(generator, media_type="text/event-stream")




@test_streaming_router.post("/project/{project_id}/frd/{document_id}/testcases/update/stream")
async def stream_chat_update(project_id : int, document_id: int, request: TestCaseUpdateRequest, db: AsyncSession = Depends(get_db)):
    service = TestGenServies()
    event_gen = await service.chat_update_stream(db, document_id, request)
    return StreamingResponse(event_gen, media_type="text/event-stream")

@test_streaming_router.post("/testcases/{testcase_id}/chat")
async def chat_update_testcase(
    testcase_id: int,
    request: TestCaseChatRequest,
    db: AsyncSession = Depends(get_db)
):
    gen = await tc_agent.chat_update_testcase_stream(db, testcase_id, request)
    return StreamingResponse(gen, media_type="text/event-stream")



# --------------------------------BRD Stream Flow------------------------------------------
# app/routes/streaming_routes.py

async def sse_stream(generator):
    async for chunk in generator:
        if isinstance(chunk, (dict, list)):
            text_chunk = json.dumps(chunk, ensure_ascii=False)
        else:
            text_chunk = str(chunk)

        yield f"{text_chunk}\n"

    yield "data: [DONE]\n\n"





@brd_stream_router.get("/project/{project_id}/brd/{brd_id}/frd/stream")
async def stream_brd_to_frd(project_id: int, brd_id: int, db: AsyncSession = Depends(get_db)):
    gen = await brd_agent.stream_brd_to_frd(db, brd_id)
    return StreamingResponse(gen, media_type="text/event-stream")
@brd_stream_router.get("/project/{project_id}/brd/{brd_id}/analyze/stream")
async def stream_analyze_brd_frd(
    project_id: int,
    brd_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    Streams the FRD analysis (map-reduce style) for a given BRD ID.
    """
    # get the async generator from the agent
    gen = await brd_agent.stream_analyze_brd_frd(db, brd_id)
    # return as SSE
    return StreamingResponse(gen, media_type="text/event-stream")


@brd_stream_router.post("/project/{project_id}/brd/{brd_id}/propose-fix/stream")
async def stream_propose_fix_brd_frd(project_id: int, brd_id: int, request: List[int], db: AsyncSession = Depends(get_db)):
    gen = await brd_agent.stream_propose_fix_to_btf(db, brd_id, request)
    return StreamingResponse(gen, media_type="text/event-stream")


@brd_stream_router.post("/project/{project_id}/brd/{brd_id}/frd/update/stream")
async def stream_update_frd_brd(project_id: int, brd_id: int, request: dict, db: AsyncSession = Depends(get_db)):
    user_message = request.get("message")
    gen = await brd_agent.stream_update_frd(db, brd_id, user_message)
    return StreamingResponse(gen, media_type="text/event-stream")


@brd_stream_router.get("/project/{project_id}/brd/{brd_id}/testcases/generate/stream")
async def stream_generate_testcases_brd(project_id: int, brd_id: int, db: AsyncSession = Depends(get_db)):
    gen = await brd_agent.stream_generate_testcases(db, brd_id)
    return StreamingResponse(gen, media_type="text/event-stream")


@brd_stream_router.post("/project/{project_id}/brd/{brd_id}/testcases/update/stream")
async def stream_update_testcases_brd(project_id: int, brd_id: int, request: TestCaseUpdateRequest, db: AsyncSession = Depends(get_db)):
    gen = await brd_agent.stream_update_testcases(db, brd_id, request)
    return StreamingResponse(gen, media_type="text/event-stream")
