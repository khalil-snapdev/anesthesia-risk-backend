# Anesthesia Risk Score 2.0 — Backend

Backend API for an outpatient oral & maxillofacial surgery anesthesia risk
assessment dashboard. Built with Python, FastAPI, and MongoDB Atlas (via
Beanie ODM).

## Setup

1. Create and activate a virtual environment:

   ```bash
   python -m venv venv
   source venv/bin/activate  # Windows: venv\Scripts\activate
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements-dev.txt
   ```

3. Copy the example environment file and fill in values:

   ```bash
   cp .env.example .env
   ```

4. Install the pre-commit hooks (runs ruff, black, and mypy on every commit):

   ```bash
   pre-commit install
   ```

5. Run the development server:

   ```bash
   uvicorn app.main:app --reload
   ```

The API will be available at `http://localhost:8000`. Check `http://localhost:8000/health`.

## Running Tests

```bash
pytest
```

Coverage is enforced at 80% (`pytest` fails below that threshold).

## Type Checking, Linting, and Security Audit

```bash
mypy app tests
ruff check .
black --check .
pip-audit
```

## Docker

```bash
docker build -t anesthesia-risk-backend .
docker run -p 8000:8000 --env-file .env anesthesia-risk-backend
```

## Project Status

Phase 1 (data model layer), Phase 2 (scoring engine), Phase 3 (API
routes), Phase 5 (Truform ingestion parser), Phase 6 (Google auth +
role-based access), Phase 7 (PDF exports), and Phase 8 (audit logging
completion pass) are complete. Phase 4 (recommendations & alerts) was
already covered by Phase 2's services and Phase 3's routes, so it's
deferred/merged. **Backend feature-complete — next: deploy to Render,
then connect the Ember frontend to the real API.** This project was
built in small, reviewed phases — see `CLAUDE.md` for the full roadmap
and phase-by-phase history.
