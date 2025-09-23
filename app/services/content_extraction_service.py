import json
from typing import List
from fastapi import HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pathlib import Path
import fitz  # PyMuPDF
import io
import docx

# from app.models.models import Documents
from app.models.models import Documents
from database.database_connection import get_db
from config.config import MODEL_NAME

try:
    import tiktoken
    _HAVE_TIKTOKEN = True
except Exception:
    _HAVE_TIKTOKEN = False

model_name = MODEL_NAME
class ContentExtractionService:
    def __init__(self, model_name = MODEL_NAME):
        self.model_name = model_name

    async def extract_document_text(
    self, db: AsyncSession, project_id: int, document_id: int
):
        """Fetch document by project_id + document_id and extract text"""

        # 1. Find the document inside project
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

        # 2. Load file from disk
        path = Path(doc.file_path)
        if not path.exists():
            raise HTTPException(status_code=404, detail="File not found on disk")

        content = path.read_bytes()
        extension = path.suffix.lower()

        # 3. Extract text
        text = await self.extract_text_content(content, extension)
        return {
            "document_id": document_id,
            "project_id": project_id,
            # handle enum vs string safely
            "doctype": doc.doctype.value if hasattr(doc.doctype, "value") else doc.doctype,
            "text_length": len(text),
            "preview": text[:500]  # first 500 chars
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
        try:
            doc = docx.Document(io.BytesIO(content))
            text = "\n".join(p.text for p in doc.paragraphs if p.text)
            return text.strip()
        except Exception as e:
            raise Exception(f"DOCX text extraction failed: {str(e)}")

    def _extract_text_from_txt(self, content: bytes) -> str:
        try:
            return content.decode("utf-8").strip()
        except UnicodeDecodeError:
            return content.decode("latin-1").strip()
    def _extract_text_from_json(self, content: bytes) -> str:
        """Extracts readable text from a JSON file"""
        try:
            data = json.loads(content.decode("utf-8"))
            # Flatten JSON into readable string
            text = self._flatten_json_to_text(data)
            return text.strip()
        except Exception as e:
            raise Exception(f"JSON text extraction failed: {str(e)}")

    def _flatten_json_to_text(self, obj, prefix="") -> str:
        """Recursively flatten JSON to text"""
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
    
    # def _split_into_chunks(self, text: str, max_tokens: int) -> list[str]:
    #     words = text.split()
    #     chunks, current = [], []
    #     count = 0
    #     for w in words:
    #         current.append(w)
    #         count += 1
    #         if count >= max_tokens:
    #             chunks.append(" ".join(current))
    #             current, count = [], 0
    #     if current:
    #         chunks.append(" ".join(current))
    #     return chunks

#     def _split_into_token_chunks(
#     self, text: str, max_tokens: int = 2000, overlap_tokens: int = 200, model_name: str = None
# ) -> List[str]:
#         """
#         Efficient token-based chunking. Precomputes token counts per word to avoid O(n^2).
#         Returns list of chunks (strings).
#         """
#         model_name = model_name or self.model_name
#         words = text.split()
#         if not words:
#             return []

#         # Precompute token counts for each word (fallback estimate when tiktoken not available)
#         token_counts = []
#         if _HAVE_TIKTOKEN:
#             for w in words:
#                 token_counts.append(self.count_tokens(w, model_name))
#         else:
#             # conservative estimate: 1 token per 4 chars (adjust if you prefer)
#             for w in words:
#                 token_counts.append(max(1, len(w) // 4))

#         # average tokens per word for calculating overlap as words
#         avg_tpw = max(1, sum(token_counts) // len(token_counts))

#         chunks: List[str] = []
#         current_words: List[str] = []
#         current_tokens = 0
#         i = 0
#         n = len(words)

#         while i < n:
#             t = token_counts[i]
#             # if it fits, append
#             if current_tokens + t <= max_tokens:
#                 current_words.append(words[i])
#                 current_tokens += t
#                 i += 1
#                 continue

#             # push current chunk
#             if current_words:
#                 chunks.append(" ".join(current_words))

#             # compute overlap in words
#             overlap_words_count = max(1, overlap_tokens // avg_tpw)
#             if overlap_words_count > len(current_words):
#                 overlap_words_count = len(current_words)

#             # prepare next chunk starting with overlap + current word
#             overlap_words = current_words[-overlap_words_count:] if overlap_words_count > 0 else []
#             current_words = overlap_words[:]  # shallow copy
#             current_tokens = sum(
#                 token_counts[i - len(current_words) + j]  # approximate, safe - small edgecases ok
#                 for j in range(len(current_words))
#             ) if current_words else 0

#             # do not advance i here so loop will attempt to add words[i] again
#         # append remaining
#         if current_words:
#             chunks.append(" ".join(current_words))
#         return chunks

    
    # --- token helpers ---
    def count_tokens(self, text: str, model_name: str = None):
        try:
            if model_name:
                enc = tiktoken.encoding_for_model(model_name)
            else:
                enc = tiktoken.get_encoding("cl100k_base")
        except KeyError:
            # Fallback for non-OpenAI models
            enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))

    def truncate_to_tokens(self, text: str, max_tokens: int, model_name: str = None) -> str:
        model_name = model_name or self.model_name
        if self.count_tokens(text, model_name) <= max_tokens:
            return text
        words = text.split()
        out_words = []
        count = 0
        for w in words:
            t = self.count_tokens(w, model_name)
            if count + t > max_tokens:
                break
            out_words.append(w)
            count += t
        return " ".join(out_words)

    def _split_into_token_chunks(
    self, text: str, max_tokens: int = 2000, overlap_tokens: int = 200, model_name: str = None
) -> List[str]:
        """
        Efficient token-based chunking with optional overlap.
        Returns list of text chunks.
        """
        model_name = model_name or self.model_name
        words = text.split()
        chunks: List[str] = []
        current: List[str] = []
        current_tokens = 0

        for w in words:
            t = self.count_tokens(w, model_name)
            if current_tokens + t > max_tokens:
                # push chunk
                chunks.append(" ".join(current))
                # form overlap
                if overlap_tokens and len(current) > 0:
                    approx_words_for_overlap = max(1, int(overlap_tokens / 1.3))
                    overlap_words = current[-approx_words_for_overlap:]
                else:
                    overlap_words = []
                current = overlap_words + [w]
                current_tokens = sum(self.count_tokens(x, model_name) for x in current)
            else:
                current.append(w)
                current_tokens += t

        if current:
            chunks.append(" ".join(current))
        return chunks

    ####Test text extraction and chunking
    async def test_text_extraction_and_chunking(
    self,
    db: AsyncSession,
    project_id: int,
    document_id: int,
    max_tokens: int = 2000,
):
        """
        Utility function to test extraction + chunking of a document.
        Prints chunks to console for debugging.
        """

        # 1. Extract text
        result = await self.extract_document_text(db, project_id, document_id)
        print(f"\n[INFO] Extracted {result['text_length']} characters from document {document_id}")
        print(f"[INFO] Preview text (first 100 chars): {result['preview'][:100]}")

        # 2. Actually get full text again
        doc = await db.get(Documents, document_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        content = Path(doc.file_path).read_bytes()
        extension = Path(doc.file_path).suffix.lower()
        full_text = await self.extract_text_content(content, extension)

        # 3. Split into chunks (fixed: use token-based chunking)
        chunks = self._split_into_token_chunks(full_text, max_tokens=max_tokens)

        # 4. Print chunks for testing
        print(f"[INFO] Total chunks created: {len(chunks)}")
        for i, chunk in enumerate(chunks, start=1):
            print(f"\n---- Chunk {i} ----\n")
            print(chunk[:500])  # only print first 500 chars for readability

        return chunks



# if __name__=="__main__":
#     db : AsyncSession = Depends(get_db)
#     extract_obj = ContentExtractionService()
#     extract_obj.test_text_extraction_and_chunking(db, 1)
