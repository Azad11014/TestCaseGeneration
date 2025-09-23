from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database.database_connection import get_db
from app.services.content_extraction_service import ContentExtractionService

extraction_router = APIRouter()
content_service = ContentExtractionService()


@extraction_router.get("/{project_id}/documents/{document_id}/extract")
async def extract_text(
    project_id: int,
    document_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Extract text from a document under a project"""
    return await content_service.extract_document_text(db, project_id, document_id)
