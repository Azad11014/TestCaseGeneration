"""
frd_router.py
Router for FRD-specific test case generation endpoints
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.services.frd_services import FRDService
from app.schema.schema import TestCaseUpdateRequest
from database.database_connection import get_db

frd_router = APIRouter()

# Initialize FRD service
frd_service = FRDService()


@frd_router.get("/project/{project_id}/documents/{document_id}/generate-testcases-stream")
async def generate_frd_testcases_stream(
    project_id: int,
    document_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    Generate test cases for FRD document with streaming progress
    
    **Validates:** Document must be of type FRD
    
    Features:
    - Automatic vector store ingestion
    - Context-aware chunk processing
    - Issue detection with cross-chunk awareness
    - Real-time progress via SSE
    
    Args:
        project_id: Project ID
        document_id: FRD Document ID
        
    Returns:
        Server-Sent Events stream with generation progress
        
    Raises:
        400: If document is not FRD type
        404: If document not found
    """
    try:
        return StreamingResponse(
            frd_service.generate_testcases_stream(
                db=db,
                project_id=project_id,
                document_id=document_id
            ),
            media_type="text/event-stream"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"FRD test case generation failed: {str(e)}"
        )


@frd_router.post("/testcases/chat-update")
async def chat_update_frd_testcases(
    project_id: int = Query(..., description="Project ID"),
    document_id: int = Query(..., description="FRD Document ID"),
    commit: bool = Query(False, description="Commit changes or preview only"),
    request: TestCaseUpdateRequest = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Update FRD test cases using chat with context retrieval
    
    **Validates:** Document must be of type FRD
    
    The AI will:
    1. Validate document is FRD type
    2. Retrieve relevant FRD chunks based on your request
    3. Use that context to make informed updates
    4. Track which chunks influenced the changes
    
    Args:
        project_id: Project ID for context search
        document_id: FRD Document ID to update
        commit: If False, returns preview. If True, saves new version
        request: TestCaseUpdateRequest with message
    
    Example request body:
    ```json
    {
        "message": "Add validation test cases for user input fields"
    }
    ```
    
    Raises:
        400: If document is not FRD type
        404: If document or test cases not found
    """
    try:
        if not request:
            raise HTTPException(
                status_code=400,
                detail="Request body with 'message' field is required"
            )
        
        result = await frd_service.chat_update(
            db=db,
            project_id=project_id,
            document_id=document_id,
            request=request,
            commit=commit
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"FRD chat update failed: {str(e)}"
        )


@frd_router.get("/testcases/{testcase_id}")
async def get_frd_testcases(
    testcase_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    Get FRD test cases by ID with metadata
    
    Returns test cases with context-aware metadata including:
    - Which chunks influenced generation
    - Related FRD sections consulted
    - Context usage statistics
    
    Args:
        testcase_id: Test case ID
        
    Raises:
        404: If test case not found
    """
    try:
        result = await frd_service.get_testcases(db, testcase_id)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve FRD test cases: {str(e)}"
        )


@frd_router.post("/testcases/revert")
async def revert_frd_testcases(
    document_id: int = Query(..., description="FRD Document ID"),
    to_version: int = Query(..., description="Version to revert to"),
    db: AsyncSession = Depends(get_db)
):
    """
    Revert FRD test cases to a previous version
    
    **Validates:** Document must be of type FRD
    
    Args:
        document_id: FRD Document ID
        to_version: Target version number to revert to
        
    Raises:
        400: If document is not FRD type
        404: If document or version not found
    """
    try:
        result = await frd_service.revert(
            db=db,
            document_id=document_id,
            to_version=to_version
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"FRD revert failed: {str(e)}"
        )


@frd_router.get("/documents/{document_id}/versions")
async def list_frd_testcase_versions(
    document_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    List all test case versions for an FRD document
    
    **Validates:** Document must be of type FRD
    
    Shows version history with context usage info and metadata
    
    Args:
        document_id: FRD Document ID
        
    Raises:
        400: If document is not FRD type
        404: If document not found
    """
    try:
        result = await frd_service.get_document_versions(
            db=db,
            document_id=document_id
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list FRD versions: {str(e)}"
        )


@frd_router.get("/documents/{document_id}/context-stats")
async def get_frd_context_statistics(
    document_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    Get context usage statistics for FRD document test cases
    
    **Validates:** Document must be of type FRD
    
    Returns:
    - How many test cases used context
    - Average chunks consulted per test case
    - Most referenced FRD sections
    - Issue detection statistics
    
    Args:
        document_id: FRD Document ID
        
    Raises:
        400: If document is not FRD type
        404: If document or test cases not found
    """
    try:
        result = await frd_service.get_context_statistics(
            db=db,
            document_id=document_id
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get FRD context statistics: {str(e)}"
        )


@frd_router.get("/health")
async def frd_health_check():
    """Check if FRD service is running"""
    return {
        "status": "healthy",
        "service": "FRD",
        "document_type": "FRD",
        "features": [
            "Test case generation",
            "Context-aware processing",
            "Chat updates",
            "Version control"
        ]
    }