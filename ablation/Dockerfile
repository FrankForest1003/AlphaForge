FROM alphaforge-backend:latest

WORKDIR /workspace
COPY agent /workspace/agent
COPY backend/app /workspace/backend/app
COPY ablation /workspace/ablation

ENV PYTHONPATH=/workspace:/workspace/backend
ENTRYPOINT ["python", "-m", "ablation"]
