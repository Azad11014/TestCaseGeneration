import asyncio
import datetime
import json, os
from pathlib import Path
from typing import Dict, Any, List, Optional
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import desc, select
from app.models.models import Documents, DocType, FRDVersions
from app.services.ai_client_services import AiClientService
from app.services.content_extraction_service import ContentExtractionService
from app.models.models import Documents

DATA_DIR = Path("data")
FRD_OUT_DIR = DATA_DIR / "frd"
ANALYSIS_DIR = DATA_DIR / "analysis"
FRD_OUT_DIR.mkdir(exist_ok=True, parents=True)
ANALYSIS_DIR.mkdir(exist_ok=True, parents=True)

# concurrency control for parallel chunk calls (configurable)
_CHUNK_CONCURRENCY = 4
_BATCH_REDUCE_SIZE = 100

ai = AiClientService()
extractor = ContentExtractionService()


class FRDAgentService:
    def __init__(self):
        self.ai = ai or AiClientService()
        self.extractor = extractor or ContentExtractionService()

    def _doctype_value(self, doc):
        """
        Return a normalized string value for a document's doctype.
        Works whether doc.doctype is an Enum (DocType) or a plain string.
        """
        dt = getattr(doc, "doctype", None)
        if dt is None:
            return None
        return dt.value if hasattr(dt, "value") else str(dt)


    async def _load_document_text(self, doc: Documents) -> str:
        try :
            path = Path(doc.file_path)
            if not path.exists():
                raise HTTPException(status_code=404, detail="File not found on disk")

            content = path.read_bytes()
            extension = path.suffix.lower()
            return await self.extractor.extract_text_content(content, extension)
        except HTTPException as he:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Something went wrong in reading document {e}")
    async def analyze_frd_mapreduce(self, db: AsyncSession, document_id: int) -> dict:
        try:
            doc = await db.get(Documents, document_id)
            # robust doctype check
            if not doc or self._doctype_value(doc) != DocType.FRD.value:
                raise HTTPException(status_code=404, detail="FRD document not found")

            text = await self._load_document_text(doc)

            # Step 1: Split into chunks
            chunks = self.extractor._split_into_token_chunks(text, max_tokens=2000)

            # Step 2: Map Phase – process each chunk in parallel
            async def process_chunk(chunk, idx):
                sys = {
                    "role": "system",
                    "content": "You are a senior QA analyst. Extract anomalies from this FRD chunk."
                }
                usr = {
                    "role": "user",
                    "content": (
                        "Return strict JSON: "
                        '{ "anomalies": [ {"section": str, "issue": str, '
                        '"severity": "low|medium|high", "suggestion": str } ] }\n\n'
                        f"FRD Chunk {idx}:\n{chunk}"
                    ),
                }
                resp = await self.ai.chat([sys, usr], provider="groq", response_format_json=True)
                try:
                    return json.loads(resp) if isinstance(resp, str) else resp
                except Exception:
                    return {"anomalies": []}

            partial_results = await asyncio.gather(
                *[process_chunk(c, i) for i, c in enumerate(chunks)]
            )

            # Step 3: Reduce Phase – merge all anomalies with IDs
            merged_anomalies = []
            for idx, r in enumerate(partial_results):
                for anomaly in r.get("anomalies", []):
                    anomaly["id"] = len(merged_anomalies) + 1
                    merged_anomalies.append(anomaly)

            # Step 4: Save anomalies into FRDVersions (DB)
            row = FRDVersions(
                frd_id=document_id,
                changes={"anomalies": merged_anomalies},
                created_at=datetime.datetime.utcnow(),
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)

            # Step 5: Save anomalies on disk
            out_path = ANALYSIS_DIR / f"frd_{document_id}_anomalies_{row.id}.json"
            out_path.write_text(json.dumps({"anomalies": merged_anomalies}, indent=2), encoding="utf-8")

            return {"version_id": row.id, "anomalies": merged_anomalies}

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Something is broken : {e}")

    # async def analyze_frd(self, db: AsyncSession, document_id: int) -> dict:
    #     try:
    #         doc = await db.get(Documents, document_id)
    #         if not doc or doc.doctype != DocType.FRD:
    #             raise HTTPException(status_code=404, detail="FRD document not found")

    #         text = await self._load_document_text(doc)

    #         sys = {
    #             "role": "system",
    #             "content": (
    #                 "You are a senior QA analyst. "
    #                 "Find ambiguities, contradictions, missing NFRs, untestable requirements."
    #             ),
    #         }
    #         usr = {
    #             "role": "user",
    #             "content": (
    #                 "Analyze the following FRD. Return strict JSON with fields:\n"
    #                 "{ \"anomalies\": [ {\"section\": str, \"issue\": str, "
    #                 "\"severity\": \"low|medium|high\", \"suggestion\": str } ] }\n\n"
    #                 f"FRD:\n{text}"
    #             ),
    #         }

    #         # Call AI
    #         content = await self.ai.chat([sys, usr], provider="groq", response_format_json=True)

    #         try:
    #             result = json.loads(content)
    #         except Exception:
    #             raise HTTPException(status_code=500, detail="AI returned non-JSON for anomaly analysis")

    #         # Save version
    #         row = FRDVersions(
    #             frd_id=document_id,
    #             changes={"anomalies": result.get("anomalies", [])},
    #             created_at=datetime.datetime.utcnow(),
    #         )
    #         db.add(row)
    #         await db.commit()
    #         await db.refresh(row)

    #         # Save output file
    #         out_path = ANALYSIS_DIR / f"frd_{document_id}_anomalies_{row.id}.json"
    #         out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    #         return {"version_id": row.id, "anomalies": result.get("anomalies", [])}
    #     except HTTPException as he:
    #         raise
    #     except Exception as e:
    #         raise HTTPException(status_code=500, detail=f"Something went wrong in analyzing frd : {e}")
    
    async def propose_fixes(
    self,
    db: AsyncSession,
    document_id: int,
    selected_issues: List[Dict[str, Any]]
):
        if not selected_issues:
            raise HTTPException(status_code=400, detail="No issues selected for fixing")

        # Get latest FRD version (context for applying fixes)
        result = await db.execute(
            select(FRDVersions)
            .where(FRDVersions.frd_id == document_id)
            .order_by(FRDVersions.id.desc())
            .limit(1)
        )
        latest = result.scalar_one_or_none()
        if not latest:
            raise HTTPException(status_code=404, detail="No FRD version found")

        # Use the latest anomalies or full context if available
        context_json = latest.changes if isinstance(latest.changes, dict) else {"data": latest.changes}

        sys = {
            "role": "system",
            "content": "You are a senior business analyst. Suggest precise fixes for the selected issues."
        }
        usr = {
            "role": "user",
            "content": (
                "Given the FRD analysis context and the selected issues, return a strict JSON object "
                "with field `proposed_fixes` that is a list of fixes. Each fix should map to the issue and "
                "contain 'section', 'issue', and 'fix' fields.\n\n"
                f"FRD Context:\n{json.dumps(context_json, indent=2)}\n\n"
                f"Selected issues:\n{json.dumps(selected_issues, indent=2)}"
            ),
        }

        # Call AI
        fixes_resp = await self.ai.chat([sys, usr], provider="groq", response_format_json=True)

        # Parse AI response safely to JSON
        try:
            fixes_json = json.loads(fixes_resp) if isinstance(fixes_resp, str) else fixes_resp
        except Exception:
            raise HTTPException(status_code=500, detail="AI returned invalid JSON for proposed fixes")

        # Normalize to expected structure: either top-level object with proposed_fixes or itself is a list
        if isinstance(fixes_json, dict) and "proposed_fixes" in fixes_json:
            proposed = fixes_json["proposed_fixes"]
        elif isinstance(fixes_json, list):
            proposed = fixes_json
        else:
            # try to wrap anomalies into proposed list if structure differs
            proposed = fixes_json.get("fixes") if isinstance(fixes_json, dict) and fixes_json.get("fixes") else [fixes_json]

        # Persist proposed fixes as a new FRDVersions row
        row = FRDVersions(
            frd_id=document_id,
            changes={
                "selected_issues": selected_issues,
                "proposed_fixes": proposed,
                "context_from_version": latest.id
            },
            created_at=datetime.datetime.utcnow(),
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)

        # Save the proposed fixes to disk for auditing/preview
        out_path = ANALYSIS_DIR / f"frd_{document_id}_proposed_fixes_{row.id}.json"
        out_path.write_text(json.dumps(row.changes, indent=2), encoding="utf-8")

        return {"version_id": row.id, "proposed_fixes": proposed}


    async def apply_fix(
    self,
    db: AsyncSession,
    document_id: int,
    version_id: int | None = None
) -> dict:
        try:
            # 1. Ensure FRD exists
            doc = await db.get(Documents, document_id)
            if not doc or doc.doctype != DocType.FRD:
                raise HTTPException(status_code=404, detail="FRD not found")

            # 2. Pick target version
            if version_id is None:
                q = await db.execute(
                    select(FRDVersions)
                    .where(FRDVersions.frd_id == document_id)
                    .order_by(desc(FRDVersions.id))
                    .limit(1)
                )
                version = q.scalar_one_or_none()
            else:
                version = await db.get(FRDVersions, version_id)

            if not version or version.frd_id != document_id:
                raise HTTPException(status_code=404, detail="Version not found for this FRD")

            # 3. Try to get fixes
            fixes = version.changes.get("proposed_fixes")

            # If no fixes but anomalies exist → auto propose fixes
            if not fixes and "anomalies" in version.changes:
                sys = {
                    "role": "system",
                    "content": "You are a senior business analyst. Suggest precise fixes for the issues."
                }
                usr = {
                    "role": "user",
                    "content": f"FRD anomalies:\n{json.dumps(version.changes['anomalies'], indent=2)}"
                }
                ai_fixes = await self.ai.chat([sys, usr], provider="groq", response_format_json=True)

                try:
                    fixes = json.loads(ai_fixes).get("fixes") or json.loads(ai_fixes)
                except Exception:
                    raise HTTPException(status_code=500, detail="AI returned invalid fixes JSON")

            if not fixes:
                raise HTTPException(status_code=400, detail="No anomalies or fixes found to apply")

            # 4. Save applied fixes as a new version
            new_version = FRDVersions(
                frd_id=document_id,
                changes={"applied_fixes": fixes},
                created_at=datetime.datetime.utcnow(),
            )
            db.add(new_version)
            await db.commit()
            await db.refresh(new_version)

            return {"version_id": new_version.id, "applied_fixes": fixes}

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Something went wrong in apply fix: {e}")

    # ---------------- Streaming map-reduce SSE generator ----------------
    async def analyze_frd_mapreduce_stream(self, db: AsyncSession, document_id: int, model: str | None = None):
        doc = await db.get(Documents, document_id)
        if not doc or self._doctype_value(doc) != DocType.FRD.value:
            raise HTTPException(status_code=404, detail="FRD document not found")

        text = await self._load_document_text(doc)
        chunks = self.extractor._split_into_token_chunks(text, max_tokens=2000, overlap_tokens=200)

        # Create initial row
        row = FRDVersions(
            frd_id=document_id,
            changes={"streaming": True},
            created_at=datetime.datetime.utcnow(),
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)

        merged_anomalies = []
        anomaly_counter = 1

        for idx, chunk in enumerate(chunks):
            sys = {"role": "system", "content": "You are a senior QA analyst. Extract anomalies from this FRD chunk."}
            usr = {"role": "user", "content": (
                "Return strict JSON: "
                '{ "anomalies": [ {"section": str, "issue": str, '
                '"severity": "low|medium|high", "suggestion": str } ] }\n\n'
                f"FRD Chunk {idx+1}:\n{chunk}"
            )}

            resp = await self.ai.chat([sys, usr], provider="groq", response_format_json=True)
            try:
                parsed = json.loads(resp) if isinstance(resp, str) else resp
            except Exception:
                parsed = {"anomalies": []}

            for a in parsed.get("anomalies", []):
                a["id"] = anomaly_counter
                anomaly_counter += 1
                merged_anomalies.append(a)

        # Save anomalies **before streaming**
        row.changes = {"anomalies": merged_anomalies}
        await db.commit()
        await db.refresh(row)

        payload = {
            "version_id": row.id,
            "anomalies": merged_anomalies
        }

        async def generator():
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        return generator()
