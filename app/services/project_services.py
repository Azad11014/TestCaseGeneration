"""
project_service.py
Updated to work with improved models schema
"""

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException
from sqlalchemy.orm import selectinload

from logs.logger_config import get_logger
from colorama import Fore, Style

logger = get_logger("ProjectService")

from app.models.models import Documents, Projects, Testcases, DocType
from app.schema.schema import ProjectCreate


class ProjectService:
    @staticmethod
    async def create_project(db: AsyncSession, project: ProjectCreate):
        """Create a new project"""
        try:
            # Check for duplicate project name
            res = await db.execute(
                select(Projects).where(func.lower(Projects.name) == project.name.lower())
            )
            if res.scalar_one_or_none():
                raise HTTPException(
                    status_code=403, 
                    detail=f"Project '{project.name}' already exists"
                )

            new_project = Projects(
                name=project.name, 
                description=project.description
            )
            db.add(new_project)
            await db.commit()
            await db.refresh(new_project)

            # Re-fetch with documents eagerly loaded
            result = await db.execute(
                select(Projects)
                .options(selectinload(Projects.documents))
                .where(Projects.id == new_project.id)
            )
            logger.info(Fore.GREEN + "Project created successfully..." + Style.RESET_ALL)
            return result.scalar_one()

        except HTTPException:
            raise
        except Exception as e:
            logger.error(Fore.RED + f"Error in project creation: {str(e)}" + Style.RESET_ALL)
            await db.rollback()
            raise HTTPException(status_code=500, detail=str(e))

    @staticmethod
    async def list_projects(db: AsyncSession):
        """List all projects with their documents"""
        try:
            result = await db.execute(
                select(Projects)
                .options(selectinload(Projects.documents))
                .order_by(Projects.created_at.desc())
            )
            projects = result.scalars().all()
            
            if not projects:
                raise HTTPException(status_code=404, detail="No projects found")
            
            logger.info(Fore.GREEN + "Projects listed successfully..." + Style.RESET_ALL)
            return projects
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

    @staticmethod
    async def get_project(db: AsyncSession, project_id: int) -> Projects:
        """Get a single project with documents and testcases"""
        try:
            result = await db.execute(
                select(Projects)
                .options(
                    selectinload(Projects.documents)
                    .selectinload(Documents.testcases)
                )
                .where(Projects.id == project_id)
            )
            project = result.scalar_one_or_none()
            
            if not project:
                raise HTTPException(status_code=404, detail="Project not found")
            
            logger.info(Fore.GREEN + f"Project {project_id} loaded successfully..." + Style.RESET_ALL)
            return project
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Something went wrong: {str(e)}")

    @staticmethod
    async def get_project_hierarchy(db: AsyncSession, project_id: int):
        """Get project with organized BRD → FRD → TestCases hierarchy"""
        try:
            result = await db.execute(
                select(Projects)
                .options(
                    selectinload(Projects.documents)
                    .selectinload(Documents.testcases)
                )
                .where(Projects.id == project_id)
            )
            project = result.scalar_one_or_none()
            
            if not project:
                raise HTTPException(status_code=404, detail="Project not found")
            
            # Organize documents by type
            brds = []
            frds = []
            
            for doc in project.documents:
                doc_data = {
                    "document_id": doc.id,
                    "doc_number": doc.doc_number,
                    "doctype": doc.doctype.value,
                    "version": doc.version,
                    "status": doc.status.value,
                    "source": doc.source.value,
                    "file_path": doc.file_path,
                    "original_filename": doc.original_filename,
                    "parent_brd_id": doc.parent_brd_id,
                    "created_at": doc.created_at.isoformat() if doc.created_at else None,
                    "testcases_count": len(doc.testcases),
                    "testcases": [
                        {
                            "testcase_id": tc.id,
                            "testcase_number": tc.testcase_number,
                            "title": tc.title,
                            "status": tc.status.value,
                            "version": tc.version,
                            "created_at": tc.created_at.isoformat() if tc.created_at else None
                        }
                        for tc in doc.testcases
                    ]
                }
                
                if doc.doctype == DocType.BRD:
                    # Add child FRDs to BRD
                    doc_data["child_frds"] = []
                    brds.append(doc_data)
                else:
                    frds.append(doc_data)
            
            # Attach FRDs to their parent BRDs
            for frd in frds:
                parent_brd_id = frd.get("parent_brd_id")
                if parent_brd_id:
                    for brd in brds:
                        if brd["document_id"] == parent_brd_id:
                            brd["child_frds"].append(frd)
                            break
            
            hierarchy = {
                "project_id": project.id,
                "project_name": project.name,
                "description": project.description,
                "created_at": project.created_at.isoformat() if project.created_at else None,
                "total_documents": len(project.documents),
                "total_brds": len(brds),
                "total_frds": len(frds),
                "documents": brds  # Only return BRDs at top level (FRDs are nested)
            }
            
            logger.info(Fore.GREEN + f"Project hierarchy loaded successfully..." + Style.RESET_ALL)
            return hierarchy
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(Fore.RED + f"Error loading hierarchy: {str(e)}" + Style.RESET_ALL)
            raise HTTPException(status_code=500, detail=f"Something went wrong: {str(e)}")

    @staticmethod
    async def get_testcases_for_project(db: AsyncSession, project_id: int):
        """Get all testcases across all documents in a project"""
        try:
            stmt = (
                select(Testcases)
                .join(Documents, Testcases.document_id == Documents.id)
                .where(Documents.project_id == project_id)
                .order_by(Documents.doc_number, Testcases.testcase_number)
            )
            result = await db.execute(stmt)
            testcases = result.scalars().all()
            
            logger.info(Fore.GREEN + f"Testcases loaded successfully for project {project_id}..." + Style.RESET_ALL)
            return testcases
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(Fore.RED + "Error loading testcases..." + Style.RESET_ALL)
            raise HTTPException(status_code=500, detail=f"Something went wrong: {e}")

    @staticmethod
    async def get_testcases_by_document(db: AsyncSession, project_id: int, document_id: int):
        """Get all testcases for a specific document"""
        try:
            # Verify document belongs to project
            doc_result = await db.execute(
                select(Documents).where(
                    Documents.id == document_id,
                    Documents.project_id == project_id
                )
            )
            doc = doc_result.scalar_one_or_none()
            if not doc:
                raise HTTPException(
                    status_code=404,
                    detail=f"Document {document_id} not found in project {project_id}"
                )
            
            # Get testcases
            stmt = (
                select(Testcases)
                .where(Testcases.document_id == document_id)
                .order_by(Testcases.testcase_number)
            )
            result = await db.execute(stmt)
            testcases = result.scalars().all()

            if not testcases:
                return []  # Return empty list instead of error
            
            logger.info(Fore.GREEN + f"Testcases loaded for document {document_id}..." + Style.RESET_ALL)
            return [
                {
                    "id": tc.id,
                    "document_id": tc.document_id,
                    "testcase_number": tc.testcase_number,
                    "title": tc.title,
                    "description": tc.description,
                    "version": tc.version,
                    "status": tc.status.value,
                    "file_path": tc.file_path,
                    "created_at": tc.created_at.isoformat() if tc.created_at else None,
                }
                for tc in testcases
            ]
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(Fore.RED + f"Error loading testcases: {str(e)}" + Style.RESET_ALL)
            raise HTTPException(status_code=500, detail=f"Something went wrong: {e}")

    @staticmethod
    async def get_document_stats(db: AsyncSession, project_id: int):
        """Get document statistics for a project"""
        try:
            # Verify project exists
            project = await db.get(Projects, project_id)
            if not project:
                raise HTTPException(status_code=404, detail="Project not found")
            
            # Count documents by type
            brd_count = await db.execute(
                select(func.count(Documents.id))
                .where(
                    Documents.project_id == project_id,
                    Documents.doctype == DocType.BRD
                )
            )
            
            frd_count = await db.execute(
                select(func.count(Documents.id))
                .where(
                    Documents.project_id == project_id,
                    Documents.doctype == DocType.FRD
                )
            )
            
            # Count total testcases
            tc_count = await db.execute(
                select(func.count(Testcases.id))
                .join(Documents, Testcases.document_id == Documents.id)
                .where(Documents.project_id == project_id)
            )
            
            stats = {
                "project_id": project_id,
                "project_name": project.name,
                "total_brds": brd_count.scalar() or 0,
                "total_frds": frd_count.scalar() or 0,
                "total_testcases": tc_count.scalar() or 0,
            }
            
            logger.info(Fore.GREEN + "Document stats loaded successfully..." + Style.RESET_ALL)
            return stats
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Something went wrong: {str(e)}")