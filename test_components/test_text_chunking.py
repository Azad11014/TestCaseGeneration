import asyncio
from database.database_connection import async_session
from app.services.content_extraction_service import ContentExtractionService
import asyncio
import sys

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def run_test():
    async with async_session() as db:
        service = ContentExtractionService()
        chunks = await service.test_text_extraction_and_chunking(
            db=db,
            project_id=1,   # replace with real project_id
            document_id=1,  # replace with real document_id
            max_tokens=500  # small chunks for demo
        )
        # print("\n[FINAL RESULT] Number of chunks:", len(chunks))
        print(chunks)

if __name__ == "__main__":
    asyncio.run(run_test())
