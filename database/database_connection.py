import ssl
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from config.config import DATABASE_URL


# Create SSL context for asyncpg
ssl_context = ssl.create_default_context()
#Create Engine
engine = create_async_engine(DATABASE_URL, echo=True,connect_args={"ssl": ssl_context} ) # this replaces the need for `sslmode`)


async_session = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

async def get_db():
    async with async_session() as session:
        print(session)
        yield session


# import asyncio

# if __name__ == "__main__":
#     async def test_db():
#         async for session in get_db():
#             print(session)

#     asyncio.run(test_db())