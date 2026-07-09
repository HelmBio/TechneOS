# techneos/tool-runtime — the single execution image for TechneOS tools.
#
# Used two ways:
#   1. The Airflow worker runs it for **pypi**-type tools: at dispatch it
#      pip-installs the tool package (which declares its own heavy deps —
#      rdkit, numpy, …) then invokes the generic runner.
#   2. **container**-type tools build `FROM` it, install their own system/python
#      deps, and set ENTRYPOINT_SPEC; the runner ENTRYPOINT is inherited.
#
# Deliberately slim: python + the zero-dependency techneos-tool-runtime + the runner.
# Heavy scientific stacks are NOT baked in — each tool brings what it needs.
#
# Build context is THIS package directory, so the source is copied and installed
# directly (no runtime-src staging). Downstream tools pin a version, never
# `latest` — keep docker images reproducible.

# ─── Stage 1: build the techneos-tool-runtime wheel ────────────────────────
FROM python:3.12-slim AS builder
RUN pip install --no-cache-dir --upgrade build
WORKDIR /src
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN python -m build --wheel --outdir /dist

# ─── Stage 2: runtime image ───────────────────────────────────────────
FROM python:3.12-slim

LABEL org.opencontainers.image.title="techneos-tool-runtime"
LABEL org.opencontainers.image.description="TechneOS tool execution runtime — worker dispatch image and container-tool base"

# Minimal native libs that the common scientific pip wheels dlopen but don't
# bundle: RDKit's Cairo drawing path (rdkit.Chem.Draw) needs libXrender/libXext.
# pypi tools have no Dockerfile of their own, so these must live in the shared
# base; tool-specific heavy libs (e.g. weasyprint's pango/cairo, vina binaries)
# stay in the individual container tools.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxrender1 \
    libxext6 \
    libfontconfig1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl

# Unified entrypoint: pip-installs a pypi tool from TECHNEOS_INSTALL_* env (if set),
# then runs the runner. Container tools inherit it and just set ENTRYPOINT_SPEC.
COPY entrypoint.sh /usr/local/bin/techneos-entrypoint
RUN chmod +x /usr/local/bin/techneos-entrypoint

# Standard working directory — the worker bind-mounts the host work dir here.
ENV TECHNEOS_WORK_DIR=/work
RUN mkdir -p /work/input /work/output
WORKDIR /work

ENTRYPOINT ["/usr/local/bin/techneos-entrypoint"]
