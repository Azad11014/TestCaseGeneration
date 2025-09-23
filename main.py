from app import create_app
import uvicorn
import logging
import sys

# Configure root logger
logging.basicConfig(
    level=logging.INFO,  # Change to DEBUG for more details
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)

logger = logging.getLogger("testgen")


app = create_app()

if __name__=="__main__":
    uvicorn.run(app, host="127.0.0.1", port="8000")