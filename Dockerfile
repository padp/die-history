# Builds the cloud/ Mongo-backed API + frontend. Root of the build context
# is the repo root (not cloud/) so this Dockerfile works regardless of
# whether the Render service has a Root Directory set - point Render at
# this file with an empty/unset Root Directory and Dockerfile Path
# "Dockerfile", and it just works.
FROM python:3.12-slim

WORKDIR /app

COPY cloud/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY cloud/ .

# Render sets $PORT at runtime; the shell form of CMD is required for the
# $PORT expansion to actually happen (the exec form would pass the literal
# string "$PORT" to gunicorn instead of substituting it).
CMD gunicorn api.app:app --bind 0.0.0.0:$PORT
