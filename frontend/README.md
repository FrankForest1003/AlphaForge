# AlphaForge Arena Frontend v2.0

This Streamlit prototype implements the fair-battle product flow defined in
`AlphaForge_团队同步与AI开发上下文_v2.0.md`.

## Local run (Windows)

```powershell
conda activate alphaforge-frontend
cd frontend
python -m pip install -r requirements.txt
$env:ALPHAFORGE_MOCK_MODE = "false"
$env:ALPHAFORGE_API_BASE_URL = "http://127.0.0.1:8000/v1"
python -m streamlit run app.py
```

## Docker demo

```powershell
cd frontend
docker build -t alphaforge-frontend:v2 .
docker run --rm -p 8501:8501 -e ALPHAFORGE_MOCK_MODE=true alphaforge-frontend:v2
```

Open <http://localhost:8501>.

## Backend integration

The page layer never calls FastAPI directly. Add real methods in
`api_client/client.py`, then start with:

```powershell
$env:ALPHAFORGE_MOCK_MODE = "false"
$env:ALPHAFORGE_API_BASE_URL = "http://127.0.0.1:8000/v1"
python -m streamlit run app.py
```

Live mode is the default and never falls back to fabricated metrics. Set
`ALPHAFORGE_MOCK_MODE=true` only for the explicitly labelled UI demo.

