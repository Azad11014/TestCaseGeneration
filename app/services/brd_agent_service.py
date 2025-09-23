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
        Convert a stored BRD document into an FRD JSON, create FRD Document row,
        initial FRDVersions row, BRD->FRD mapping, save file, return metadata.
        """
        try:
            # 1. Load BRD document
            brd_doc = await db.get(Documents, document_id)
            if not brd_doc or brd_doc.doctype != DocType.BRD:
                raise HTTPException(status_code=404, detail="BRD not found")

            path = Path(brd_doc.file_path)
            if not path.exists():
                raise HTTPException(status_code=404, detail="BRD file not found on disk")

            # 2. Extract text
            content = path.read_bytes()
            text = await self.extractor.extract_text_content(content, path.suffix.lower())

            # 3. Ask AI to convert BRD → FRD
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

            ai_response = await self.ai.chat([system_prompt, user_prompt], provider="groq", response_format_json=True)
            try:
                frd_json = json.loads(ai_response)
            except Exception:
                raise HTTPException(status_code=500, detail="AI returned invalid JSON for BRD->FRD conversion")

            # 4. Create FRD document
            frd_file_path = str(CONVERTED_FRD_DIR / f"frd_{document_id}_{int(datetime.datetime.utcnow().timestamp())}.json")
            # Save FRD document
            frd_doc = Documents(
                project_id=brd_doc.project_id,
                doctype=DocType.FRD,
                file_path=str(frd_file_path),
                doc_number=1,   # TODO: assign next doc_number per project
                version=1,
            )
            db.add(frd_doc)
            await db.commit()
            await db.refresh(frd_doc)

            # Track BRD → FRD mapping
            mapping = BRDToFRDVersions(
                brd_id=brd_doc.id,
                frd_id=frd_doc.id,
                changes={"action": "conversion", "timestamp": str(datetime.datetime.utcnow())},
            )
            db.add(mapping)
            await db.commit()
            await db.refresh(mapping)

            return {"frd_id": frd_doc.id, "converted frd ": frd_json, "frd_path":frd_file_path}


        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"BRD->FRD conversion failed: {e}")



    async def _get_frd_from_brd(self, db: AsyncSession, brd_id: int) -> Documents:
        mapping = await db.execute(
            select(BRDToFRDVersions).where(BRDToFRDVersions.brd_id == brd_id).order_by(BRDToFRDVersions.id.desc())
        )
        mapping = mapping.scalars().first()
        if not mapping:
            raise HTTPException(status_code=404, detail="No FRD found for this BRD")

        frd_doc = await db.get(Documents, mapping.frd_id)
        if not frd_doc:
            raise HTTPException(status_code=404, detail="FRD document referenced by mapping not found")
        return frd_doc

    
    async def analyze_brd_frd(self, db: AsyncSession, brd_id: int):
        frd_doc = await self._get_frd_from_brd(db, brd_id)
        result = await self.frd_agent.analyze_frd_mapreduce(db, frd_doc.id)
        anomalies = result.get("anomalies", result)

        # return structured response
        return {
            "message": f"Analyzed FRD {frd_doc.id} for BRD {brd_id}",
            "frd_id": frd_doc.id,
            "frd_version_id": frd_doc.active_version_id,
            "anomalies": anomalies,
            "status": frd_doc.status.value,
            "file_path": frd_doc.file_path,
        }

            
    # Reuse components from FRD Agent, but use BRD apis and main  BRd database models
    async def propose_fix_to_btf(self, db: AsyncSession, brd_id: int, selected_issues: dict) -> dict:
        frd_doc = await self._get_frd_from_brd(db, brd_id)
        fixes = await self.frd_agent.propose_fixes(db, frd_doc.id, selected_issues.get("anomalies", []))

        # Persist as new FRDVersions
        row = FRDVersions(
            frd_id=frd_doc.id,
            changes={"original_issues": selected_issues, "proposed_fixes": fixes},
            created_at=datetime.datetime.utcnow()
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)

        # Update active pointer
        if hasattr(frd_doc, "active_version_id"):
            frd_doc.active_version_id = row.id
            await db.commit()

        return {
            "frd_id": frd_doc.id,
            "propose_version_id": row.id,
            "proposed_fixes": fixes
        }

    async def apply_fix_to_btf(self, db: AsyncSession, brd_id: int, version_id: int) -> Dict[str, Any]:
        frd_doc = await self._get_frd_from_brd(db, brd_id)
        result = await self.frd_agent.apply_fix(db, frd_doc.id, version_id)

        new_version_id = result.get("version_id")
        if new_version_id and hasattr(frd_doc, "active_version_id"):
            frd_doc.active_version_id = new_version_id
            await db.commit()

        return {"frd_id": frd_doc.id, "applied_version_id": new_version_id, "applied_fixes": result.get("applied_fixes")}

    async def update_frd(self, db: AsyncSession, brd_id: int, user_message: str) -> Dict[str, Any]:
        frd_doc = await self._get_frd_from_brd(db, brd_id)

        # Load current FRD snapshot
        path = Path(frd_doc.file_path)
        if path.exists():
            current_json = json.loads(path.read_text(encoding="utf-8"))
        else:
            stmt = select(FRDVersions).where(FRDVersions.frd_id == frd_doc.id).order_by(FRDVersions.id.desc())
            latest = (await db.execute(stmt)).scalars().first()
            if not latest:
                raise HTTPException(status_code=404, detail="No FRD content available")
            current_json = latest.changes.get("frd") or latest.changes

        # AI prompt
        system_prompt = {"role": "system", "content": "You are a requirements engineer. Update the FRD per user instructions."}
        user_prompt = {"role": "user", "content": f"{user_message}\nCurrent FRD:\n{json.dumps(current_json, indent=2)}"}

        content = await self.ai.chat([system_prompt, user_prompt], provider="groq", response_format_json=True)
        try:
            updated_frd = json.loads(content)
        except Exception:
            raise HTTPException(status_code=500, detail="AI returned invalid JSON")

        # Persist new FRDVersions
        row = FRDVersions(frd_id=frd_doc.id, changes={"frd": updated_frd, "action": "chat_update", "message": user_message}, created_at=datetime.datetime.utcnow())
        db.add(row)
        await db.commit()
        await db.refresh(row)

        if hasattr(frd_doc, "active_version_id"):
            frd_doc.active_version_id = row.id
            await db.commit()

        Path(frd_doc.file_path).write_text(json.dumps(updated_frd, indent=2), encoding="utf-8")

        return {"frd_id": frd_doc.id, "update_version_id": row.id, "status": "updated"}

    # In BRDAgentService
    async def revert(self, db: AsyncSession, brd_id: int, to_version_id: int) -> dict:
        """
        Revert the BRD→FRD mapping to a previous BRDToFRDVersions version.
        Creates a new BRDToFRDVersions row with the reverted content.
        """
        # 1. Load target version
        target = await db.get(BRDToFRDVersions, to_version_id)
        if not target or target.brd_id != brd_id:
            raise HTTPException(status_code=404, detail="Target BRD->FRD version not found")

        # 2. Load snapshot JSON
        snapshot = target.changes.get("converted_frd") or target.changes

        # 3. Create new BRDToFRDVersions row with reverted content
        new_version = BRDToFRDVersions(
            brd_id=brd_id,
            frd_id=target.frd_id,  # keep same FRD doc
            changes={"converted_frd": snapshot, "action": "revert", "reverted_from": to_version_id},
            created_at=datetime.datetime.utcnow(),
        )
        db.add(new_version)
        await db.commit()
        await db.refresh(new_version)

        # 4. Update FRD file (optional) — use target.frd_id to fetch FRD document
        frd_doc = await db.get(Documents, target.frd_id)
        if frd_doc and frd_doc.file_path:
            try:
                Path(frd_doc.file_path).write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
            except Exception as e:
                logger.error(f"Failed to update FRD file on revert: {e}")

        return {
            "brd_id": brd_id,
            "frd_id": target.frd_id,
            "reverted_from_version": to_version_id,
            "new_version_id": new_version.id,
            "status": "reverted",
        }



    # -------------------------
    # Generate testcases (delegate to TestGenServies)
    # -------------------------
    async def generate(self, db: AsyncSession, brd_id: int) -> Dict[str, Any]:
        """
        Generate testcases based on the latest FRD corresponding to the given BRD.
        Returns the full testcases response from TestGenServies.
        """
        # 1. Get the latest FRD for the BRD
        frd_doc = await self._get_frd_from_brd(db, brd_id)

        # 2. Call TestGenServies to generate testcases
        result = await self.tc_agent.generate_testcases(db, frd_doc.id)

        # 3. Optionally, you could store a 'TestcaseVersion' row here if you have versioning
        #    For now, just return the generated result
        return result

    # -------------------------
    # Update testcases (chat-style) - delegate to TestGenServies.chat_update
    # -------------------------
    async def update_testcases(self, db: AsyncSession, brd_id: int, request: TestCaseUpdateRequest, commit: bool = False) -> Dict[str, Any]:
        """
        Update testcases for the latest FRD corresponding to the given BRD using chat/AI input.
        Handles preview vs commit based on 'commit' flag.
        """
        # 1. Get latest FRD
        frd_doc = await self._get_frd_from_brd(db, brd_id)

        # 2. Delegate to TestGenServies.chat_update
        #    chat_update internally handles generating preview or committing new testcases
        result = await self.tc_agent.chat_update(db, frd_doc.id, request, commit=commit)

        # 3. Optionally, maintain a version pointer to the FRD active_version_id if needed
        if commit and hasattr(frd_doc, "active_version_id"):
            # For traceability, you could link testcases to FRD version
            # e.g., store active FRD version in the returned object
            result["frd_version_id"] = frd_doc.active_version_id

        return result
        
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

        sys = {"role": "system", "content": "You are an experienced Business Analyst. Convert BRD→FRD. Return strict JSON."}
        usr = {"role": "user", "content": f"Convert the following BRD into FRD JSON:\n\n{text}"}

        async def event_generator():
            async for token in self.ai._groq_chat_stream([sys, usr], model=model or "llama-3.1-8b-instant", temperature=0.2, timeout=120,):
                yield token
            yield "\n\n[BRD→FRD conversion complete]\n"

        return event_generator()

    # ---------- Analyze BRD (via FRD) ----------
    async def stream_analyze_brd_frd(self, db: AsyncSession, brd_id: int):
        frd_doc = await self._get_frd_from_brd(db, brd_id)
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
            stmt = select(FRDVersions).where(FRDVersions.frd_id == frd_doc.id).order_by(FRDVersions.id.desc())
            res = await db.execute(stmt)
            latest = res.scalars().first()
            if not latest:
                raise HTTPException(status_code=404, detail="No FRD content available")
            current_json = latest.changes.get("frd") or latest.changes

        sys = {"role": "system", "content": "You are a requirements engineer. Modify the FRD per user instructions and return strict JSON of the full FRD."}
        usr = {"role": "user", "content": f"User request: {user_message}\n\nCurrent FRD JSON:\n{json.dumps(current_json, indent=2)}"}

        async def event_generator():
            async for token in self.ai._groq_chat_stream([sys, usr], model="llama-3.1-8b-instant", temperature=0.2, timeout=120,):
                yield token
            yield "\n\n[FRD update complete]\n"

        return event_generator()

    # ---------- Testcases ----------
    async def stream_generate_testcases(self, db: AsyncSession, brd_id: int):
        frd_doc = await self._get_frd_from_brd(db, brd_id)
        return await self.tc_agent.generate_testcases_stream(db, frd_doc.id, ai, extractor)

    async def stream_update_testcases(self, db: AsyncSession, brd_id: int, request: TestCaseUpdateRequest):
        frd_doc = await self._get_frd_from_brd(db, brd_id)
        return await self.tc_agent.chat_update_stream(db, frd_doc.id, request)