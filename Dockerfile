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

# api/app.py does `from db import get_db` (a plain top-level import, same
# as running `python app.py` locally from inside api/ - see that file's
# own __main__ comment) - it only resolves if the process's working
# directory is api/ itself, since that's what puts db.py on sys.path.
# Running gunicorn as "api.app:app" from /app does NOT do that (db.py
# sits one level down, invisible to the api.app submodule's plain
# `import db`) - confirmed live, ModuleNotFoundError: No module named 'db'.
WORKDIR /app/api

# Render sets $PORT at runtime; the shell form of CMD is required for the
# $PORT expansion to actually happen (the exec form would pass the literal
# string "$PORT" to gunicorn instead of substituting it).
CMD gunicorn app:app --bind 0.0.0.0:$PORT
