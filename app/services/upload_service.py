"""
document_upload_service.py
Updated to work with your actual models schema
"""

from fastapi import HTTPException, UploadFile
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.models import Documents, Projects, DocType, BRDToFRDVersions
from logs.logger_config import get_logger
from colorama import Fore, Style

logger = get_logger("DocumentUploadService")


class DocumentUploadService:
    ALLOWED_EXTENSIONS = {'.pdf', '.docx', '.doc', '.txt', '.md', '.json'}
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

    def __init__(self, upload_dir: str = "data"):
        self.upload_dir = Path(upload_dir)
        self.upload_dir.mkdir(exist_ok=True)

        # Create subdirectories
        (self.upload_dir / "brd").mkdir(exist_ok=True)
        (self.upload_dir / "frd").mkdir(exist_ok=True)
        (self.upload_dir / "temp").mkdir(exist_ok=True)
        (self.upload_dir / "generated").mkdir(exist_ok=True)

        logger.info(Fore.GREEN + "Document Service initialized successfully..." + Style.RESET_ALL)

    async def validate_files(self, file: UploadFile, document_type: str = "unknown") -> Dict[str, Any]:
        """Validate uploaded file"""
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
        
        logger.info(Fore.GREEN + "Document validation successful..." + Style.RESET_ALL)
        return {
            "filename": file.filename,
            "size": file_size,
            "extension": file_extension,
        }

    async def upload_document(
        self, 
        project_id: int, 
        file: UploadFile, 
        doctype: DocType, 
        db: AsyncSession
    ):
        """Upload a document (BRD or FRD) to a project"""
        try:
            # Verify project exists
            project = await db.get(Projects, project_id)
            if not project:
                logger.error(Fore.RED + "Project not found..." + Style.RESET_ALL)
                raise HTTPException(status_code=404, detail="Project not found")

            # Validate file
            validation_result = await self.validate_files(file, doctype.value)

            # Get next doc_number for this project
            query = select(func.max(Documents.doc_number)).where(Documents.project_id == project_id)
            result = await db.execute(query)
            last_doc_number = result.scalar() or 0
            next_doc_number = last_doc_number + 1

            # Determine target directory
            target_dir = self.upload_dir / doctype.value.lower()
            
            # Create unique filename to avoid conflicts
            safe_filename = f"doc_{next_doc_number}_{file.filename}"
            file_location = target_dir / safe_filename

            # Save file
            await file.seek(0)
            with open(file_location, "wb") as buffer:
                buffer.write(await file.read())

            # Create document record
            new_doc = Documents(
                project_id=project_id,
                doctype=doctype,
                doc_number=next_doc_number,
                version=1,
                file_path=str(file_location),
                changes={
                    "file_size": validation_result["size"],
                    "file_extension": validation_result["extension"],
                    "original_filename": file.filename
                }
            )
            
            db.add(new_doc)
            await db.commit()
            await db.refresh(new_doc)
            
            logger.info(Fore.GREEN + f"Document uploaded successfully: {doctype.value} #{next_doc_number}..." + Style.RESET_ALL)

            return {
                "success": True,
                "document_id": new_doc.id,
                "document_type": doctype.value,
                "doc_number": new_doc.doc_number,
                "version": new_doc.version,
                "file_path": str(file_location),
                "validation": validation_result
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(Fore.RED + f"Error uploading document: {str(e)}" + Style.RESET_ALL)
            await db.rollback()
            raise HTTPException(status_code=500, detail=f"Document upload failed: {str(e)}")

    async def generate_frd_from_brd(
        self,
        db: AsyncSession,
        brd_id: int,
        frd_content: bytes,
        filename: str,
        conversion_prompt: Optional[str] = None,
        conversion_metadata: Optional[Dict] = None
    ):
        """Generate an FRD document from a BRD"""
        try:
            # Fetch parent BRD
            result = await db.execute(
                select(Documents).where(Documents.id == brd_id)
            )
            brd = result.scalar_one_or_none()
            
            if not brd:
                raise HTTPException(status_code=404, detail=f"BRD {brd_id} not found")
            
            if brd.doctype != DocType.BRD:
                raise HTTPException(status_code=400, detail="Source document must be a BRD")

            # Get next doc_number for the project
            query = select(func.max(Documents.doc_number)).where(
                Documents.project_id == brd.project_id
            )
            result = await db.execute(query)
            last_doc_number = result.scalar() or 0
            next_doc_number = last_doc_number + 1

            # Save generated FRD file
            target_dir = self.upload_dir / "generated"
            safe_filename = f"frd_from_brd_{brd.doc_number}_{filename}"
            file_location = target_dir / safe_filename
            
            with open(file_location, "wb") as f:
                f.write(frd_content)

            # Create FRD document
            frd = Documents(
                project_id=brd.project_id,
                doctype=DocType.FRD,
                doc_number=next_doc_number,
                version=1,
                file_path=str(file_location),
                changes={
                    "generated_from_brd": brd_id,
                    "conversion_prompt": conversion_prompt,
                    "file_size": len(frd_content),
                    "original_filename": filename
                }
            )
            
            db.add(frd)
            await db.flush()  # Get FRD ID before creating mapping

            # Create BRD → FRD mapping/version
            mapping = BRDToFRDVersions(
                brd_id=brd_id,
                frd_id=frd.id,
                changes={
                    "conversion_prompt": conversion_prompt,
                    "metadata": conversion_metadata or {}
                }
            )
            
            db.add(mapping)
            await db.commit()
            await db.refresh(frd)
            
            logger.info(Fore.GREEN + f"FRD #{frd.doc_number} generated from BRD #{brd.doc_number}..." + Style.RESET_ALL)

            return {
                "success": True,
                "frd_id": frd.id,
                "frd_doc_number": frd.doc_number,
                "source_brd_id": brd_id,
                "source_brd_doc_number": brd.doc_number,
                "file_path": str(file_location)
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(Fore.RED + f"Error generating FRD: {str(e)}" + Style.RESET_ALL)
            await db.rollback()
            raise HTTPException(status_code=500, detail=f"FRD generation failed: {str(e)}")

    async def get_document(self, db: AsyncSession, project_id: int, document_id: int):
        """Get document details"""
        try:
            result = await db.execute(
                select(Documents).where(
                    Documents.id == document_id,
                    Documents.project_id == project_id
                )
            )
            doc = result.scalar_one_or_none()
            
            if not doc:
                raise HTTPException(
                    status_code=404,
                    detail=f"Document {document_id} not found in project {project_id}"
                )
            
            return {
                "document_id": doc.id,
                "project_id": doc.project_id,
                "doctype": doc.doctype.value,
                "doc_number": doc.doc_number,
                "version": doc.version,
                "file_path": doc.file_path,
                "changes": doc.changes,
                "created_at": doc.created_at.isoformat() if doc.created_at else None,
                "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
            }
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error fetching document: {str(e)}")

    async def get_documents_by_type(
        self, 
        db: AsyncSession, 
        project_id: int, 
        doctype: DocType
    ):
        """Get all documents of a specific type in a project"""
        try:
            result = await db.execute(
                select(Documents)
                .where(
                    Documents.project_id == project_id,
                    Documents.doctype == doctype
                )
                .order_by(Documents.doc_number)
            )
            docs = result.scalars().all()
            
            return [
                {
                    "document_id": doc.id,
                    "doc_number": doc.doc_number,
                    "doctype": doc.doctype.value,
                    "version": doc.version,
                    "file_path": doc.file_path,
                    "changes": doc.changes,
                    "created_at": doc.created_at.isoformat() if doc.created_at else None,
                }
                for doc in docs
            ]
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error fetching documents: {str(e)}")

    async def get_brd_to_frd_versions(self, db: AsyncSession, brd_id: int):
        """Get all FRD versions generated from a specific BRD"""
        try:
            # Verify BRD exists
            brd = await db.get(Documents, brd_id)
            if not brd:
                raise HTTPException(status_code=404, detail="BRD not found")
            
            if brd.doctype != DocType.BRD:
                raise HTTPException(status_code=400, detail="Document must be a BRD")
            
            # Get all BRD to FRD mappings
            result = await db.execute(
                select(BRDToFRDVersions)
                .where(BRDToFRDVersions.brd_id == brd_id)
                .order_by(BRDToFRDVersions.created_at.desc())
            )
            mappings = result.scalars().all()
            
            # Get FRD details for each mapping
            frd_versions = []
            for mapping in mappings:
                if mapping.frd_id:
                    frd = await db.get(Documents, mapping.frd_id)
                    if frd:
                        frd_versions.append({
                            "mapping_id": mapping.id,
                            "frd_id": frd.id,
                            "doc_number": frd.doc_number,
                            "version": frd.version,
                            "file_path": frd.file_path,
                            "changes": mapping.changes,
                            "created_at": mapping.created_at.isoformat() if mapping.created_at else None,
                        })
            
            return {
                "brd_id": brd_id,
                "brd_doc_number": brd.doc_number,
                "total_frd_versions": len(frd_versions),
                "frd_versions": frd_versions
            }
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error fetching FRD versions: {str(e)}")