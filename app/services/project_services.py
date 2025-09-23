from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException
from sqlalchemy.orm import selectinload


from app.models.models import Documents, Projects, Testcases
from app.schema.schema import ProjectCreate

class ProjectService:
    @staticmethod
    async def create_project(db: AsyncSession, project: ProjectCreate):
        try:
            # Check if project already exists
            db_project = await db.execute(
                select(Projects).where(func.lower(Projects.name) == project.name.lower())
            )
            project_exists = db_project.scalar_one_or_none()
            if project_exists:
                raise HTTPException(
                    status_code=403,
                    detail=f"Project '{str(project.name)}' already exists"
                )
            
            new_project = Projects(
                name=project.name,
                description=project.description
            )
            db.add(new_project)
            await db.commit()
            await db.refresh(new_project)

            return new_project
        except HTTPException:
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(status_code=500, detail=f"Something broke: {e}")

    @staticmethod
    async def list_projects(db: AsyncSession):
        try:
            result = await db.execute(
                select(Projects).options(selectinload(Projects.documents))
            )
            projects = result.scalars().all()
            if not projects:
                raise HTTPException(status_code=404, detail="No projects found")
            return projects
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Internal Server Error {str(e)}")

    @staticmethod
    async def get_project(db: AsyncSession, project_id: int) -> Projects:
        try:
            result = await db.execute(
                select(Projects)
                .options(selectinload(Projects.documents).selectinload(Documents.testcases))
                .where(Projects.id == project_id)
            )
            project = result.scalar_one_or_none()
            if not project:
                raise HTTPException(status_code=404, detail="No project found")
            return project
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Something went wrong {str(e)}")

    
    async def get_test_cases_for_project(self, db: AsyncSession, project_id: int):
        try:
            stmt = (
                select(Testcases)
                .join(Documents, Testcases.document_id == Documents.id)
                .where(Documents.project_id == project_id)
            )
            result = await db.execute(stmt)
            return result.scalars().all()
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Something went wrong: {e}")
        
    async def get_testcases_by_document(self, db: AsyncSession, document_id: int):
        stmt = select(Testcases).where(Testcases.document_id == document_id)
        result = await db.execute(stmt)
        testcases = result.scalars().all()

        if not testcases:
            raise HTTPException(
                status_code=404,
                detail=f"No test cases found for document_id={document_id}"
            )

        return [
            {
                "id": tc.id,
                "document_id": tc.document_id,
                "testcase_number": tc.testcase_number,
                "version": tc.version,
                "file_path": tc.file_path,
                "status": tc.status,  # plain string now
                "created_at": tc.created_at,
            }
            for tc in testcases
        ]
