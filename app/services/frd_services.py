"""
frd_service.py
FRD-specific test case generation service with document type validation
"""

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, AsyncGenerator

from app.services.testcase_generation_service import EnhancedTestGenService
from app.models.models import Documents, DocType
from app.schema.schema import TestCaseUpdateRequest
from logs.logger_config import get_logger
from colorama import Fore, Style

logger = get_logger("FRDService")


class FRDService:
    """
    FRD (Functional Requirements Document) specific service
    Validates document type and delegates to test case generation service
    """
    
    def __init__(self):
        self.testgen_service = EnhancedTestGenService()
        logger.info(
            Fore.CYAN + 
            "FRD Service initialized" + 
            Style.RESET_ALL
        )
    
    async def _validate_frd_document(
        self, 
        db: AsyncSession, 
        document_id: int
    ) -> Documents:
        """
        Validate that the document exists and is of type FRD
        
        Args:
            db: Database session
            document_id: Document ID to validate
            
        Returns:
            Documents: The validated document
            
        Raises:
            HTTPException: If document not found or not FRD type
        """
        doc = await db.get(Documents, document_id)
        
        if not doc:
            raise HTTPException(
                status_code=404,
                detail=f"Document {document_id} not found"
            )
        
        # Check if document is FRD
        doc_type = doc.doctype.value if hasattr(doc.doctype, "value") else doc.doctype
        
        if doc_type != "FRD":
            raise HTTPException(
                status_code=400,
                detail=f"Document {document_id} is not an FRD document. Found type: {doc_type}"
            )
        
        logger.info(
            Fore.GREEN + 
            f"Validated FRD document {document_id}" + 
            Style.RESET_ALL
        )
        
        return doc
    
    async def generate_testcases_stream(
        self,
        db: AsyncSession,
        project_id: int,
        document_id: int
    ) -> AsyncGenerator[str, None]:
        """
        Generate test cases for FRD document with streaming
        
        Args:
            db: Database session
            project_id: Project ID
            document_id: FRD Document ID
            
        Yields:
            SSE events with generation progress
            
        Raises:
            HTTPException: If document is not FRD type
        """
        # Validate FRD document type
        await self._validate_frd_document(db, document_id)
        
        logger.info(
            Fore.BLUE + 
            f"Starting FRD test case generation for document {document_id}" + 
            Style.RESET_ALL
        )
        
        # Delegate to test generation service
        async for event in self.testgen_service.generate_testcases_stream(
            db=db,
            project_id=project_id,
            document_id=document_id
        ):
            yield event
    
    async def chat_update(
        self,
        db: AsyncSession,
        project_id: int,
        document_id: int,
        request: TestCaseUpdateRequest,
        commit: bool = False
    ) -> Dict:
        """
        Update FRD test cases via chat
        
        Args:
            db: Database session
            project_id: Project ID
            document_id: FRD Document ID
            request: Update request with message
            commit: Whether to save changes
            
        Returns:
            Dict with update results
            
        Raises:
            HTTPException: If document is not FRD type
        """
        # Validate FRD document type
        await self._validate_frd_document(db, document_id)
        
        logger.info(
            Fore.BLUE + 
            f"Processing FRD chat update for document {document_id}" + 
            Style.RESET_ALL
        )
        
        # Delegate to test generation service
        result = await self.testgen_service.chat_update(
            db=db,
            project_id=project_id,
            document_id=document_id,
            request=request,
            commit=commit
        )
        
        return result
    
    async def get_testcases(
        self, 
        db: AsyncSession, 
        testcase_id: int
    ) -> Dict:
        """
        Get FRD test cases by ID
        
        Note: This doesn't validate FRD type since we're accessing by testcase_id
        Use with caution or add document_id parameter for validation
        """
        return await self.testgen_service.get_testcases_with_issues(
            db=db, 
            testcase_id=testcase_id
        )
    
    async def revert(
        self, 
        db: AsyncSession, 
        document_id: int, 
        to_version: int
    ) -> Dict:
        """
        Revert FRD test cases to a previous version
        
        Args:
            db: Database session
            document_id: FRD Document ID
            to_version: Version number to revert to
            
        Returns:
            Dict with revert results
            
        Raises:
            HTTPException: If document is not FRD type
        """
        # Validate FRD document type
        await self._validate_frd_document(db, document_id)
        
        logger.info(
            Fore.YELLOW + 
            f"Reverting FRD document {document_id} to version {to_version}" + 
            Style.RESET_ALL
        )
        
        return await self.testgen_service.revert(
            db=db,
            document_id=document_id,
            to_version=to_version
        )
    
    async def get_document_versions(
        self,
        db: AsyncSession,
        document_id: int
    ) -> Dict:
        """
        Get all test case versions for an FRD document
        
        Args:
            db: Database session
            document_id: FRD Document ID
            
        Returns:
            Dict with version history
            
        Raises:
            HTTPException: If document is not FRD type
        """
        from sqlalchemy import select
        from app.models.models import Testcases
        
        # Validate FRD document type
        await self._validate_frd_document(db, document_id)
        
        result = await db.execute(
            select(Testcases)
            .where(Testcases.document_id == document_id)
            .order_by(Testcases.version.desc())
        )
        versions = result.scalars().all()
        
        return {
            "document_id": document_id,
            "document_type": "FRD",
            "total_versions": len(versions),
            "versions": [
                {
                    "testcase_id": v.id,
                    "version": v.version,
                    "status": v.status,
                    "created_at": v.created_at.isoformat() if v.created_at else None,
                    "metadata": v.changes
                }
                for v in versions
            ]
        }
    
    async def get_context_statistics(
        self,
        db: AsyncSession,
        document_id: int
    ) -> Dict:
        """
        Get context usage statistics for FRD document test cases
        
        Args:
            db: Database session
            document_id: FRD Document ID
            
        Returns:
            Dict with context statistics
            
        Raises:
            HTTPException: If document is not FRD type
        """
        from sqlalchemy import select
        from app.models.models import Testcases
        from pathlib import Path
        import json
        
        # Validate FRD document type
        await self._validate_frd_document(db, document_id)
        
        # Get latest version
        result = await db.execute(
            select(Testcases)
            .where(Testcases.document_id == document_id)
            .order_by(Testcases.version.desc())
            .limit(1)
        )
        latest = result.scalar_one_or_none()
        
        if not latest:
            raise HTTPException(
                status_code=404,
                detail=f"No test cases found for FRD document {document_id}"
            )
        
        # Load test case data
        file_path = Path(latest.file_path)
        if not file_path.exists():
            raise HTTPException(
                status_code=404, 
                detail="Test case file not found"
            )
        
        data = json.loads(file_path.read_text(encoding="utf-8"))
        testcases = data.get("testcases", [])
        metadata = data.get("metadata", {})
        
        # Calculate statistics
        context_enabled = sum(
            1 for tc in testcases if tc.get("generated_with_context")
        )
        total_chunks_used = sum(
            tc.get("related_chunks_consulted", 0) for tc in testcases
        )
        avg_chunks = total_chunks_used / len(testcases) if testcases else 0
        
        # Count section references
        section_refs = {}
        for tc in testcases:
            for section in tc.get("related_chunks", []):
                section_refs[section] = section_refs.get(section, 0) + 1
        
        top_sections = sorted(
            section_refs.items(), 
            key=lambda x: x[1], 
            reverse=True
        )[:5]
        
        return {
            "document_id": document_id,
            "document_type": "FRD",
            "version": latest.version,
            "total_testcases": len(testcases),
            "context_statistics": {
                "context_enabled_testcases": context_enabled,
                "percentage_with_context": round(
                    context_enabled / len(testcases) * 100, 2
                ) if testcases else 0,
                "total_chunks_consulted": total_chunks_used,
                "avg_chunks_per_testcase": round(avg_chunks, 2),
                "total_issues_found": metadata.get("total_issues", 0),
                "most_referenced_sections": [
                    {"section_id": section, "references": count}
                    for section, count in top_sections
                ]
            },
            "generation_metadata": {
                "context_aware": metadata.get("context_aware", False),
                "vector_store_used": metadata.get("vector_store_used", False),
                "total_chunks_processed": metadata.get("total_chunks", 0)
            }
        }