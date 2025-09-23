import datetime
import json
from pathlib import Path
import re
from fastapi import HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Dict, Any
from sqlalchemy import select, desc

from app.schema.schema import TestCaseChatRequest, TestCaseUpdateRequest
from app.services.ai_client_services import AiClientService
from app.services.content_extraction_service import ContentExtractionService
from app.services.frd_agent_service import FRDAgentService

from app.models.models import Documents, FRDVersions, DocType, TestCaseStatus, Testcases


ai = AiClientService()

DATA_DIR = Path("data")
TC_DIR = DATA_DIR / "testcases"
TC_DIR.mkdir(exist_ok=True, parents=True)


class TestGenServies:
    def __init__(self):
         self.ai = ai

    async def get_latest_frd_version(self, db: AsyncSession, document_id: int):
        try:
            # Get latest versions first
            q = await db.execute(
                select(FRDVersions)
                .where(FRDVersions.frd_id == document_id)
                .order_by(desc(FRDVersions.id))
            )
            versions = q.scalars().all()

            # Prefer one with applied fixes
            for v in versions:
                if v.changes and "applied_fixes" in v.changes:
                    return v

            # Fallback: just return the latest
            return versions[0] if versions else None

        except HTTPException as he:
            raise he
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Something went wrong fetching latest FRD version: {e}"
            )


    async def generate_testcases(self, db: AsyncSession, document_id: int):
        try:
            # Fetch latest FRD version
            latest_frd = await self.get_latest_frd_version(db, document_id)
            if not latest_frd:
                raise HTTPException(status_code=404, detail="No FRD version found")

            # Full FRD and applied fixes
            frd_full = latest_frd.changes.get("frd") or latest_frd.changes
            applied_fixes = latest_frd.changes.get("applied_fixes", {})

            # Combine full FRD with applied fixes for AI
            combined_content = {
                "full_frd": frd_full,
                "applied_fixes": applied_fixes
            }

            text = json.dumps(combined_content, indent=2)

            # AI prompt
            sys = {"role": "system", "content": "You are a QA automation lead. Generate thorough test cases."}
            usr = {
                "role": "user",
                "content": (
                    "Generate JSON testcases for the entire FRD. "
                    "If applied fixes exist, incorporate them in relevant sections. "
                    "Output strictly JSON: "
                    "{ \"testcases\": [ {\"id\": str, \"title\": str, \"preconditions\": [str], "
                    "\"steps\": [str], \"expected\": str, \"priority\": \"P0|P1|P2\"} ] }\n\n"
                    f"FRD with applied fixes:\n{text}"
                )
            }

            # Call AI
            content = await self.ai.chat([sys, usr], provider="groq", response_format_json=True)
            result = json.loads(content)
            tcs = result.get("testcases", [])

            # Save testcases
            latest_row_id = await self.write_and_record(
                db, document_id, tcs, status=TestCaseStatus.generated
            )

            return {"testcases_id": latest_row_id, "testcases": tcs, "count": len(tcs)}

        except HTTPException as he:
            raise he
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Something went wrong generating testcases: {e}")

    
    async def get_latest_row(self, db: AsyncSession, document_id: int):
        try:
            result = await db.execute(
                select(Testcases)
                .where(Testcases.document_id == document_id)
                .order_by(Testcases.id.desc())
                .limit(1)
            )
            return result.scalar_one_or_none()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Something went wrong {e}")


    async def write_and_record(
    self, db: AsyncSession, document_id: int, testcases: List[dict], status, version: int | None = None
):
        """
        Persist testcases to disk and create a Testcases DB row.
        Converts Enum status to string for DB compatibility.
        """
        dir = Path("data/testcases")
        dir.mkdir(parents=True, exist_ok=True)
        ts = int(datetime.datetime.utcnow().timestamp())
        file_path = dir / f"testcases_{document_id}_{ts}.json"
        file_path.write_text(json.dumps({"testcases": testcases}, indent=2), encoding="utf-8")

        # Determine next testcase_number per document
        last_tc = await db.execute(
            select(Testcases)
            .where(Testcases.document_id == document_id)
            .order_by(Testcases.testcase_number.desc())
            .limit(1)
        )
        last_tc_row = last_tc.scalar_one_or_none()
        next_tc_number = (last_tc_row.testcase_number if last_tc_row else 0) + 1

        # Convert status to string if Enum
        status_str = status.value if hasattr(status, "value") else str(status)

        # Create DB row
        row = Testcases(
            document_id=document_id,
            testcase_number=next_tc_number,
            version=version,
            file_path=str(file_path),
            status=status_str,
            created_at=datetime.datetime.utcnow(),
            changes=None
        )

        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row.id




    def _parse_testcases_from_text(self, text: str) -> List[dict]:
        """
        Try JSON first, fall back to heuristic text parsing.
        Heuristic: look for lines that begin with "Test Case", "TC", or numbered lists.
        Return list of testcases as minimal dicts: {"title": "...", "description": "..."}.
        """
        # 1) try to find JSON block
        try:
            obj = json.loads(text)
            if isinstance(obj, dict) and "testcases" in obj:
                return obj["testcases"]
            if isinstance(obj, list):
                return obj
            # some models return {"testcases": [...]} or nested forms
        except Exception:
            pass

        # 2) fallback: split by lines and capture numbered or "Test Case" entries
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        testcases = []
        cur = None
        for ln in lines:
            m = re.match(r'^(?:\d+\.)\s*(.+)', ln)
            m2 = re.match(r'^(?:Test Case|TC)\s*[:\-]?\s*(.+)', ln, flags=re.I)
            if m or m2:
                title = (m.group(1) if m else m2.group(1)).strip()
                if cur:
                    testcases.append(cur)
                cur = {"title": title, "description": ""}
            else:
                if cur:
                    cur["description"] += (ln + "\n")
                else:
                    # loose lines -> create ad-hoc testcases
                    testcases.append({"title": ln, "description": ""})
        if cur:
            testcases.append(cur)
        return testcases
    
    
    async def chat_update(
    self, db: AsyncSession, document_id: int, request: TestCaseUpdateRequest, commit: bool = False
):
        try:
            # Get latest testcase row
            latest = await self.get_latest_row(db, document_id)
            if not latest:
                raise HTTPException(status_code=404, detail="No testcases generated yet")

            # Load current JSON
            current = json.loads(Path(latest.file_path).read_text(encoding="utf-8"))

            # AI Prompt
            sys = {
                "role": "system",
                "content": (
                    "You are a QA copilot. Update testcases according to the user request. "
                    "Preserve all existing testcases, add new ones if necessary, and modify only requested parts. "
                    "Output strictly valid JSON with { 'testcases': [...] }."
                ),
            }
            usr = {
                "role": "user",
                "content": f"User request: {request.message}\n\nCurrent JSON:\n{json.dumps(current, indent=2)}",
            }

            # Generate updated testcases from AI
            content = await self.ai.chat([sys, usr], provider="groq", response_format_json=True)
            try:
                updated = json.loads(content)
                updated_tcs = updated.get("testcases", [])
            except Exception:
                raise HTTPException(status_code=500, detail="AI returned invalid JSON")

            if not commit:
                # Preview only
                return {"preview": updated_tcs, "count": len(updated_tcs)}

            # Determine next version for this document
            last_version_row = await db.execute(
                select(Testcases)
                .where(Testcases.document_id == document_id)
                .order_by(Testcases.version.desc())
                .limit(1)
            )
            last_version = last_version_row.scalar_one_or_none()
            next_version = (last_version.version if last_version else 0) + 1

            # Save as new version
            new_row_id = await self.write_and_record(
                db, document_id, updated_tcs, status=TestCaseStatus.revised, version=next_version
            )

            return {
                "testcases_id": new_row_id,
                "latest_version" : last_version,
                "version": next_version,
                "testcases": updated_tcs,
                "count": len(updated_tcs),
            }

        except HTTPException as he:
            raise he
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Something went wrong: {e}")



    async def revert(self, db: AsyncSession, document_id: int, to_version: int) -> dict:
        try:
            # Load target version row
            target_row = await db.execute(
                select(Testcases)
                .where(Testcases.document_id == document_id)
                .where(Testcases.version == to_version)
            )
            target = target_row.scalar_one_or_none()
            if not target:
                raise HTTPException(status_code=404, detail=f"Testcases version {to_version} not found")

            # Duplicate as new version
            last_version_row = await db.execute(
                select(Testcases)
                .where(Testcases.document_id == document_id)
                .order_by(Testcases.version.desc())
                .limit(1)
            )
            last_version = last_version_row.scalar_one_or_none()
            next_version = (last_version.version if last_version else 0) + 1

            # Copy file to new version
            file_content = Path(target.file_path).read_text(encoding="utf-8")
            new_row_id = await self.write_and_record(
                db, document_id, json.loads(file_content)["testcases"], status=TestCaseStatus.revised, version=next_version
            )

            return {
                "document_id": document_id,
                "reverted_from_version": to_version,
                "new_version": next_version,
                "testcases_id": new_row_id,
                "status": "reverted"
            }

        except HTTPException as he:
            raise he
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Something went wrong: {e}")



    # ---------- Streaming generation ----------
    # async def generate_testcases_stream(
    #     self, db: AsyncSession, document_id: int, model: str | None = None
    # ):
    #     """
    #     Streams the test case generation using SSE/StreamingResponse.
    #     """
    #     latest_frd = await self.get_latest_frd_version(db, document_id)
    #     if not latest_frd:
    #         raise HTTPException(status_code=404, detail=f"No FRD version found")

    #     text = json.dumps(latest_frd.changes, indent=2)

    #     sys = {
    #         "role": "system",
    #         "content": "You are a QA automation lead. Generate thorough test cases."
    #     }
    #     usr = {
    #         "role": "user",
    #         "content": (
    #             "From the FRD below, produce JSON with: "
    #             "{ \"testcases\": [ {\"id\": str, \"title\": str, \"preconditions\": [str], "
    #             "\"steps\": [str], \"expected\": str, \"priority\": \"P0|P1|P2\"} ] }\n\n"
    #             f"FRD:\n{text}"
    #         )
    #     }

    #     # create a placeholder row for version tracking
    #     placeholder_row_id = await self.write_and_record(
    #         db, document_id, [], status=TestCaseStatus.generated
    #     )

    #     async def event_generator():
    #         async for token in self.ai._groq_chat_stream(
    #             [sys, usr],
    #             model=model or "llama-3.1-8b-instant",
    #             temperature=0.2,
    #             timeout=120,
    #         ):
    #             # yield token incrementally
    #             yield token

    #         yield f"\n\n[Test case generation complete. Version ID: {placeholder_row_id}]\n"

    #     return event_generator()

    def _extract_json_testcases(self, text: str) -> List[dict]:
        """Extract testcases list from JSON string or text."""
        import re
        try:
            obj = json.loads(text)
            if isinstance(obj, dict) and "testcases" in obj:
                return obj["testcases"]
            elif isinstance(obj, list):
                return obj
        except Exception:
            pass

        # fallback find JSON in text
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                obj = json.loads(m.group())
                if "testcases" in obj:
                    return obj["testcases"]
                elif isinstance(obj, list):
                    return obj
            except Exception:
                pass
        return []


    async def generate_testcases_stream(
    self,
    db: AsyncSession,
    document_id: int,
    ai_client: AiClientService,
    content_extractor: ContentExtractionService,
    max_tokens_per_chunk: int = 1800,
):
        """
        Stream testcases per chunk as SSE events,
        optionally including applied fixes from FRD content.
        """
        try:
            # Load document
            doc = await db.get(Documents, document_id)
            if not doc:
                raise HTTPException(status_code=404, detail="Document not found")

            # Load current content including applied fixes if available
            path = Path(doc.file_path)
            if path.exists():
                current_content = await content_extractor.extract_text_content(path.read_bytes(), path.suffix.lower())
            else:
                current_content = ""

            # Split into chunks
            chunks = content_extractor._split_into_token_chunks(
                current_content, max_tokens=max_tokens_per_chunk
            )
            total_chunks = len(chunks)
            aggregated_testcases: list[dict] = []

            async def gen():
                # Initial event
                yield f"data: {json.dumps({'type':'start','document_id':document_id,'total_chunks':total_chunks})}\n\n"

                for i, chunk in enumerate(chunks, start=1):
                    yield f"data: {json.dumps({'type':'chunk_start','chunk':i})}\n\n"

                    # Prepare system/user messages for LLM
                    sys = {
                        "role": "system",
                        "content": (
                            "You are a QA automation lead. Generate thorough test cases. "
                            "Consider applied fixes in FRD content if present. "
                            "Output only JSON like this:\n"
                            "{ \"testcases\": [ {\"id\": \"TC-001\", \"title\": str, \"preconditions\": [str], "
                            "\"steps\": [str], \"expected\": str, \"priority\": \"P0|P1|P2\"} ] }"
                        )
                    }
                    usr = {"role": "user", "content": f"Document chunk {i}/{total_chunks}:\n\n{chunk}"}

                    # Stream AI response
                    stream_gen = await ai_client.stream_chat([sys, usr])

                    chunk_buf = ""
                    async for part in stream_gen:
                        token_piece = part.get("text") if isinstance(part, dict) else str(part)
                        # Stream token by token
                        yield f"data: {json.dumps({'type':'token','chunk':i,'text':token_piece})}\n\n"
                        chunk_buf += token_piece

                    # Parse testcases JSON from chunk buffer
                    testcases = self._parse_testcases_from_text(chunk_buf)

                    # Store in DB
                    new_version_id = await self.write_and_record(
                        db, document_id, testcases, status=TestCaseStatus.generated
                    )
                    aggregated_testcases.extend(testcases)

                    yield f"data: {json.dumps({'type':'chunk_done','chunk':i,'version_id':new_version_id,'testcases_count':len(testcases)})}\n\n"

                # Final event with all aggregated testcases
                final_payload = {
                    'type': 'complete',
                    'document_id': document_id,
                    'total_testcases': len(aggregated_testcases),
                    'testcases': aggregated_testcases
                }
                yield f"data: {json.dumps(final_payload, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"

            return gen()

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Something went wrong in generate_testcases_stream: {e}")

    # --------------------chat update stream-------------------------------------------
    async def chat_update_stream(
    self, db: AsyncSession, document_id: int, request: TestCaseUpdateRequest, model: str | None = None
):
        """
        Streams AI updates to testcases per user request as SSE,
        structured JSON events for easy frontend parsing.
        """
        try:
            latest = await self.get_latest_row(db, document_id)
            if not latest:
                raise HTTPException(status_code=404, detail="No testcases generated yet")

            current = json.loads(Path(latest.file_path).read_text(encoding="utf-8"))

            sys = {
                "role": "system",
                "content": (
                    "You are a QA copilot. Modify ONLY the necessary parts of the testcases per user request. "
                    "Preserve all other testcases unchanged. Output only JSON like this:\n"
                    "{ \"testcases\": [ {\"id\": \"TC-001\", \"title\": str, \"preconditions\": [str], "
                    "\"steps\": [str], \"expected\": str, \"priority\": \"P0|P1|P2\"} ] }"
                ),
            }

            usr = {
                "role": "user",
                "content": f"User request: {request.message}\n\nCurrent JSON:\n{json.dumps(current, indent=2)}",
            }

            async def gen():
                yield f"data: {json.dumps({'type':'start','document_id':document_id,'action':'chat_update'})}\n\n"

                chunk_buf = ""
                async for token in self.ai._groq_chat_stream(
                    [sys, usr],
                    model=model or "llama-3.1-8b-instant",
                    temperature=0.2,
                    timeout=120,
                ):
                    token_piece = token.get("text") if isinstance(token, dict) else str(token)
                    chunk_buf += token_piece
                    # stream token
                    yield f"data: {json.dumps({'type':'token','text':token_piece})}\n\n"

                updated_testcases = self._parse_testcases_from_text(chunk_buf)

                new_version_id = await self.write_and_record(
                    db, document_id, updated_testcases, status=TestCaseStatus.updated
                )

                # Final event
                final_payload = {
                    "type": "complete",
                    "document_id": document_id,
                    "version_id": new_version_id,
                    "total_testcases": len(updated_testcases),
                    "testcases": updated_testcases,
                }
                yield f"data: {json.dumps(final_payload, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"

            return gen()
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Something went wrong in chat_update_stream: {e}")




    # async def revert(self, db: AsyncSession, document_id: int, to_id: int) -> Dict[str, Any]:
    #     target = await db.get(TeseCases, to_id)
    #     if not target or target.frd_id != document_id:
    #         raise HTTPException(status_code=404, detail="Target testcases version not found")
    #     try:
    #         data = json.loads(Path(target.file_path).read_text(encoding="utf-8"))
    #     except Exception:
    #         raise HTTPException(status_code=500, detail="Failed to read target testcases file")
    #     new_row_id = await self.write_and_record(db, document_id, data.get("testcases", []), status=TestCaseStatus.reverted)
    #     return {
    #         "reverted_from": to_id,
    #         "new_version_id": new_row_id,
    #         "count": len(data.get("testcases", [])),
    #         "status": "generated"
    #     }
    async def chat_update_testcase_stream(
        self,
        db: AsyncSession,
        testcase_id: int,
        request: TestCaseChatRequest,
        model: str | None = None
    ):
        # 1. Fetch testcase from DB
        testcase = await db.get(Testcases, testcase_id)
        if not testcase:
            raise HTTPException(status_code=404, detail="Testcase not found")
        
        current_data = json.loads(Path(testcase.file_path).read_text(encoding="utf-8"))

        # 2. Prepare system/user messages for LLM
        sys = {
            "role": "system",
            "content": "You are a QA assistant. Modify only the parts needed according to user instructions. Output strict JSON."
        }
        usr = {
            "role": "user",
            "content": f"User message: {request.message}\nCurrent testcase JSON:\n{json.dumps(current_data, indent=2)}"
        }

        async def gen():
            buf = ""
            async for token in self.ai._groq_chat_stream([sys, usr], model=model or "llama-3.1-8b-instant",
                    temperature=0.2,
                    timeout=120,):
                token_piece = token.get("text") if isinstance(token, dict) else str(token)
                buf += token_piece
                yield f"data: {json.dumps({'type':'token','text':token_piece})}\n\n"

            # parse final JSON
            updated_testcase = self._parse_testcases_from_text(buf)

            # save new version
            new_version_id = await self.write_and_record(
                db, testcase.document_id, updated_testcase, status=TestCaseStatus.updated
            )

            # final payload
            yield f"data: {json.dumps({'type':'complete','version_id':new_version_id,'testcase':updated_testcase})}\n\n"
            yield "data: [DONE]\n\n"

        return gen()