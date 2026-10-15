# syntax=docker/dockerfile:1
#
# CleanSlate API container
#
# Stages:
#   lock    - resolves and freezes runtime dependencies into requirements.lock.txt
#   tools   - installs ExifTool (from the official distribution, checksum-pinned)
#             and qpdf on top of a Debian-based Python base
#   base    - runtime dependencies + application code
#   test    - base + dev dependencies, runs the pytest suite (build fails on failure)
#   runtime - non-root runtime image (default build target)
#
# Shell access inside this image is not needed at runtime; the entrypoint is
# uvicorn only, and the process runs as uid 10001.

ARG PYTHON_IMAGE=python:3.12-slim-trixie

# --------------------------------------------------------------------------- #
# lock: freeze runtime dependencies (run `scripts/pin-deps.sh` to refresh)
# --------------------------------------------------------------------------- #
FROM ${PYTHON_IMAGE} AS lock
WORKDIR /lock
COPY requirements.in ./
RUN pip install --no-cache-dir --upgrade pip >/dev/null \
 && pip install --no-cache-dir -r requirements.in >/dev/null \
 && pip freeze --exclude-editable > /tmp/requirements.lock.txt \
 && cat /tmp/requirements.lock.txt

# --------------------------------------------------------------------------- #
# tools: ExifTool + qpdf
# --------------------------------------------------------------------------- #
FROM ${PYTHON_IMAGE} AS tools
ARG EXIFTOOL_VERSION=13.59
ARG EXIFTOOL_SHA256=668ea3acececb7235fbd0f4900e72d5f12c9b07e5c778fd36cb1e9b5828fd65a
ENV DEBIAN_FRONTEND=noninteractive
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl perl make qpdf; \
    curl -fsSL -o /tmp/exiftool.tar.gz \
      "https://sourceforge.net/projects/exiftool/files/Image-ExifTool-${EXIFTOOL_VERSION}.tar.gz/download"; \
    echo "${EXIFTOOL_SHA256}  /tmp/exiftool.tar.gz" | sha256sum -c -; \
    tar -xzf /tmp/exiftool.tar.gz -C /tmp; \
    cd "/tmp/Image-ExifTool-${EXIFTOOL_VERSION}"; \
    perl Makefile.PL >/dev/null; \
    make -s install; \
    rm -rf "/tmp/Image-ExifTool-${EXIFTOOL_VERSION}" /tmp/exiftool.tar.gz; \
    apt-get purge -y --auto-remove make curl; \
    rm -rf /var/lib/apt/lists/*; \
    exiftool -ver; \
    qpdf --version

# --------------------------------------------------------------------------- #
# base: application + runtime dependencies
# --------------------------------------------------------------------------- #
FROM tools AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY app ./app
COPY pytest.ini ./

# --------------------------------------------------------------------------- #
# test: full pytest suite (fixtures are generated with real tools + Pillow)
# --------------------------------------------------------------------------- #
FROM base AS test
COPY requirements-dev.in ./
RUN pip install --no-cache-dir -r requirements-dev.in
COPY tests ./tests
RUN python -m pytest -q

# --------------------------------------------------------------------------- #
# runtime: non-root, no shell tooling needed
# --------------------------------------------------------------------------- #
FROM base AS runtime
RUN useradd --system --uid 10001 --home-dir /home/clean --create-home \
      --shell /usr/sbin/nologin clean \
 && mkdir -p /tmp/cleanslate-jobs \
 && chown -R clean:clean /home/clean /tmp/cleanslate-jobs
USER 10001
ENV HOME=/home/clean \
    TEMP_ROOT=/tmp/cleanslate-jobs \
    PORT=8787 \
    ENVIRONMENT=production \
    EXPOSE_API_DOCS=false \
    TRUST_PROXY_HEADERS=false \
    ENABLE_HSTS=true
EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import os,sys,urllib.request; \
url='http://127.0.0.1:'+os.environ.get('PORT','8787')+'/api/health'; \
sys.exit(0 if urllib.request.urlopen(url, timeout=4).status==200 else 1)"
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8787} --workers 1 --no-server-header --log-level info"]
