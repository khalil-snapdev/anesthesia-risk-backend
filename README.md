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

4. Run the development server:

   ```bash
   uvicorn app.main:app --reload
   ```

The API will be available at `http://localhost:8000`. Check `http://localhost:8000/health`.

## Running Tests

```bash
pytest
```

## Project Status

Currently on **Step 1.3 — core models (User, Patient)**. This project is
being built in small, reviewed phases — see `CLAUDE.md` for the full
roadmap and current phase.
