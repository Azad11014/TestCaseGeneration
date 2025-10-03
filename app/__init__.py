from fastapi import FastAPI, HTTPException, Depends, Request
import time
import numpy as np

from fastapi.middleware.cors import CORSMiddleware

from app.routes.project_routes import project_router
from app.routes.upload_router import upload_router
from app.routes.text_extraction_route import extraction_router

from logs.logger_config  import get_logger
from colorama import Fore, Style, init

logger = get_logger("MainAppInitialization")

def calculate_percentiles(data):
    if not data:
        return {}
    # Extract only the "time" values if data is a list of dicts
    if isinstance(data[0], dict):
        values = [d["time"] for d in data]
    else:
        values = data

    return {
        "p50": float(np.percentile(values, 50)),
        "p90": float(np.percentile(values, 90)),
        "p95": float(np.percentile(values, 95)),
        "p99": float(np.percentile(values, 99)),
    }
def create_app():

    app = FastAPI()

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    api_prefix = "/api/v1"

    @app.get("/")
    def home():
        try:
            return {"message" : "This is Home. Home is safe..."}
        except HTTPException as he:
            raise HTTPException(status_code=500, detail=f"Home is broken : {he}")
        
    timings = []

    @app.middleware("http")
    async def add_timing(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start
        timings.append({"path": request.url.path, "time": duration})
        return response
    
    api_timings = []

    @app.middleware("http")
    async def add_timing(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start
        api_timings.append(duration)  # store only float
        return response


    @app.get("/metrics")
    async def get_metrics():
        return timings
    
    @app.get("/metrics/percentiles")
    async def get_percentiles():
        result = calculate_percentiles(api_timings)
        return {"count": len(api_timings), "percentiles": result}
    
    app.include_router(project_router, prefix=f"{api_prefix}/project", tags=["Project"])
    app.include_router(upload_router, prefix=f"{api_prefix}/project", tags=["Document Upload"])
    app.include_router(extraction_router, prefix=f"{api_prefix}/project", tags=["Text Extraction"])
    
    return app
