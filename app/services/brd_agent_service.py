import datetime
import json
from pathlib import Path
from typing import Any, Dict, List
from fastapi import FastAPI, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import logging


from app.services.ai_client_services import AiClientService
from app.services.content_extraction_service import ContentExtractionService
from app.services.frd_agent_service import FRDAgentService
from app.services.testcase_gen_service import TestGenServies

from app.schema.schema import DocumentRead, TestCaseUpdateRequest, UpdateBRDToFRD
from app.models.models import BRDToFRDVersions, DocType, Documents, FRDVersions, Source, TestCaseStatus
from database.database_connection import get_db

# Setup logger once (top of file)
logger = logging.getLogger("frd_fixes")
logger.setLevel(logging.INFO)
fh = logging.FileHandler("frd_fixes.log", encoding="utf-8")
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
fh.setFormatter(formatter)
logger.addHandler(fh)

ai = AiClientService()
frd_agent = FRDAgentService()
extractor = ContentExtractionService()
tc_agent = TestGenServies()

DATA_DIR = Path("data")
FRD_OUT_DIR = DATA_DIR / "converted_frd"
CONVERTED_FRD_DIR = DATA_DIR / "cfrd"
FRD_OUT_DIR.mkdir(exist_ok=True, parents=True)
CONVERTED_FRD_DIR.mkdir(exist_ok=True, parents=True)

class BRDAgentService:
    def __init__(self):
        self.ai = ai
        self.frd_agent = frd_agent
        self.extractor = extractor
        self.tc_agent = tc_agent
        
    async def brd_to_frd(self, db: AsyncSession, document_id: int):
        """
        Convert a stored BRD document into an FRD JSON,
        create FRD document row, initial FRD version, save file,
        create BRD->FRD mapping, return metadata.
        """
        try:
            # ----------------------
            # Fetch BRD document
            # ----------------------
            brd_doc = await db.get(Documents, document_id)
            if not brd_doc or brd_doc.doctype != DocType.BRD:
                raise HTTPException(status_code=404, detail="BRD not found")

            path = Path(brd_doc.file_path)
            if not path.exists():
                raise HTTPException(status_code=404, detail="BRD file not found")

            # ----------------------
            # Extract BRD content
            # ----------------------
            content = path.read_bytes()
            text = await self.extractor.extract_text_content(content, path.suffix.lower())

            # ----------------------
            # Convert BRD -> FRD using AI
            # ----------------------
            system_prompt = {
                "role": "system",
                "content": (
                    "You are an experienced Business Analyst. Convert BRD into a structured FRD JSON. "
                    "Include functional, non-functional requirements, use cases, assumptions, dependencies, constraints."
                ),
            }
            user_prompt = {
                "role": "user",
                "content": f"BRD Content:\n{text}\nReturn strict JSON with FRD structure."
            }

            ai_response = await self.ai.chat(
                [system_prompt, user_prompt],
                provider="groq",
                response_format_json=True
            )

            try:
                frd_json = json.loads(ai_response)
            except Exception:
                raise HTTPException(status_code=500, detail="AI returned non-JSON for BRD->FRD conversion")

            # ----------------------
            # Prepare file path
            # ----------------------
            frd_file_path = Path(CONVERTED_FRD_DIR) / f"frd_{document_id}_{int(datetime.datetime.utcnow().timestamp())}.json"
            frd_file_path.parent.mkdir(parents=True, exist_ok=True)  # Ensure directory exists
            # ----------------------
            # Compute doc_number
            # ----------------------
            result = await db.execute(
                select(Documents.doc_number)
                .where(Documents.project_id == brd_doc.project_id)
                .order_by(Documents.doc_number.desc())
            )
            last_number = result.scalars().first()
            next_number = (last_number or 0) + 1
            # ----------------------
            # Create FRD document row
            # ----------------------
            frd_doc = Documents(
                project_id=brd_doc.project_id,
                doctype=DocType.FRD,
                version=1,
                file_path=str(frd_file_path),
                doc_number=next_number,
            )
            db.add(frd_doc)
            await db.commit()
            await db.refresh(frd_doc)

            # ----------------------
            # Save FRD JSON to disk
            # ----------------------
            frd_file_path.write_text(json.dumps(frd_json, indent=2), encoding="utf-8")

            # ----------------------
            # Create BRD->FRD mapping
            # ----------------------
            mapping = BRDToFRDVersions(
                brd_id=brd_doc.id,
                frd_id=frd_doc.id,
                changes={"converted_frd": frd_json},
                created_at=datetime.datetime.utcnow()
            )
            db.add(mapping)
            await db.commit()
            await db.refresh(mapping)

            return {
                "brd_id": brd_doc.id,
                "frd_id": frd_doc.id,
                "converted_frd" : frd_json,
                "mapping_id": mapping.id,
                "frd_file_path": str(frd_file_path),
            }

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"BRD->FRD conversion failed: {e}")

    async def _get_frd_from_brd(self, db: AsyncSession, brd_id: int):
        mapping = await db.execute(
            select(BRDToFRDVersions)
            .where(BRDToFRDVersions.brd_id == brd_id)
            .order_by(BRDToFRDVersions.id.desc())
        )
        mapping = mapping.scalars().first()
        if not mapping:
            raise HTTPException(status_code=404, detail="No FRD found for this BRD")

        frd_doc = await db.get(Documents, mapping.frd_id)
        if not frd_doc:
            raise HTTPException(status_code=404, detail="FRD document referenced by mapping not found")
        return frd_doc
    # --------------------------
    # Get latest FRD for a BRD
    # --------------------------
    # async def _get_frd_from_brd(self, db: AsyncSession, brd_id: int) -> Documents:
    #     result = await db.execute(
    #         select(BRDToFRDVersions).where(BRDToFRDVersions.brd_id == brd_id).order_by(BRDToFRDVersions.id.desc())
    #     )
    #     mapping = result.scalars().first()
    #     if not mapping:
    #         raise HTTPException(status_code=404, detail="No FRD found for this BRD")

    #     frd_doc = await db.get(Documents, mapping.frd_id)
    #     if not frd_doc:
    #         raise HTTPException(status_code=404, detail="FRD document referenced by mapping not found")
    #     return frd_doc

    # --------------------------
    # Analyze FRD
    # --------------------------
    async def analyze_brd_frd(self, db: AsyncSession, brd_id: int) -> Dict[str, Any]:
        # Fetch the corresponding FRD document from the BRD
        frd_doc = await self._get_frd_from_brd(db, brd_id)
        
        # Perform analysis via FRD agent
        result = await self.frd_agent.analyze_frd_mapreduce(db, frd_doc.id)
        anomalies = result.get("anomalies", result)

        # Safely get status; fallback to 'draft' if not present
        status_value = getattr(frd_doc, "status", None)
        status = getattr(status_value, "value", status_value) if status_value else "draft"

        # Safely get active version ID if available
        active_version_id = getattr(frd_doc, "active_version_id", None)

        return {
            "message": f"Analyzed FRD {frd_doc.id} for BRD {brd_id}",
            "frd_id": frd_doc.id,
            "frd_version_id": active_version_id,
            "anomalies": anomalies,
            "status": status,
            "file_path": frd_doc.file_path,
        }

    async def propose_fix_to_btf(
    self,
    db: AsyncSession,
    brd_id: int,
    issue_ids: list[int]
):
        # Get the FRD corresponding to this BRD
        frd_doc = await self._get_frd_from_brd(db, brd_id)

        # Get latest FRD version to fetch anomalies
        result = await db.execute(
            select(FRDVersions)
            .where(FRDVersions.frd_id == frd_doc.id)
            .order_by(FRDVersions.id.desc())
            .limit(1)
        )
        latest_version = result.scalar_one_or_none()
        if not latest_version:
            raise HTTPException(status_code=404, detail="No FRD version found for proposed fixes")

        # Extract anomalies
        anomalies = latest_version.changes.get("anomalies", [])
        if not anomalies:
            raise HTTPException(status_code=400, detail="No anomalies found in latest FRD version")

        # Filter anomalies by requested issue_ids
        selected_issues = [a for a in anomalies if a.get("id") in issue_ids]
        if not selected_issues:
            raise HTTPException(status_code=400, detail="Selected issues not found in FRD anomalies")

        # Use existing propose_fixes logic
        return await self.propose_fixes(db, frd_doc.id, selected_issues)


    # --------------------------
    # Update FRD via chat/AI
    # --------------------------
    async def update_frd(self, db: AsyncSession, brd_id: int, user_message: str) -> Dict[str, Any]:
        frd_doc = await self._get_frd_from_brd(db, brd_id)

        # Load latest FRD JSON
        path = Path(frd_doc.file_path)
        if path.exists():
            current_json = json.loads(path.read_text(encoding="utf-8"))
        else:
            stmt = select(FRDVersions).where(FRDVersions.frd_id == frd_doc.id).order_by(FRDVersions.id.desc())
            res = await db.execute(stmt)
            latest = res.scalars().first()
            if not latest:
                raise HTTPException(status_code=404, detail="No FRD content available")
            current_json = latest.changes.get("frd") or latest.changes

        # AI prompt for update
        sys = {"role": "system", "content": "You are a requirements engineer. Update FRD per user instructions and return full JSON."}
        usr = {"role": "user", "content": f"User request: {user_message}\n\nCurrent FRD:\n{json.dumps(current_json, indent=2)}"}

        content = await self.ai.chat([sys, usr], provider="groq", response_format_json=True)
        try:
            updated_frd = json.loads(content)
        except Exception:
            raise HTTPException(status_code=500, detail="AI returned invalid JSON for FRD update")

        # Save new FRDVersions row
        row = FRDVersions(
            frd_id=frd_doc.id,
            changes={"frd": updated_frd, "action": "chat_update", "message": user_message},
            created_at=datetime.datetime.utcnow()
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)

        # Update active version pointer
        if hasattr(frd_doc, "active_version_id"):
            frd_doc.active_version_id = row.id
            await db.commit()

        # Update file on disk
        Path(frd_doc.file_path).write_text(json.dumps(updated_frd, indent=2), encoding="utf-8")

        return {"frd_id": frd_doc.id, "update_version_id": row.id, "status": "updated"}
    
    async def apply_fix_to_btf(self, db: AsyncSession, brd_id: int, version_id: int | None = 0):
        frd_doc = await self._get_frd_from_brd(db, brd_id)

        fixes_to_apply = []
        context_version_id = None

        if version_id and version_id > 0:
            # Fetch specific proposed fix version
            result = await db.execute(select(FRDVersions).where(FRDVersions.id == version_id))
            proposed_version = result.scalar_one_or_none()
            if not proposed_version:
                raise HTTPException(status_code=404, detail="Proposed fixes version not found")
            fixes_to_apply = proposed_version.changes.get("proposed_fixes", [])
            context_version_id = proposed_version.changes.get("context_from_version")
        else:
            # Fallback: use latest analysis anomalies from FRD
            result = await db.execute(
                select(FRDVersions)
                .where(FRDVersions.frd_id == frd_doc.id)
                .order_by(FRDVersions.id.desc())
                .limit(1)
            )
            latest_version = result.scalar_one_or_none()

            if latest_version and latest_version.changes.get("anomalies"):
                fixes_to_apply = latest_version.changes["anomalies"]
                context_version_id = latest_version.id
            else:
                # If no proposed fixes or anomalies, fallback to empty but do not fail
                fixes_to_apply = []
                context_version_id = None

        # Apply fixes automatically if nothing exists
        applied_fixes = [
            {
                "section": f.get("section"),
                "issue": f.get("issue"),
                "fix": f.get("fix", "Auto-applied based on current analysis")
            }
            for f in fixes_to_apply
        ]

        # Save applied fixes as new FRD version
        new_version = FRDVersions(
            frd_id=frd_doc.id,
            changes={
                "applied_fixes": applied_fixes,
                "context_from_version": context_version_id,
            },
            created_at=datetime.datetime.utcnow(),
        )
        db.add(new_version)
        await db.commit()
        await db.refresh(new_version)

        return {
            "message": "Applied fixes successfully",
            "version_id": new_version.id,
            "applied_fixes": applied_fixes
        }



    async def _get_frd_from_brd(self, db: AsyncSession, brd_id: int) -> Documents:
        """
        Helper to get FRD document corresponding to a BRD.
        Assumes FRD is generated for the BRD and exists in `Documents` table.
        """
        result = await db.execute(
            select(Documents)
            .where(Documents.project_id == brd_id, Documents.doctype == "FRD")
            .limit(1)
        )
        frd_doc = result.scalar_one_or_none()
        if not frd_doc:
            raise HTTPException(status_code=404, detail="No FRD document found for this BRD")
        return frd_doc

    # --------------------------
    # Revert FRD to previous BRD->FRD mapping
    # --------------------------
    async def revert(self, db: AsyncSession, brd_id: int, to_version_id: int) -> Dict[str, Any]:
        target = await db.get(BRDToFRDVersions, to_version_id)
        if not target or target.brd_id != brd_id:
            raise HTTPException(status_code=404, detail="Target BRD->FRD version not found")

        snapshot = target.changes.get("converted_frd") or target.changes

        new_version = BRDToFRDVersions(
            brd_id=brd_id,
            frd_id=target.frd_id,
            changes={"converted_frd": snapshot, "action": "revert", "reverted_from": to_version_id},
            created_at=datetime.datetime.utcnow()
        )
        db.add(new_version)
        await db.commit()
        await db.refresh(new_version)

        frd_doc = await db.get(Documents, target.frd_id)
        if frd_doc and frd_doc.file_path:
            Path(frd_doc.file_path).write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

        return {
            "brd_id": brd_id,
            "frd_id": target.frd_id,
            "reverted_from_version": to_version_id,
            "new_version_id": new_version.id,
            "status": "reverted"
        }

    # --------------------------
    # Generate testcases
    # --------------------------
    async def generate_testcases(self, db: AsyncSession, brd_id: int) -> Dict[str, Any]:
        frd_doc = await self._get_frd_from_brd(db, brd_id)

        # Fetch the latest FRD version
        result = await db.execute(
            select(FRDVersions)
            .where(FRDVersions.frd_id == frd_doc.id)
            .order_by(FRDVersions.id.desc())
            .limit(1)
        )
        latest_frd = result.scalar_one_or_none()
        if not latest_frd:
            raise HTTPException(status_code=404, detail="No FRD version found for this BRD")

        # Now call the original generate_testcases, passing latest version ID
        testgen_service = TestGenServies()
        return await testgen_service.generate_testcases(
            db=db,
            document_id=frd_doc.id
        )

    # --------------------------
    # Update testcases via chat
    # --------------------------
    async def update_testcases(
    self,
    db: AsyncSession,
    brd_id: int,
    request: TestCaseUpdateRequest,
    commit: bool = False
) -> dict[str, any]:
        """
        Update testcases for the FRD document linked to a BRD document.
        """
        # Get FRD document from BRD id
        frd_doc = await self._get_frd_from_brd(db, brd_id)

        # Call the tc_agent chat_update to update the testcases
        result = await self.tc_agent.chat_update(
            db=db,
            document_id=frd_doc.id,
            request=request,
            commit=commit
        )
        return result


    # -------------------------
    # Generate testcases (delegate to TestGenServies)
    # -------------------------
    # async def generate(self, db: AsyncSession, brd_id: int) -> Dict[str, Any]:
    #     """
    #     Generate testcases based on the latest FRD corresponding to the given BRD.
    #     Returns the full testcases response from TestGenServies.
    #     """
    #     # 1. Get the latest FRD for the BRD
    #     frd_doc = await self._get_frd_from_brd(db, brd_id)

    #     # 2. Call TestGenServies to generate testcases
    #     result = await self.tc_agent.generate_testcases(db, frd_doc.id)

    #     # 3. Optionally, you could store a 'TestcaseVersion' row here if you have versioning
    #     #    For now, just return the generated result
    #     return result

    # # -------------------------
    # # Update testcases (chat-style) - delegate to TestGenServies.chat_update
    # # -------------------------
    # async def update_testcases(self, db: AsyncSession, brd_id: int, request: TestCaseUpdateRequest, commit: bool = False) -> Dict[str, Any]:
    #     """
    #     Update testcases for the latest FRD corresponding to the given BRD using chat/AI input.
    #     Handles preview vs commit based on 'commit' flag.
    #     """
    #     # 1. Get latest FRD
    #     frd_doc = await self._get_frd_from_brd(db, brd_id)

    #     # 2. Delegate to TestGenServies.chat_update
    #     #    chat_update internally handles generating preview or committing new testcases
    #     result = await self.tc_agent.chat_update(db, frd_doc.id, request, commit=commit)

    #     # 3. Optionally, maintain a version pointer to the FRD active_version_id if needed
    #     if commit and hasattr(frd_doc, "active_version_id"):
    #         # For traceability, you could link testcases to FRD version
    #         # e.g., store active FRD version in the returned object
    #         result["frd_version_id"] = frd_doc.active_version_id

    #     return result
        
    # ------------------------------BRD Streaming Functions ------------------------------
    # ---------------------------------------------------------------------------------

    # ---------- BRD → FRD conversion ----------
    async def stream_brd_to_frd(self, db: AsyncSession, document_id: int, model: str | None = None):
        brd_doc = await db.get(Documents, document_id)
        if not brd_doc or brd_doc.doctype != DocType.BRD:
            raise HTTPException(status_code=404, detail="BRD not found")

        path = Path(brd_doc.file_path)
        if not path.exists():
            raise HTTPException(status_code=404, detail="BRD file not found on disk")

        text = await self.extractor.extract_text_content(path.read_bytes(), path.suffix.lower())

        sys = {
            "role": "system",
            "content": "You are an experienced Business Analyst. Convert BRD→FRD. Return strict JSON."
        }
        usr = {
            "role": "user",
            "content": f"Convert the following BRD into FRD JSON:\n\n{text}"
        }

        async def event_generator():
            yield f"data: {json.dumps({'type': 'start', 'document_id': document_id, 'action': 'brd_to_frd'})}\n\n"
            chunk_buf = ""

            async for token in self.ai._groq_chat_stream(
                [sys, usr],
                model=model or "llama-3.1-8b-instant",
                temperature=0.2,
                timeout=120,
            ):
                token_piece = token.get("text") if isinstance(token, dict) else str(token)
                chunk_buf += token_piece
                yield f"data: {json.dumps({'type': 'token', 'text': token_piece})}\n\n"

            # Final event
            yield f"data: {json.dumps({'type': 'complete','document_id': document_id,'frd_json_text': chunk_buf})}\n\n"
            yield "data: [DONE]\n\n"

        return event_generator()


    # ---------- Analyze BRD (via FRD) ----------
    async def stream_analyze_brd_frd(self, db: AsyncSession, brd_id: int):
        frd_doc = await self._get_frd_from_brd(db, brd_id)
        # This already returns a generator from frd_agent:
        return await self.frd_agent.analyze_frd_mapreduce_stream(db, frd_doc.id)


    # ---------- Propose fixes ----------
    async def stream_propose_fix_to_btf(self, db: AsyncSession, brd_id: int, selected_issues: dict):
        frd_doc = await self._get_frd_from_brd(db, brd_id)
        return await self.frd_agent.propose_fix_stream(db, frd_doc.id, selected_issues["anomalies"])


    # ---------- Update FRD ----------
    async def stream_update_frd(self, db: AsyncSession, brd_id: int, user_message: str):
        frd_doc = await self._get_frd_from_brd(db, brd_id)

        path = Path(frd_doc.file_path)
        if path.exists():
            current_json = json.loads(path.read_text(encoding="utf-8"))
        else:
            stmt = (
                select(FRDVersions)
                .where(FRDVersions.frd_id == frd_doc.id)
                .order_by(FRDVersions.id.desc())
            )
            res = await db.execute(stmt)
            latest = res.scalars().first()
            if not latest:
                raise HTTPException(status_code=404, detail="No FRD content available")
            current_json = latest.changes.get("frd") or latest.changes

        sys = {
            "role": "system",
            "content": "You are a requirements engineer. Modify the FRD per user instructions and return strict JSON of the full FRD."
        }
        usr = {
            "role": "user",
            "content": f"User request: {user_message}\n\nCurrent FRD JSON:\n{json.dumps(current_json, indent=2)}"
        }

        async def event_generator():
            yield f"data: {json.dumps({'type': 'start','frd_id': frd_doc.id,'action':'update_frd'})}\n\n"
            chunk_buf = ""

            async for token in self.ai._groq_chat_stream(
                [sys, usr],
                model="llama-3.1-8b-instant",
                temperature=0.2,
                timeout=120,
            ):
                token_piece = token.get("text") if isinstance(token, dict) else str(token)
                chunk_buf += token_piece
                yield f"data: {json.dumps({'type': 'token', 'text': token_piece})}\n\n"

            yield f"data: {json.dumps({'type': 'complete','frd_id': frd_doc.id,'updated_frd_json_text': chunk_buf})}\n\n"
            yield "data: [DONE]\n\n"

        return event_generator()


    # ---------- Testcases ----------
    async def stream_generate_testcases(self, db: AsyncSession, brd_id: int):
        frd_doc = await self._get_frd_from_brd(db, brd_id)
        return await self.tc_agent.generate_testcases_stream(db, frd_doc.id, self.ai, self.extractor)


    async def stream_update_testcases(self, db: AsyncSession, brd_id: int, request: TestCaseUpdateRequest):
        frd_doc = await self._get_frd_from_brd(db, brd_id)
        return await self.tc_agent.chat_update_stream(db, frd_doc.id, request)
