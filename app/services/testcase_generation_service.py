"""
enhanced_testcase_generation_service.py
Context-aware test case generation with vector store integration
"""

import datetime
import json
from pathlib import Path
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Dict, Any, AsyncGenerator
from sqlalchemy import select

from app.schema.schema import TestCaseUpdateRequest
from app.services.ai_client_services import AiClientService
from app.services.text_extraction_service import ContentExtractionService
from app.services.vector_store_service import VectorStoreService
from app.services.text_chunking_service import SmartChunker

from app.models.models import Documents, Testcases, TestCaseStatus

from logs.logger_config import get_logger
from colorama import Fore, Style

logger = get_logger("EnhancedTestGenService")

DATA_DIR = Path("data")
TC_DIR = DATA_DIR / "testcases"
TC_DIR.mkdir(exist_ok=True, parents=True)


class EnhancedTestGenService:
    """
    Test case generation service with vector store integration
    Maintains context awareness across chunks and during chat updates
    """
    
    def __init__(self):
        self.ai = AiClientService()
        self.vector_service = VectorStoreService()
        self.chunker = SmartChunker(min_words=40, max_words=800)
        self.content_extractor = ContentExtractionService()
        
        logger.info(
            Fore.GREEN + 
            "Enhanced Testcase Generation Service initialized with vector support..." + 
            Style.RESET_ALL
        )
    
    async def get_document_content(
        self, 
        db: AsyncSession, 
        document_id: int
    ) -> str:
        """Get document content from file"""
        try:
            doc = await db.get(Documents, document_id)
            if not doc:
                raise HTTPException(status_code=404, detail="Document not found")
            
            file_path = Path(doc.file_path)
            if not file_path.exists():
                raise HTTPException(status_code=404, detail="Document file not found")
            
            content_bytes = file_path.read_bytes()
            text = await self.content_extractor.extract_text_content(
                content_bytes, 
                file_path.suffix.lower()
            )
            
            return text
                
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Error reading document content: {e}"
            )
    
    async def analyze_chunk_issues(
        self, 
        chunk: Dict[str, str],
        project_id: int,
        document_id: int
    ) -> Dict[str, Any]:
        """
        Analyze a chunk for issues with context from related chunks
        """
        chunk_id = chunk.get("section_id", "unknown")
        chunk_text = chunk.get("text", "")
        
        try:
            prompt = (
                "Analyze this requirement chunk and identify any issues. "
                "Consider the related sections provided for context. "
                "Look for: ambiguous statements, missing details, contradictions, "
                "unclear acceptance criteria. "
                "Output JSON in this format:\n"
                '{"issues": [{"id": "ISS-001", "type": "ambiguity|missing|contradiction", '
                '"severity": "high|medium|low", "description": "...", "location": "..."}]}'
            )
            
            result = await self.ai.generate_with_chunk_context(
                current_chunk=chunk,
                project_id=project_id,
                document_id=document_id,
                generation_prompt=prompt,
                max_related_chunks=2,
                response_format_json=True
            )
            
            parsed = json.loads(result["response"])
            issues = parsed.get("issues", [])
            
            # Add chunk_id and context info to each issue
            for issue in issues:
                issue["chunk_id"] = chunk_id
                issue["related_chunks_consulted"] = result.get("related_chunks_used", 0)
            
            logger.debug(
                Fore.CYAN + 
                f"Found {len(issues)} issues in chunk {chunk_id} " +
                f"(consulted {result.get('related_chunks_used', 0)} related chunks)" +
                Style.RESET_ALL
            )
            
            return {
                "chunk_id": chunk_id,
                "has_issues": len(issues) > 0,
                "issue_count": len(issues),
                "issues": issues,
                "context_aware": True,
                "related_chunks_used": result.get("related_chunks_used", 0)
            }
            
        except Exception as e:
            logger.error(
                Fore.RED + 
                f"Issue analysis failed for {chunk_id}: {e}" + 
                Style.RESET_ALL
            )
            return {
                "chunk_id": chunk_id,
                "has_issues": False,
                "issue_count": 0,
                "issues": [],
                "error": str(e),
                "context_aware": False
            }
    
    async def generate_testcases_for_chunk(
        self, 
        chunk: Dict[str, str],
        project_id: int,
        document_id: int,
        issues: List[Dict]
    ) -> List[Dict]:
        """
        Generate test cases for a chunk with context awareness
        """
        chunk_id = chunk.get("section_id", "unknown")
        chunk_text = chunk.get("text", "")
        
        try:
            # Prepare issues context
            issues_context = ""
            if issues:
                issues_context = (
                    "\n\nIDENTIFIED ISSUES TO ADDRESS:\n" + 
                    json.dumps(issues, indent=2)
                )
            
            prompt = (
                "Generate comprehensive test cases for this requirement chunk. "
                "Consider related sections for consistency and coverage. "
                f"{issues_context}\n\n"
                "Output JSON in this format:\n"
                '{"testcases": [{"id": "TC-001", "chunk_id": "...", "title": "...", '
                '"preconditions": ["..."], "steps": ["..."], "expected": "...", '
                '"priority": "P0|P1|P2", "addresses_issue": "ISS-001 or null", '
                '"related_chunks": ["section_id1", "section_id2"]}]}'
            )
            
            result = await self.ai.generate_with_chunk_context(
                current_chunk=chunk,
                project_id=project_id,
                document_id=document_id,
                generation_prompt=prompt,
                max_related_chunks=2,
                response_format_json=True
            )
            
            parsed = json.loads(result["response"])
            testcases = parsed.get("testcases", [])
            
            # Enrich test cases with context metadata
            for tc in testcases:
                tc["chunk_id"] = chunk_id
                tc["generated_with_context"] = True
                tc["related_chunks_consulted"] = result.get("related_chunks_used", 0)
                
                # Add references to related chunks used
                if "related_chunks" not in tc and result.get("related_sources"):
                    tc["related_chunks"] = [
                        src["section_id"] 
                        for src in result.get("related_sources", [])
                    ]
            
            logger.debug(
                Fore.GREEN + 
                f"Generated {len(testcases)} test cases for chunk {chunk_id} " +
                f"(consulted {result.get('related_chunks_used', 0)} related chunks)" +
                Style.RESET_ALL
            )
            
            return testcases
            
        except Exception as e:
            logger.error(
                Fore.RED + 
                f"Testcase generation failed for {chunk_id}: {e}" + 
                Style.RESET_ALL
            )
            return []
    
    async def generate_testcases_stream(
        self,
        db: AsyncSession,
        project_id: int,
        document_id: int
    ) -> AsyncGenerator[str, None]:
        """
        Stream test case generation with vector-aware context
        """
        try:
            # Get document
            doc = await db.get(Documents, document_id)
            if not doc:
                raise HTTPException(status_code=404, detail="Document not found")
            
            # Get content and chunk
            content = await self.get_document_content(db, document_id)
            chunks = self.chunker.chunk(content)
            total_chunks = len(chunks)
            
            logger.info(
                Fore.CYAN + 
                f"Processing {total_chunks} chunks with context awareness..." + 
                Style.RESET_ALL
            )
            
            # STEP 1: Ingest document to vector store
            yield f"data: {json.dumps({'type': 'vector_ingest_start', 'document_id': document_id})}\n\n"
            
            try:
                await self.vector_service.ingest_document_chunks(
                    document_id=document_id,
                    project_id=project_id,
                    chunks=chunks,
                    doctype=doc.doctype.value if hasattr(doc.doctype, "value") else doc.doctype
                )
                yield f"data: {json.dumps({'type': 'vector_ingest_complete', 'chunks_indexed': total_chunks})}\n\n"
            except Exception as e:
                logger.warning(
                    Fore.YELLOW + 
                    f"Vector ingestion failed, continuing without context: {e}" + 
                    Style.RESET_ALL
                )
                yield f"data: {json.dumps({'type': 'vector_ingest_failed', 'message': str(e)})}\n\n"
            
            # Aggregators
            all_issues = []
            all_testcases = []
            
            # Start event
            yield f"data: {json.dumps({'type': 'start', 'document_id': document_id, 'total_chunks': total_chunks, 'context_aware': True})}\n\n"
            
            # Process each chunk with context
            for idx, chunk in enumerate(chunks, start=1):
                chunk_id = chunk.get("section_id", f"CHUNK_{idx}")
                
                yield f"data: {json.dumps({'type': 'chunk_start', 'chunk': idx, 'chunk_id': chunk_id, 'total': total_chunks})}\n\n"
                
                # Step 1: Analyze issues (with context)
                yield f"data: {json.dumps({'type': 'analysis_start', 'chunk': idx, 'chunk_id': chunk_id})}\n\n"
                
                issue_result = await self.analyze_chunk_issues(
                    chunk=chunk,
                    project_id=project_id,
                    document_id=document_id
                )
                all_issues.extend(issue_result.get("issues", []))
                
                yield f"data: {json.dumps({'type': 'issues_found', 'chunk': idx, 'chunk_id': chunk_id, 'issues': issue_result})}\n\n"
                
                # Step 2: Generate test cases (with context)
                yield f"data: {json.dumps({'type': 'generation_start', 'chunk': idx, 'chunk_id': chunk_id})}\n\n"
                
                testcases = await self.generate_testcases_for_chunk(
                    chunk=chunk,
                    project_id=project_id,
                    document_id=document_id,
                    issues=issue_result.get("issues", [])
                )
                all_testcases.extend(testcases)
                
                yield f"data: {json.dumps({'type': 'testcases_generated', 'chunk': idx, 'chunk_id': chunk_id, 'count': len(testcases)})}\n\n"
                yield f"data: {json.dumps({'type': 'chunk_complete', 'chunk': idx, 'chunk_id': chunk_id, 'testcases_count': len(testcases), 'issues_count': len(issue_result.get('issues', []))})}\n\n"
            
            # Save aggregated results
            logger.info(Fore.GREEN + "Saving aggregated test cases..." + Style.RESET_ALL)
            
            testcase_id = await self.write_and_record(
                db, 
                document_id, 
                all_testcases, 
                status=TestCaseStatus.generated,
                metadata={
                    "total_chunks": total_chunks,
                    "total_issues": len(all_issues),
                    "context_aware": True,
                    "vector_store_used": True,
                    "issues_by_chunk": self._group_issues_by_chunk(all_issues)
                }
            )
            
            # Final complete event
            final_data = {
                'type': 'complete',
                'document_id': document_id,
                'testcase_id': testcase_id,
                'total_chunks': total_chunks,
                'total_testcases': len(all_testcases),
                'total_issues': len(all_issues),
                'context_aware': True,
                'summary': {
                    'high_severity_issues': len([i for i in all_issues if i.get('severity') == 'high']),
                    'medium_severity_issues': len([i for i in all_issues if i.get('severity') == 'medium']),
                    'low_severity_issues': len([i for i in all_issues if i.get('severity') == 'low']),
                    'context_enhanced_testcases': len([tc for tc in all_testcases if tc.get('generated_with_context')])
                }
            }
            yield f"data: {json.dumps(final_data)}\n\n"
            yield "data: [DONE]\n\n"
        
        except HTTPException:
            raise
        except Exception as e:
            logger.error(Fore.RED + f"Stream generation failed: {e}" + Style.RESET_ALL)
            error_data = {'type': 'error', 'message': str(e)}
            yield f"data: {json.dumps(error_data)}\n\n"
    
    def _group_issues_by_chunk(self, issues: List[Dict]) -> Dict[str, List[Dict]]:
        """Group issues by chunk_id"""
        grouped = {}
        for issue in issues:
            chunk_id = issue.get("chunk_id", "unknown")
            if chunk_id not in grouped:
                grouped[chunk_id] = []
            grouped[chunk_id].append(issue)
        return grouped
    
    async def write_and_record(
        self,
        db: AsyncSession,
        document_id: int,
        testcases: List[dict],
        status: TestCaseStatus,
        version: int | None = None,
        metadata: Dict | None = None
    ) -> int:
        """Save testcases to file and create DB record"""
        try:
            tc_dir = TC_DIR / f"doc_{document_id}"
            tc_dir.mkdir(parents=True, exist_ok=True)
            
            # Get next number and version
            last_tc = await db.execute(
                select(Testcases)
                .where(Testcases.document_id == document_id)
                .order_by(Testcases.testcase_number.desc())
                .limit(1)
            )
            last_row = last_tc.scalar_one_or_none()
            next_number = (last_row.testcase_number if last_row else 0) + 1
            
            if version is None:
                version = (last_row.version if last_row else 0) + 1
            
            # Save to file
            timestamp = int(datetime.datetime.utcnow().timestamp())
            file_path = tc_dir / f"testcases_v{version}_{timestamp}.json"
            
            file_data = {
                "testcases": testcases,
                "metadata": metadata or {}
            }
            
            file_path.write_text(
                json.dumps(file_data, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            
            # Create DB record
            new_testcase = Testcases(
                document_id=document_id,
                testcase_number=next_number,
                version=version,
                file_path=str(file_path),
                status=status.value,
                changes=metadata,
                created_at=datetime.datetime.utcnow()
            )
            
            db.add(new_testcase)
            await db.commit()
            await db.refresh(new_testcase)
            
            logger.info(
                Fore.GREEN + 
                f"Testcase #{next_number} v{version} saved (ID: {new_testcase.id})..." + 
                Style.RESET_ALL
            )
            return new_testcase.id
        
        except Exception as e:
            await db.rollback()
            logger.error(Fore.RED + f"Error saving testcases: {e}" + Style.RESET_ALL)
            raise HTTPException(status_code=500, detail=f"Failed to save testcases: {e}")
    
    async def get_testcases_with_issues(
        self, 
        db: AsyncSession, 
        testcase_id: int
    ) -> Dict:
        """Get testcases along with their associated issues"""
        try:
            testcase = await db.get(Testcases, testcase_id)
            if not testcase:
                raise HTTPException(status_code=404, detail="Testcase not found")
            
            file_path = Path(testcase.file_path)
            if not file_path.exists():
                raise HTTPException(status_code=404, detail="Testcase file not found")
            
            data = json.loads(file_path.read_text(encoding="utf-8"))
            
            return {
                "testcase_id": testcase_id,
                "document_id": testcase.document_id,
                "version": testcase.version,
                "status": testcase.status,
                "testcases": data.get("testcases", []),
                "metadata": data.get("metadata", {}),
                "created_at": testcase.created_at.isoformat() if testcase.created_at else None
            }
        
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error reading testcases: {e}")
    
    async def chat_update(
        self,
        db: AsyncSession,
        project_id: int,
        document_id: int,
        request: TestCaseUpdateRequest,
        commit: bool = False
    ):
        """
        Update testcases based on chat request with context awareness
        Uses vector store to retrieve relevant context
        """
        logger.info(Fore.GREEN + "Processing context-aware chat update..." + Style.RESET_ALL)
        
        try:
            # Get latest testcase
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
                    detail="No testcases found. Generate testcases first."
                )
            
            # Load current testcases
            current_data = await self.get_testcases_with_issues(db, latest.id)
            current = current_data.get("testcases", [])
            
            # Use context-aware chat for update
            system_msg = {
                "role": "system",
                "content": (
                    "You are a QA assistant. Update testcases based on user request. "
                    "Use the provided document context to ensure consistency. "
                    "Preserve existing testcases and only modify what's requested. "
                    "Output strictly valid JSON."
                )
            }
            
            user_msg = {
                "role": "user",
                "content": (
                    f"User request: {request.message}\n\n"
                    f"Current testcases:\n{json.dumps(current, indent=2)}\n\n"
                    "Update the testcases according to the request. "
                    "Output format: "
                    '{"testcases": [...updated testcases...], "changes_made": "description"}'
                )
            }
            
            # Call AI with context retrieval
            logger.debug(
                Fore.CYAN + 
                "Retrieving relevant context for chat update..." + 
                Style.RESET_ALL
            )
            
            result = await self.ai.chat_with_context(
                messages=[system_msg, user_msg],
                project_id=project_id,
                document_id=document_id,
                max_context_chunks=3,
                response_format_json=True
            )
            
            response = result["response"]
            sources = result["sources"]
            
            logger.info(
                Fore.GREEN + 
                f"Chat update used {result['context_chunks_used']} context chunks" + 
                Style.RESET_ALL
            )
            
            try:
                updated = json.loads(response)
                updated_tcs = updated.get("testcases", [])
                changes_made = updated.get("changes_made", "Updates applied")
                
                logger.info(Fore.GREEN + "Updated testcases received..." + Style.RESET_ALL)
            except Exception:
                raise HTTPException(status_code=500, detail="AI returned invalid JSON")
            
            if not commit:
                return {
                    "preview": updated_tcs,
                    "count": len(updated_tcs),
                    "current_version": latest.version,
                    "changes_description": changes_made,
                    "context_used": {
                        "chunks_consulted": result['context_chunks_used'],
                        "sources": sources
                    }
                }
            
            # Save as new version with context metadata
            metadata = {
                "chat_update": True,
                "user_request": request.message,
                "changes_made": changes_made,
                "context_chunks_used": result['context_chunks_used'],
                "context_sources": sources
            }
            
            new_id = await self.write_and_record(
                db, 
                document_id, 
                updated_tcs, 
                status=TestCaseStatus.revised,
                metadata=metadata
            )
            
            return {
                "testcase_id": new_id,
                "previous_version": latest.version,
                "testcases": updated_tcs,
                "count": len(updated_tcs),
                "changes_description": changes_made,
                "context_aware": True,
                "context_used": {
                    "chunks_consulted": result['context_chunks_used'],
                    "sources": sources
                }
            }
        
        except HTTPException:
            raise
        except Exception as e:
            logger.error(Fore.RED + f"Chat update failed: {e}" + Style.RESET_ALL)
            raise HTTPException(status_code=500, detail=f"Chat update failed: {e}")
    
    async def revert(
        self, 
        db: AsyncSession, 
        document_id: int, 
        to_version: int
    ):
        """Revert to a specific testcase version"""
        try:
            result = await db.execute(
                select(Testcases)
                .where(
                    Testcases.document_id == document_id,
                    Testcases.version == to_version
                )
            )
            target = result.scalar_one_or_none()
            
            if not target:
                raise HTTPException(
                    status_code=404,
                    detail=f"Version {to_version} not found"
                )
            
            # Load testcases from target version
            content = await self.get_testcases_with_issues(db, target.id)
            testcases = content.get("testcases", [])
            
            # Create new version with reverted content
            new_id = await self.write_and_record(
                db, 
                document_id, 
                testcases, 
                status=TestCaseStatus.revised,
                metadata={
                    "reverted": True,
                    "reverted_from_version": to_version
                }
            )
            
            new_tc = await db.get(Testcases, new_id)
            
            return {
                "testcase_id": new_id,
                "reverted_from_version": to_version,
                "new_version": new_tc.version,
                "count": len(testcases),
                "status": "reverted"
            }
        
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Revert failed: {e}")