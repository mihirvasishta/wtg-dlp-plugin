FROM python:3.11-slim

WORKDIR /app

# Install dependencies first — separate layer so rebuilds are fast
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy everything else
COPY . .

# Azure Container Apps: set target-port=8443 in ingress config.
# PORT env var is read by config.py; default 8443 is used unless overridden.
ENV PORT=8443

EXPOSE ${PORT}

# Run from backend/ so all relative imports resolve correctly
CMD ["sh", "-c", "cd backend && uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
