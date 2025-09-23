from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
import asyncio

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from config.config import DATABASE_URL

db = DATABASE_URL

async def check_connection():
    try:
        engine = create_engine(db)
        with engine.connect() as connection:
            result = connection.execute(text('SELECT 1'))
            print(f"DB Connected successfully : {result.scalar()}")
    except OperationalError as e:
        print(f"DB connection Failed : {e}")

# Run the function
if __name__ == "__main__":
    asyncio.run(check_connection())