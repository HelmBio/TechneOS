"""Input normalization — resolves dataset references into inline values.

Flow
----
Before a tool operator receives step parameters, the orchestrator
normalises them so that dataset references like ``pubchem-peptides:v3``
are replaced with the actual data from the file (e.g. a list of SMILES
strings).  The ``resolve_and_inline_params`` function performs this
normalisation given a callback that resolves a reference string to
MinIO storage info.

Usage
-----
.. code-block:: python

    async def resolve_ref(ref: str) -> dict[str, str] | None:
        # e.g. query database for Dataset + DatasetVersion
        ...

    params = await resolve_and_inline_params(
        {"smiles": "pubchem-peptides:v3"},
        resolve_ref=resolve_ref,
    )
    # params == {"smiles": ["CCCO", "c1ccccc1", ...]}
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from core.storage import get_object_store

logger = logging.getLogger(__name__)

_DATASET_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*:v\d+$")


def looks_like_storage_ref(value: str) -> bool:
    """Does *value* look like a dataset reference (``slug:v<N>``) or upload reference (``upload:<id>``)?"""
    if not isinstance(value, str):
        return False
    if value.startswith("upload:"):
        return True
    return bool(_DATASET_REF_RE.match(value))


def inline_dataset_values(data: bytes, file_name: str) -> list[str] | None:
    """Read CSV/TSV bytes and return the SMILES column as a list.

    Heuristics in order:
      1. If the file has a header row with a column named ``SMILES``
         (case-insensitive), extract that column.
      2. Otherwise use the first column from data rows (skip header).
      3. On parse failure, return *None*.

    Note
    ----
    This is the pipeline-orchestrator path; it returns plain SMILES
    strings (the pipeline framework's contract pre-dates per-row IDs).
    Tools running inside containers go through
    :mod:`techneos_tool_runtime.parsers` instead, which returns ``list[dict]``
    rows of ``{"smiles", "id"?}``. The two implementations track the
    same column heuristic intentionally — keep them in sync if you tweak
    one.
    """
    delimiter = "\t" if file_name.endswith(".tsv") else ","
    try:
        text = data.decode("utf-8")
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        rows = list(reader)
    except Exception:
        logger.exception("Failed to parse dataset file %s", file_name)
        return None

    if not rows:
        return None

    header = rows[0]
    smiles_idx: int | None = None
    for i, col in enumerate(header):
        if col.strip().lower() == "smiles":
            smiles_idx = i
            break

    if smiles_idx is not None:
        values = [row[smiles_idx].strip() for row in rows[1:] if len(row) > smiles_idx]
    elif len(rows) > 1:
        values = [row[0].strip() for row in rows[1:] if row]
    else:
        values = [row[0].strip() for row in rows if row]

    return [v for v in values if v]


async def resolve_and_inline_params(
    params: dict[str, Any],
    resolve_ref: Callable[[str], Awaitable[dict[str, str] | None]],
) -> dict[str, Any]:
    """Return a new params dict with dataset/upload references replaced by inline values.

    Parameters
    ----------
    params:
        Raw parameters (e.g. ``{"smiles": "pubchem-peptides:v3"}``).
    resolve_ref:
        Async callback that takes a reference string
        (``"pubchem-peptides:v3"`` or ``"upload:<id>"``) and returns
        ``{"bucket": str, "key": str, "file_name": str}`` or *None*.

    Returns
    -------
    A new dict where reference values have been replaced with lists of
    values from the referenced file.  Non-reference values are unchanged.
    """
    store = get_object_store()
    result = dict(params)

    for key, value in list(result.items()):
        if not looks_like_storage_ref(str(value)):
            continue

        info = await resolve_ref(str(value))
        if not info:
            logger.warning("Could not resolve %s=%s, leaving unchanged", key, value)
            continue

        try:
            data = await asyncio.to_thread(
                store.get,
                info.get("bucket", "techneos-data"),
                info["key"],
            )
        except Exception:
            logger.exception("Failed to download %s for key %s", info["key"], key)
            continue

        inlined = inline_dataset_values(data, info.get("file_name", "data.csv"))
        if inlined is not None:
            result[key] = inlined
            logger.info(
                "Inlined %s=%s → %d value(s) from %s",
                key,
                value,
                len(inlined),
                info["key"],
            )

    return result
