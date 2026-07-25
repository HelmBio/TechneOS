#!/bin/sh
# techneos/tool-runtime unified entrypoint.
#
# Two modes, selected by env — no command override needed, so it behaves the
# same on the Docker and AWS Batch backends:
#   - pypi tool:      the worker sets TECHNEOS_INSTALL_PACKAGE (+ optional
#                     TECHNEOS_INSTALL_INDEX_URL / TECHNEOS_INSTALL_TRUSTED_HOST); we
#                     pip-install it at dispatch, then run the runner.
#   - container tool: no TECHNEOS_INSTALL_* is set; we go straight to the runner,
#                     which reads ENTRYPOINT_SPEC from the env baked into the
#                     tool image.
#
# When a private index (CodeArtifact / DevPI) is used as --index-url,
# PyPI is added as --extra-index-url so transitive deps not in the
# private index (e.g. rdkit-pypi) can still resolve.
set -e

if [ -n "${TECHNEOS_INSTALL_PACKAGE:-}" ]; then
    pip install --quiet --cache-dir "${TECHNEOS_PIP_CACHE_DIR:-/tmp/techneos-pip-cache}" \
        ${TECHNEOS_INSTALL_INDEX_URL:+--index-url "${TECHNEOS_INSTALL_INDEX_URL}"} \
        ${TECHNEOS_INSTALL_TRUSTED_HOST:+--trusted-host "${TECHNEOS_INSTALL_TRUSTED_HOST}"} \
        ${TECHNEOS_INSTALL_INDEX_URL:+--extra-index-url https://pypi.org/simple/} \
        "${TECHNEOS_INSTALL_PACKAGE}"
fi

exec python -m techneos_tool_runtime.runner "$@"
