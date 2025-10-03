"""
upload_routes.py
Routes for document upload operations
"""

from fastapi import APIRouter, File, Form, HTTPException, Depends, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.services.upload_service import DocumentUploadService
from app.models.models import DocType
from database.database_connection import get_db

upload_router = APIRouter()
upload_service = DocumentUploadService()


@upload_router.post("/{project_id}/upload")
async def upload_document(
    project_id: int,
    file: UploadFile = File(...),
    doctype: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a document (BRD or FRD) to a project
    
    - **project_id**: ID of the project
    - **file**: Document file to upload
    - **doctype**: Type of document (BRD or FRD)
    """
    # Normalize doctype to uppercase
    doctype_upper = doctype.upper()
    if doctype_upper not in DocType.__members__:
        raise HTTPException(
            status_code=400, 
            detail="Invalid doctype. Use 'BRD' or 'FRD'."
        )
    
    doc_type = DocType[doctype_upper]
    
    return await upload_service.upload_document(
        project_id=project_id,
        file=file,
        doctype=doc_type,
        db=db
    )


@upload_router.get("/{project_id}/documents/{document_id}")
async def get_document(
    project_id: int,
    document_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get details of a specific document"""
    return await upload_service.get_document(db, project_id, document_id)


@upload_router.get("/{project_id}/documents")
async def list_documents(
    project_id: int,
    doctype: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    List all documents in a project, optionally filtered by type
    
    - **project_id**: ID of the project
    - **doctype**: Optional filter by document type (BRD or FRD)
    """
    if doctype:
        doctype_upper = doctype.upper()
        if doctype_upper not in DocType.__members__:
            raise HTTPException(
                status_code=400,
                detail="Invalid doctype. Use 'BRD' or 'FRD'."
            )
        return await upload_service.get_documents_by_type(
            db, project_id, DocType[doctype_upper]
        )
    
    # Return all documents if no filter
    brds = await upload_service.get_documents_by_type(db, project_id, DocType.BRD)
    frds = await upload_service.get_documents_by_type(db, project_id, DocType.FRD)
    return {"brds": brds, "frds": frds}


@upload_router.post("/{project_id}/brds/{brd_id}/generate-frd")
async def generate_frd(
    project_id: int,
    brd_id: int,
    file: UploadFile = File(...),
    conversion_prompt: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db)
):
    """
    Generate/upload an FRD from a BRD
    
    - **project_id**: ID of the project
    - **brd_id**: ID of the source BRD
    - **file**: Generated FRD file
    - **conversion_prompt**: Optional prompt/changes used for conversion
    """
    content = await file.read()
    
    return await upload_service.generate_frd_from_brd(
        db=db,
        brd_id=brd_id,
        frd_content=content,
        filename=file.filename,
        conversion_prompt=conversion_prompt,
        conversion_metadata={"content_type": file.content_type}
    )


@upload_router.get("/{project_id}/brds/{brd_id}/frds")
async def get_brd_to_frd_versions(
    project_id: int,
    brd_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get all FRD versions generated from a specific BRD"""
    return await upload_service.get_brd_to_frd_versions(db, brd_id)