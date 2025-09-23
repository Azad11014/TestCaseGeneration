from fastapi import APIRouter, File, Form, HTTPException, Depends, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.upload_service import DocumentUploadService
from app.models.models import DocType
from database.database_connection import get_db


upload_route = APIRouter()
upload_service = DocumentUploadService()


@upload_route.post("/{project_id}/upload")
async def upload_doc(
    project_id: int,
    file: UploadFile = File(...),
    doctype: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    # normalize doctype to uppercase so "brd" and "BRD" both work
    doctype_upper = doctype.upper()
    if doctype_upper not in DocType.__members__:
        raise HTTPException(status_code=400, detail="Invalid doctype. Use BRD or FRD.")

    return await upload_service.upload_document(project_id, file, DocType[doctype_upper], db)



# @frd_upload_route.post("/{project_id}/frd/upload")
# async def upload_frd(
#     project_id: int,
#     file: UploadFile = File(...),
#     doctype: str = Form(...),
#     db: AsyncSession = Depends(get_db)
#     ):
#     try:
#         # validate and convert string to Enum
#         if doctype not in DocType.__members__:
#             raise HTTPException(status_code=400, detail="Invalid doctype. Use BRD or FRD.")

#         result = await upload_service.brd_upload(project_id, file, DocType[doctype], db)
#         return result
#     except HTTPException:
#         raise
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))