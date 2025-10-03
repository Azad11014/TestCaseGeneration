"""
content_extraction_service.py
Service for extracting text from various document formats and chunking
"""

import json
import io
from typing import Dict
from pathlib import Path
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import fitz  # PyMuPDF
import docx

from app.models.models import Documents
from config.config import MODEL_NAME
from logs.logger_config import get_logger
from colorama import Fore, Style
from app.services.text_chunking_service import SmartChunker

logger = get_logger("TextExtractionService")


class ContentExtractionService:
    """Extract and chunk text from various document formats"""
    
    def __init__(self, model_name=MODEL_NAME, min_words=40, max_words=900):
        self.model_name = model_name
        self.chunker = SmartChunker(min_words=min_words, max_words=max_words)
    
    async def extract_and_chunk_document(
        self, db: AsyncSession, project_id: int, document_id: int
    ) -> Dict:
        """Extract text from document and return chunked results"""
        
        # 1. Fetch document
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
        
        # 2. Load and extract text
        path = Path(doc.file_path)
        if not path.exists():
            raise HTTPException(status_code=404, detail="File not found on disk")
        
        content = path.read_bytes()
        extension = path.suffix.lower()
        text = await self.extract_text_content(content, extension)
        
        logger.debug(Fore.GREEN + "Extracted text successfully..." + Style.RESET_ALL)
        
        # 3. Chunk the text
        chunks = self.chunker.chunk(text)
        logger.debug(Fore.CYAN + f"Created {len(chunks)} chunks" + Style.RESET_ALL)
        
        return {
            "document_id": document_id,
            "project_id": project_id,
            "doctype": doc.doctype.value if hasattr(doc.doctype, "value") else doc.doctype,
            "total_text_length": len(text),
            "total_chunks": len(chunks),
            "chunks": chunks,
            "preview": f"First 500 chars...\n{text[:500]}..."
        }
    
    async def extract_document_text(
        self, db: AsyncSession, project_id: int, document_id: int
    ) -> Dict:
        """Fetch document and extract text only (without chunking)"""
        
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
        
        path = Path(doc.file_path)
        if not path.exists():
            raise HTTPException(status_code=404, detail="File not found on disk")
        
        content = path.read_bytes()
        extension = path.suffix.lower()
        text = await self.extract_text_content(content, extension)
        
        logger.debug(Fore.GREEN + "Extracted text successfully..." + Style.RESET_ALL)
        
        return {
            "document_id": document_id,
            "project_id": project_id,
            "doctype": doc.doctype.value if hasattr(doc.doctype, "value") else doc.doctype,
            "text_length": len(text),
            "preview": f"First 500 words...\n{text[:500]}..."
        }
    
    async def extract_text_content(self, content: bytes, extension: str) -> str:
        """Detect file type and extract text accordingly"""
        try:
            if extension == ".pdf":
                return self._extract_text_from_pdf(content)
            elif extension in [".docx", ".doc"]:
                return self._extract_text_from_docx(content)
            elif extension == ".txt":
                return self._extract_text_from_txt(content)
            elif extension == ".json":
                return self._extract_text_from_json(content)
            else:
                raise Exception(f"Unsupported file extension: {extension}")
        except Exception as e:
            raise Exception(f"Text extraction failed: {str(e)}")
    
    def _extract_text_from_pdf(self, content: bytes) -> str:
        """Extract text from PDF file"""
        try:
            text = ""
            with fitz.open(stream=content, filetype="pdf") as doc:
                for page in doc:
                    page_text = page.get_text()
                    if page_text:
                        text += page_text + "\n"
            return text.strip()
        except Exception as e:
            raise Exception(f"PDF text extraction failed: {str(e)}")
    
    def _extract_text_from_docx(self, content: bytes) -> str:
        """Extract text from DOCX file"""
        try:
            doc = docx.Document(io.BytesIO(content))
            text = "\n".join(p.text for p in doc.paragraphs if p.text)
            return text.strip()
        except Exception as e:
            raise Exception(f"DOCX text extraction failed: {str(e)}")
    
    def _extract_text_from_txt(self, content: bytes) -> str:
        """Extract text from TXT file"""
        try:
            return content.decode("utf-8").strip()
        except UnicodeDecodeError:
            return content.decode("latin-1").strip()
    
    def _extract_text_from_json(self, content: bytes) -> str:
        """Extract readable text from JSON file"""
        try:
            data = json.loads(content.decode("utf-8"))
            text = self._flatten_json_to_text(data)
            return text.strip()
        except Exception as e:
            raise Exception(f"JSON text extraction failed: {str(e)}")
    
    def _flatten_json_to_text(self, obj, prefix="") -> str:
        """Recursively flatten JSON to readable text"""
        lines = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                lines.append(f"{prefix}{k}: {self._flatten_json_to_text(v, prefix='')}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                lines.append(self._flatten_json_to_text(v, prefix=prefix))
        else:
            lines.append(str(obj))
        return "\n".join(filter(None, lines))