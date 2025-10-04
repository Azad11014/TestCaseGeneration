"""
brd_service.py
BRD-specific test case generation service with document type validation
"""

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, AsyncGenerator

from app.services.testcase_generation_service import EnhancedTestGenService
from app.models.models import Documents, DocType
from app.schema.schema import TestCaseUpdateRequest
from logs.logger_config import get_logger
from colorama import Fore, Style

logger = get_logger("BRDService")


class BRDService:
    """
    BRD (Business Requirements Document) specific service
    Validates document type and delegates to test case generation service
    """
    
    def __init__(self):
        self.testgen_service = EnhancedTestGenService()
        logger.info(
            Fore.CYAN + 
            "BRD Service initialized" + 
            Style.RESET_ALL
        )
    
    async def _validate_brd_document(
        self, 
        db: AsyncSession, 
        document_id: int
    ) -> Documents:
        """
        Validate that the document exists and is of type BRD
        
        Args:
            db: Database session
            document_id: Document ID to validate
            
        Returns:
            Documents: The validated document
            
        Raises:
            HTTPException: If document not found or not BRD type
        """
        doc = await db.get(Documents, document_id)
        
        if not doc:
            raise HTTPException(
                status_code=404,
                detail=f"Document {document_id} not found"
            )
        
        # Check if document is BRD
        doc_type = doc.doctype.value if hasattr(doc.doctype, "value") else doc.doctype
        
        if doc_type != "BRD":
            raise HTTPException(
                status_code=400,
                detail=f"Document {document_id} is not a BRD document. Found type: {doc_type}"
            )
        
        logger.info(
            Fore.GREEN + 
            f"Validated BRD document {document_id}" + 
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
        Generate test cases for BRD document with streaming
        
        Args:
            db: Database session
            project_id: Project ID
            document_id: BRD Document ID
            
        Yields:
            SSE events with generation progress
            
        Raises:
            HTTPException: If document is not BRD type
        """
        # Validate BRD document type
        await self._validate_brd_document(db, document_id)
        
        logger.info(
            Fore.BLUE + 
            f"Starting BRD test case generation for document {document_id}" + 
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
        Update BRD test cases via chat
        
        Args:
            db: Database session
            project_id: Project ID
            document_id: BRD Document ID
            request: Update request with message
            commit: Whether to save changes
            
        Returns:
            Dict with update results
            
        Raises:
            HTTPException: If document is not BRD type
        """
        # Validate BRD document type
        await self._validate_brd_document(db, document_id)
        
        logger.info(
            Fore.BLUE + 
            f"Processing BRD chat update for document {document_id}" + 
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
    
    async def convert_brd_to_frd(
        self,
        db: AsyncSession,
        project_id: int,
        brd_document_id: int,
        conversion_instructions: str = None
    ) -> Dict:
        """
        Convert BRD to FRD document using AI
        
        This function:
        1. Validates BRD document
        2. Extracts and chunks BRD content
        3. Uses AI to convert BRD chunks to FRD functional requirements
        4. Saves generated FRD as a new document
        5. Links BRD and FRD in BRDToFRDVersions table
        6. Generates test cases for the FRD
        
        Args:
            db: Database session
            project_id: Project ID
            brd_document_id: Source BRD document ID
            conversion_instructions: Optional custom instructions for conversion
            
        Returns:
            Dict with FRD document info and test case generation results
        """
        from sqlalchemy import select, desc
        from app.models.models import BRDToFRDVersions
        from pathlib import Path
        import json
        
        # Validate BRD document
        brd_doc = await self._validate_brd_document(db, brd_document_id)
        
        logger.info(
            Fore.BLUE + 
            f"Starting BRD to FRD conversion for document {brd_document_id}" + 
            Style.RESET_ALL
        )
        
        # Get BRD content and chunk it
        content = await self.testgen_service.get_document_content(db, brd_document_id)
        chunks = self.testgen_service.chunker.chunk(content)
        
        logger.debug(
            Fore.CYAN + 
            f"Processing {len(chunks)} BRD chunks for conversion" + 
            Style.RESET_ALL
        )
        
        # Convert each chunk to FRD format
        frd_chunks = []
        for idx, chunk in enumerate(chunks, 1):
            chunk_id = chunk.get("section_id", f"CHUNK_{idx}")
            chunk_text = chunk.get("text", "")
            
            # Prepare conversion prompt
            default_instructions = (
                "Convert this Business Requirement into detailed Functional Requirements. "
                "Include specific system behaviors, inputs, outputs, validations, and error handling. "
                "Be precise and technical."
            )
            
            instructions = conversion_instructions or default_instructions
            
            sys_msg = {
                "role": "system",
                "content": (
                    "You are a Business Analyst converting BRD to FRD. "
                    "Transform high-level business requirements into detailed functional specifications. "
                    "Output strictly valid JSON."
                )
            }
            
            user_msg = {
                "role": "user",
                "content": (
                    f"{instructions}\n\n"
                    f"BRD Section [{chunk_id}]:\n{chunk_text}\n\n"
                    "Output format:\n"
                    '{"section_id": "...", "functional_requirements": ['
                    '{"req_id": "FR-001", "title": "...", "description": "...", '
                    '"acceptance_criteria": ["..."], "dependencies": ["..."]}'
                    ']}'
                )
            }
            
            try:
                # Use context-aware generation for better results
                result = await self.testgen_service.ai.generate_with_chunk_context(
                    current_chunk=chunk,
                    project_id=project_id,
                    document_id=brd_document_id,
                    generation_prompt=user_msg["content"],
                    max_related_chunks=2,
                    response_format_json=True
                )
                
                frd_data = json.loads(result["response"])
                frd_chunks.append({
                    "brd_section_id": chunk_id,
                    "frd_section_id": frd_data.get("section_id", chunk_id),
                    "functional_requirements": frd_data.get("functional_requirements", []),
                    "context_used": result.get("related_chunks_used", 0)
                })
                
                logger.debug(
                    Fore.GREEN + 
                    f"Converted BRD chunk {chunk_id} to FRD" + 
                    Style.RESET_ALL
                )
                
            except Exception as e:
                logger.error(
                    Fore.RED + 
                    f"Failed to convert chunk {chunk_id}: {e}" + 
                    Style.RESET_ALL
                )
                frd_chunks.append({
                    "brd_section_id": chunk_id,
                    "error": str(e)
                })
        
        # Save FRD document
        frd_content = self._format_frd_content(frd_chunks)
        
        # Get next document number for project
        result = await db.execute(
            select(Documents)
            .where(Documents.project_id == project_id)
            .order_by(desc(Documents.doc_number))
            .limit(1)
        )
        last_doc = result.scalar_one_or_none()
        next_doc_number = (last_doc.doc_number if last_doc else 0) + 1
        
        # Create FRD document file
        doc_dir = Path("data") / "documents" / f"project_{project_id}"
        doc_dir.mkdir(parents=True, exist_ok=True)
        
        frd_filename = f"frd_from_brd_{brd_document_id}_v1.txt"
        frd_file_path = doc_dir / frd_filename
        frd_file_path.write_text(frd_content, encoding="utf-8")
        
        # Create FRD document record
        frd_document = Documents(
            project_id=project_id,
            doctype=DocType.FRD,
            file_path=str(frd_file_path),
            doc_number=next_doc_number,
            version=1,
            changes={
                "source": "generated",
                "generated_from_brd": brd_document_id,
                "total_chunks_converted": len(frd_chunks),
                "conversion_instructions": conversion_instructions
            }
        )
        
        db.add(frd_document)
        await db.flush()  # Get the ID
        
        # Create BRD-to-FRD version link
        brd_frd_link = BRDToFRDVersions(
            brd_id=brd_document_id,
            frd_id=frd_document.id,
            changes={
                "frd_chunks": frd_chunks,
                "conversion_metadata": {
                    "total_chunks": len(chunks),
                    "successful_conversions": len([c for c in frd_chunks if "error" not in c]),
                    "context_aware": True
                }
            }
        )
        
        db.add(brd_frd_link)
        await db.commit()
        await db.refresh(frd_document)
        
        logger.info(
            Fore.GREEN + 
            f"Created FRD document {frd_document.id} from BRD {brd_document_id}" + 
            Style.RESET_ALL
        )
        
        return {
            "status": "success",
            "brd_document_id": brd_document_id,
            "frd_document": {
                "id": frd_document.id,
                "doc_number": frd_document.doc_number,
                "file_path": str(frd_file_path),
                "version": frd_document.version
            },
            "conversion_results": {
                "total_chunks_processed": len(chunks),
                "successful_conversions": len([c for c in frd_chunks if "error" not in c]),
                "failed_conversions": len([c for c in frd_chunks if "error" in c]),
                "frd_chunks": frd_chunks
            },
            "message": "FRD document created successfully. You can now generate test cases for it."
        }
    
    def _format_frd_content(self, frd_chunks: list) -> str:
        """Format FRD chunks into readable document content"""
        lines = ["FUNCTIONAL REQUIREMENTS DOCUMENT (FRD)", "=" * 50, ""]
        
        for chunk in frd_chunks:
            if "error" in chunk:
                continue
            
            lines.append(f"\n## Section: {chunk.get('frd_section_id', 'Unknown')}")
            lines.append(f"(Derived from BRD Section: {chunk.get('brd_section_id', 'Unknown')})")
            lines.append("")
            
            for req in chunk.get("functional_requirements", []):
                lines.append(f"\n### {req.get('req_id', 'FR-XXX')}: {req.get('title', 'Untitled')}")
                lines.append("")
                lines.append(f"**Description:** {req.get('description', 'N/A')}")
                lines.append("")
                
                criteria = req.get("acceptance_criteria", [])
                if criteria:
                    lines.append("**Acceptance Criteria:**")
                    for criterion in criteria:
                        lines.append(f"- {criterion}")
                    lines.append("")
                
                deps = req.get("dependencies", [])
                if deps:
                    lines.append(f"**Dependencies:** {', '.join(deps)}")
                    lines.append("")
        
        return "\n".join(lines)
    
    async def get_testcases(
        self, 
        db: AsyncSession, 
        testcase_id: int
    ) -> Dict:
        """Get BRD test cases by ID"""
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
        """Revert BRD test cases to a previous version"""
        await self._validate_brd_document(db, document_id)
        
        logger.info(
            Fore.YELLOW + 
            f"Reverting BRD document {document_id} to version {to_version}" + 
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
        """Get all test case versions for a BRD document"""
        from sqlalchemy import select
        from app.models.models import Testcases
        
        await self._validate_brd_document(db, document_id)
        
        result = await db.execute(
            select(Testcases)
            .where(Testcases.document_id == document_id)
            .order_by(Testcases.version.desc())
        )
        versions = result.scalars().all()
        
        return {
            "document_id": document_id,
            "document_type": "BRD",
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
    
    async def get_brd_frd_mappings(
        self,
        db: AsyncSession,
        brd_document_id: int
    ) -> Dict:
        """Get all FRD documents generated from this BRD"""
        from sqlalchemy import select
        from app.models.models import BRDToFRDVersions, Documents
        
        await self._validate_brd_document(db, brd_document_id)
        
        result = await db.execute(
            select(BRDToFRDVersions)
            .where(BRDToFRDVersions.brd_id == brd_document_id)
            .order_by(BRDToFRDVersions.created_at.desc())
        )
        mappings = result.scalars().all()
        
        frd_list = []
        for mapping in mappings:
            if mapping.frd_id:
                frd_doc = await db.get(Documents, mapping.frd_id)
                if frd_doc:
                    frd_list.append({
                        "frd_id": frd_doc.id,
                        "frd_doc_number": frd_doc.doc_number,
                        "version": frd_doc.version,
                        "created_at": mapping.created_at.isoformat() if mapping.created_at else None,
                        "file_path": frd_doc.file_path,
                        "conversion_metadata": mapping.changes.get("conversion_metadata", {})
                    })
        
        return {
            "brd_document_id": brd_document_id,
            "total_frd_generated": len(frd_list),
            "frd_documents": frd_list
        }
    
    async def get_context_statistics(
        self,
        db: AsyncSession,
        document_id: int
    ) -> Dict:
        """Get context usage statistics for BRD document test cases"""
        from sqlalchemy import select
        from app.models.models import Testcases
        from pathlib import Path
        import json
        
        await self._validate_brd_document(db, document_id)
        
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
                detail=f"No test cases found for BRD document {document_id}"
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
            "document_type": "BRD",
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