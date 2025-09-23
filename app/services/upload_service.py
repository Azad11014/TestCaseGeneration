from fastapi import HTTPException, UploadFile
from pathlib import Path
from typing import Any, Dict

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.models import Documents, Projects, DocType


class DocumentUploadService:
    ALLOWED_EXTENSIONS = {'.pdf', '.docx', '.doc', '.txt', ".md", ".json"}
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
    ALLOWED_MIME_TYPES = {
        'application/pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/msword',
        'text/plain',
        'application/octet-stream'
    }

    def __init__(self, upload_dir: str = "data"):
        self.upload_dir = Path(upload_dir)
        self.upload_dir.mkdir(exist_ok=True)

        (self.upload_dir / "brd").mkdir(exist_ok=True)
        (self.upload_dir / "frd").mkdir(exist_ok=True)
        (self.upload_dir / "temp").mkdir(exist_ok=True)

    async def validate_files(self, file: UploadFile, document_type: str = "unknown") -> Dict[str, Any]:
        if not file or not file.filename:
            raise HTTPException(status_code=400, detail="No file provided")

        file_extension = Path(file.filename).suffix.lower()
        if file_extension not in self.ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"File extension '{file_extension}' not allowed. Allowed: {list(self.ALLOWED_EXTENSIONS)}"
            )

        content = await file.read()
        file_size = len(content)

        if file_size == 0:
            raise HTTPException(status_code=400, detail="File is empty")
        if file_size > self.MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"File size ({file_size:,} bytes) exceeds max allowed ({self.MAX_FILE_SIZE:,} bytes)"
            )

        return {
            "filename": file.filename,
            "size": file_size,
            "extension": file_extension,
        }

    async def upload_document(self, project_id: int, file: UploadFile, doctype: DocType, db: AsyncSession):
        try:
            project = await db.get(Projects, project_id)
            if not project:
                raise HTTPException(status_code=404, detail="Project not found")

            validation_result = await self.validate_files(file, doctype.value)

            # Assign next doc_number inside this project
            query = select(func.max(Documents.doc_number)).where(Documents.project_id == project_id)
            result = await db.execute(query)
            last_doc_number = result.scalar() or 0
            next_doc_number = last_doc_number + 1

            target_dir = self.upload_dir / doctype.value.lower()
            file_location = target_dir / file.filename
            await file.seek(0)
            with open(file_location, "wb") as buffer:
                buffer.write(await file.read())

            new_doc = Documents(
                project_id=project_id,
                doctype=doctype,
                file_path=str(file_location),
                doc_number=next_doc_number,
                version=1
            )
            db.add(new_doc)
            await db.commit()
            await db.refresh(new_doc)

            return {
                "success": True,
                "document_type": doctype.value,
                "document_id": new_doc.id,
                "doc_number": new_doc.doc_number,
                "file_path": str(file_location),
                "validation": validation_result
            }

        except HTTPException:
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(status_code=500, detail=f"Something went wrong: {e}")
