"""
extraction_routes.py
Routes for content extraction and chunking operations
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database.database_connection import get_db
from app.services.text_extraction_service import ContentExtractionService

extraction_router = APIRouter()
content_service = ContentExtractionService()


@extraction_router.get("/{project_id}/documents/{document_id}/extract")
async def extract_text(
    project_id: int,
    document_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    Extract text content from a document (without chunking)
    
    - **project_id**: ID of the project
    - **document_id**: ID of the document
    
    Returns text length and preview
    """
    return await content_service.extract_document_text(db, project_id, document_id)


@extraction_router.get("/{project_id}/documents/{document_id}/extract-and-chunk")
async def extract_and_chunk(
    project_id: int,
    document_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    Extract text from a document and return chunked content
    
    - **project_id**: ID of the project
    - **document_id**: ID of the document
    
    Returns chunks with section IDs and text content
    """
    return await content_service.extract_and_chunk_document(db, project_id, document_id)