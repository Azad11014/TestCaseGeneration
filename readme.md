# Project Documentation and Test Case Management System

This project is a FastAPI-based application designed to manage projects, documents (BRD and FRD), and test cases with AI-powered analysis, conversion, and generation capabilities. It provides a robust system for uploading, analyzing, and versioning Business Requirement Documents (BRDs) and Functional Requirement Documents (FRDs), generating test cases, and refining them through AI-driven workflows. The system uses PostgreSQL/Neon for metadata storage, a file system for storing generated JSON files, and Server-Sent Events (SSE) for real-time AI output streaming.

## Table of Contents
1. [Overview](#overview)
2. [Database Models](#database-models)
3. [FastAPI Application Setup](#fastapi-application-setup)
4. [Workflows](#workflows)
   - [BRD to FRD Flow](#brd-to-frd-flow)
   - [FRD Flow](#frd-flow)
5. [Streaming APIs](#streaming-apis)
6. [Services](#services)
   - [ContentExtractionService](#contentextractionservice)
   - [DocumentUploadService](#documentuploadservice)
   - [TestGenServices](#testgenservices)
7. [Persistence](#persistence)
8. [API Endpoints](#api-endpoints)
   - [Default Routes](#default-routes)
   - [Upload Document](#upload-document)
   - [Projects](#projects)
   - [Test Cases](#test-cases)
   - [Content Extraction](#content-extraction)
   - [FRD Flow](#frd-flow)
   - [BRD Flow](#brd-flow)
9. [Usage Examples](#usage-examples)
10. [Setup and Installation](#setup-and-installation)
    - [Prerequisites](#prerequisites)
    - [Installation Steps](#installation-steps)
    - [Directory Structure](#directory-structure)
11. [Dependencies](#dependencies)

## Overview
The system allows users to:
- Upload BRD/FRD documents to projects.
- Analyze documents for anomalies using AI.
- Convert BRDs to FRDs with version tracking.
- Generate and refine test cases based on FRDs.
- Propose and apply fixes to detected anomalies.
- Revert changes to previous versions.
- Stream AI outputs in real-time for a smooth user experience.

All operations are versioned and reversible, with metadata stored in a PostgreSQL/Neon database and generated files (BRD, FRD, test cases) stored on the file system.

## Database Models
The application uses SQLAlchemy ORM to define the following relational schema:
- **Projects**: Represents a project that groups documents.
- **Documents**: Represents BRD or FRD documents within a project. Each document has a `doctype` (BRD or FRD) and a sequential `doc_number` per project.
- **FRDVersions**: Tracks changes and versions of FRD documents.
- **BRDToFRDVersions**: Manages mappings and conversions from BRD to FRD.
- **Testcases**: Stores test cases linked to documents (primarily FRDs), with support for multiple versions.

### Hierarchy
```
Project → Documents (BRD/FRD) → FRD Versions + Test Cases
```

## FastAPI Application Setup
The FastAPI application (`main.py`) is the core of the system, registering routers for:
- Uploads
- Project management
- BRD workflow
- FRD workflow
- Test case management
- Streaming routes (SSE for AI generation)

### Features
- **CORS Middleware**: Configured to allow cross-origin requests.
- **Latency Metrics**: Tracks request latency with percentiles for performance monitoring.

## Workflows
The system supports two primary workflows: BRD to FRD Flow and FRD Flow.

### BRD to FRD Flow
1. **Convert BRD to FRD** (`POST /project/{project_id}/document/{document_id}/convert`):
   - Uses `BRDAgentService.brd_to_frd()` to generate an FRD JSON.
   - Saves the result in `Documents` and `BRDToFRDVersions`.
2. **Analyze BRD/FRD** (`POST /project/{project_id}/document/{document_id}/bfrd/analyze`):
   - Performs AI-driven anomaly detection.
3. **Propose Fix** (`POST /project/{project_id}/document/{document_id}/brd/propose-fix`):
   - Users select issues, and AI suggests fixes stored in version history.
4. **Apply Fix** (`POST /project/{project_id}/document/{document_id}/brd/apply-fix/{version_id}`):
   - Applies selected fixes to the FRD.
5. **Generate Test Cases** (`POST /project/{project_id}/document/{document_id}/testcases/generate`):
   - Generates test case JSON files based on the FRD.
6. **Update Test Cases (Chat-style)** (`POST /project/{project_id}/document/{document_id}/testcases/update`):
   - Allows users to revise test cases interactively with AI.

### FRD Flow
1. **Analyze FRD** (`POST /project/{project_id}/document/{document_id}/analyze`):
   - Uses map-reduce style AI analysis to detect anomalies.
2. **Propose Fixes** (`POST /project/{project_id}/documents/{document_id}/frd/propose-fix`):
   - Users select anomaly IDs, and AI generates fixes.
3. **Apply Fix** (`POST /project/{project_id}/documents/{document_id}/frd/apply-fix`):
   - Commits fixes to the FRD version history.
4. **Generate Test Cases** (`POST /project/{project_id}/documents/{document_id}/testcases/generate`):
   - Produces structured test case JSON files.
5. **Chat Update Test Cases** (`POST /project/{project_id}/documents/{document_id}/testcases/chat`):
   - Enables real-time test case refinement with AI.
6. **Revert (FRD or Test Cases)**:
   - Rolls back to a previous version using `version_id`.

## Streaming APIs
For long-running AI tasks, the system uses Server-Sent Events (SSE) to stream outputs token-by-token, enabling real-time updates on the frontend:
- FRD analysis stream
- FRD test case generation stream
- BRD to FRD conversion stream
- BRD propose-fix stream
- Test case chat update stream

## Services
The application delegates heavy processing to service classes, which handle AI interactions, version management, JSON diffs, and test case generation.

### ContentExtractionService
Extracts text from various file formats (PDF, DOCX, TXT, JSON) for AI processing.

- **Key Methods**:
  - `extract_document_text(db, project_id, document_id)`: Fetches a document and extracts its text, returning metadata and a preview.
  - `extract_text_content(content, extension)`: Detects file type and extracts text using appropriate methods (e.g., PyMuPDF for PDFs, python-docx for DOCX).
  - `_split_into_token_chunks(text, max_tokens, overlap_tokens)`: Splits text into token-based chunks for AI processing, with overlap to maintain context.
  - `count_tokens(text, model_name)`: Counts tokens for a given text using tiktoken or a fallback estimate.
  - `truncate_to_tokens(text, max_tokens)`: Truncates text to fit within a token limit.
  - `test_text_extraction_and_chunking(db, project_id, document_id)`: Utility function for debugging text extraction and chunking.

### DocumentUploadService
Handles file uploads and validation, ensuring files meet size and format requirements.

- **Key Methods**:
  - `validate_files(file, document_type)`: Validates file extension, size, and MIME type.
  - `upload_document(project_id, file, doctype, db)`: Uploads a document, assigns a sequential `doc_number`, and saves it to the file system and database.

### TestGenServices
Manages test case generation, updates, and reversion using AI.

- **Key Methods**:
  - `get_latest_frd_version(db, document_id)`: Retrieves the latest FRD version, prioritizing versions with applied fixes.
  - `generate_testcases(db, document_id)`: Generates test cases from the latest FRD using AI, saving them to the file system and database.
  - `write_and_record(db, document_id, testcases, status, version)`: Persists test cases to disk and creates a `Testcases` database row.
  - `chat_update(db, document_id, request, commit)`: Updates test cases based on user input via AI, with an option to preview or commit.
  - `revert(db, document_id, to_version)`: Reverts test cases to a specified version.
  - `generate_testcases_stream(db, document_id, ai_client, content_extractor)`: Streams test case generation for large documents, processing them in chunks.
  - `chat_update_stream(db, document_id, request)`: Streams test case updates in real-time using SSE.

## Persistence
- **Database (PostgreSQL/Neon)**: Stores metadata, version history, anomalies, and mappings.
- **File System**: Stores generated JSON files for BRDs, FRDs, and test cases, referenced by `file_path` in the database.

## API Endpoints
The application exposes a comprehensive set of RESTful and streaming APIs.

### Default Routes
- `GET /`: Home endpoint.
- `GET /metrics`: Retrieve request latency metrics.
- `GET /metrics/percentiles`: Retrieve latency percentiles.

### Upload Document
- `POST /api/v1/project/{project_id}/upload`: Upload a BRD or FRD document to a project.

### Projects
- `POST /api/v1/project/create`: Create a new project.
- `GET /api/v1/project/projects/{project_id}`: Retrieve a specific project.
- `GET /api/v1/project/projects`: List all projects.

### Test Cases
- `GET /api/v1/{project_id}/testcases`: List test cases for a project.
- `GET /api/v1/testcases/{document_id}/versions`: Retrieve test case versions for a document.
- `GET /api/v1/testcases/{testcase_id}/preview`: Preview a test case JSON.
- `GET /api/v1/project/{project_id}/document/{document_id}/testcases`: List test cases for a specific document.

### Content Extraction
- `GET /api/v1/project/{project_id}/documents/{document_id}/extract`: Extract text from a document.

### FRD Flow
- `POST /api/v1/project/{project_id}/document/{document_id}/analyze`: Analyze an FRD for anomalies.
- `POST /api/v1/project/{project_id}/documents/{document_id}/frd/propose-fix`: Propose fixes for selected anomalies.
- `POST /api/v1/project/{project_id}/documents/{document_id}/frd/apply-fix`: Apply fixes to an FRD.
- `POST /api/v1/project/{project_id}/documents/{document_id}/testcases/generate`: Generate test cases for an FRD.
- `POST /api/v1/project/{project_id}/documents/{document_id}/testcases/chat`: Update test cases interactively.
- `POST /api/v1/project/{project_id}/documents/{document_id}/frd/revert`: Revert an FRD to a previous version.
- `POST /api/v1/project/{project_id}/documents/{document_id}/testcases/revert`: Revert test cases to a previous version.

### BRD Flow
- `POST /api/v1/project/{project_id}/document/{document_id}/convert`: Convert a BRD to an FRD.
- `POST /api/v1/project/{project_id}/document/{document_id}/bfrd/analyze`: Analyze a BRD or FRD for anomalies.
- `POST /api/v1/project/{project_id}/document/{document_id}/brd/propose-fix`: Propose fixes for a BRD.
- `POST /api/v1/project/{project_id}/document/{document_id}/brd/apply-fix/{version_id}`: Apply fixes to a BRD-derived FRD.
- `POST /api/v1/project/{project_id}/document/{document_id}/testcases/generate`: Generate test cases for a BRD-derived FRD.
- `POST /api/v1/project/{project_id}/document/{document_id}/testcases/update`: Update test cases for a BRD-derived FRD.
- `POST /api/v1/project/{project_id}/document/{document_id}/revert/{version_id}`: Revert a BRD or FRD to a previous version.

## Usage Examples
Below are example API calls using `curl` to demonstrate key functionalities.

### Create a Project
```bash
curl -X POST "http://localhost:8000/api/v1/project/create" \
-H "Content-Type: application/json" \
-d '{"name": "New Project", "description": "A sample project"}'
```

### Upload a Document
```bash
curl -X POST "http://localhost:8000/api/v1/project/1/upload" \
-F "file=@sample_brd.pdf" \
-F "doctype=BRD"
```

### Convert BRD to FRD
```bash
curl -X POST "http://localhost:8000/api/v1/project/1/document/1/convert" \
-H "Content-Type: application/json"
```

### Analyze FRD
```bash
curl -X POST "http://localhost:8000/api/v1/project/1/document/1/analyze" \
-H "Content-Type: application/json"
```

### Generate Test Cases
```bash
curl -X POST "http://localhost:8000/api/v1/project/1/documents/1/testcases/generate" \
-H "Content-Type: application/json"
```

### Chat Update Test Cases
```bash
curl -X POST "http://localhost:8000/api/v1/project/1/documents/1/testcases/chat" \
-H "Content-Type: application/json" \
-d '{"message": "Add a test case for user login validation"}'
```

### Stream Test Case Generation
```bash
curl -X POST "http://localhost:8000/api/v1/project/1/documents/1/testcases/generate" \
-H "Accept: text/event-stream"
```

### Revert Test Cases
```bash
curl -X POST "http://localhost:8000/api/v1/project/1/documents/1/testcases/revert" \
-H "Content-Type: application/json" \
-d '{"to_version": 1}'
```

## Setup and Installation

### Prerequisites
- **Python**: Version 3.9 or higher.
- **PostgreSQL**: Version 14 or higher, or a Neon database instance.
- **Git**: For cloning the repository.
- **pip**: For installing Python dependencies.
- **Alembic**: For database migrations.
- **System Dependencies** (for PyMuPDF and other libraries):
  - On Ubuntu/Debian: `sudo apt-get install libmupdf-dev libfreetype6-dev libjpeg-dev zlib1g-dev`
  - On macOS: `brew install mupdf freetype libjpeg zlib`

### Installation Steps
1. **Clone the Repository**:
   ```bash
   git clone <repository_url>
   cd <repository_name>
   ```

2. **Create a Virtual Environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install Dependencies**:
   Create a `requirements.txt` file with the provided dependencies and run:
   ```bash
   pip install -r requirements.txt
   ```

4. **Set Up Environment Variables**:
   Create a `.env` file in the project root with the following:
   ```plaintext
   DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/dbname
   MODEL_NAME=llama-3.1-8b-instant
   UPLOAD_DIR=data
   ```
   Replace `user`, `password`, and `dbname` with your PostgreSQL credentials and database name. For Neon, use the connection string provided by the Neon dashboard.

5. **Set Up the Database**:
   Ensure PostgreSQL or Neon is running. Create a database if using local PostgreSQL:
   ```bash
   createdb <dbname>
   ```

6. **Run Database Migrations**:
   Initialize Alembic (if not already set up) and apply migrations:
   ```bash
   alembic init migrations
   alembic revision --autogenerate -m "Initial migration"
   alembic upgrade head
   ```

7. **Start the FastAPI Server**:
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8000
   ```

8. **Verify the Application**:
   Open a browser or use `curl` to access `http://localhost:8000` to ensure the server is running.


## Dependencies
The following Python packages are required (as specified):

- alembic==1.16.5
- annotated-types==0.7.0
- anyio==4.10.0
- async-timeout==5.0.1
- asyncpg==0.30.0
- certifi==2025.8.3
- charset-normalizer==3.4.3
- click==8.2.1
- colorama==0.4.6
- docx==0.2.4
- exceptiongroup==1.3.0
- fastapi==0.116.1
- greenlet==3.2.4
- h11==0.16.0
- httpcore==1.0.9
- httpx==0.28.1
- idna==3.10
- lxml==6.0.1
- Mako==1.3.10
- MarkupSafe==3.0.2
- numpy==2.2.6
- pillow==11.3.0
- psycopg2==2.9.10
- psycopg2-binary==2.9.10
- pydantic==2.11.7
- pydantic_core==2.33.2
- PyMuPDF==1.26.4
- python-docx==1.2.0
- python-dotenv==1.1.1
- python-multipart==0.0.20
- regex==2025.9.1
- requests==2.32.5
- sniffio==1.3.1
- SQLAlchemy==2.0.43
- starlette==0.47.3
- tiktoken==0.11.0
- tomli==2.2.1
- typing-inspection==0.4.1
- typing_extensions==4.15.0
- urllib3==2.5.0
- uvicorn==0.35.0

These dependencies support the application's core functionality, including web server operations, database connectivity, file processing, and AI interactions.

This README provides a comprehensive guide to the system, its services, API usage, and setup instructions. For further details, refer to the source code or contact the development team.