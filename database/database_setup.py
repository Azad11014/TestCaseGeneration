"""
Database setup and initialization script
Run this file once to create all tables in your Neon database
"""

from sqlalchemy import create_engine
from app.models.models import Base
from config.config import DATABASE_URL
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_tables():
    """Create all tables in the database"""
    try:
        # Convert async URL to sync URL for table creation
        sync_url = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
        
        # Create sync engine for table creation
        engine = create_engine(sync_url, echo=True)
        
        # Create all tables
        logger.info("Creating database tables...")
        Base.metadata.create_all(bind=engine)
        logger.info("All tables created successfully!")
        
        # Close the engine
        engine.dispose()
        
    except Exception as e:
        logger.error(f"Error creating tables: {e}")
        raise

if __name__ == "__main__":
    create_tables()