# syntax=docker/dockerfile:1

# ---- Base image ----
# python:3.12-slim is small and well-supported. (Note: slim no longer bundles
# setuptools — we don't need it here since we have no pkg_resources imports.)
FROM python:3.12-slim

# Don't buffer stdout/stderr (so logs show up immediately in `kubectl logs`),
# and don't write .pyc files into the image layer.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install deps first (separate layer) so code changes don't bust the pip cache.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application source.
COPY src ./src

# Run as a non-root user — least privilege for a pod that can delete pods.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin appuser
USER 10001

EXPOSE 8080

# Serve the ASGI app. 0.0.0.0 so it's reachable from the cluster network.
CMD ["uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8080"]
