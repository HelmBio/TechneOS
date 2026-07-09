"""Input file parsers — convert a downloaded file into a tool-ready Python value.

Tools receive a uniform input shape regardless of where the data came from
(paste, upload, or dataset). The runner downloads the file to /work/input/
and then calls one of the parsers here to turn it into the value the tool's
``run()`` actually consumes.

For SMILES inputs, every parser returns ``list[dict]`` rows of
``{"smiles": str, "id": str?}``. The ``id`` key is omitted when the source
has no identifying column. ``_normalize_input_item`` in tools that follow
the platform conventions already accepts this shape, so no per-tool change
is needed to propagate IDs end-to-end.

Tools can override the default parser for any field by exporting a
``parse(file_path, params)`` function alongside ``run()``; the runner
picks it up via ``getattr``.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Column-detection heuristics. First hit wins, case-insensitive.
_SMILES_COLUMN_CANDIDATES = (
    "smiles",
    "canonical_smiles",
    "canonical smiles",
    "mol_smiles",
    "isomeric_smiles",
)
_ID_COLUMN_CANDIDATES = (
    "id",
    "name",
    "compound_id",
    "molecule_id",
    "mol_id",
    "chembl_id",
)


def _find_column(header: list[str], candidates: Iterable[str]) -> int | None:
    """Case-insensitive header lookup. Returns the first matching index."""
    normalized = [c.strip().lower() for c in header]
    for cand in candidates:
        key = cand.strip().lower()
        if key in normalized:
            return normalized.index(key)
    return None


def _explicit_column(header: list[str], name: str | None) -> int | None:
    if not name:
        return None
    normalized = [c.strip().lower() for c in header]
    key = name.strip().lower()
    if key in normalized:
        return normalized.index(key)
    raise ValueError(f"Column {name!r} not found in header {header!r}")


def _parse_smiles_delimited(
    data: bytes,
    delimiter: str,
    *,
    smiles_column: str | None = None,
    id_column: str | None = None,
) -> list[dict[str, str]]:
    """Shared CSV/TSV path. Returns ``[{"smiles", "id"?}, ...]``."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="replace")

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = list(reader)
    if not rows:
        return []

    header = rows[0]
    smi_idx = _explicit_column(header, smiles_column)
    if smi_idx is None:
        smi_idx = _find_column(header, _SMILES_COLUMN_CANDIDATES)

    id_idx = _explicit_column(header, id_column)
    if id_idx is None:
        id_idx = _find_column(header, _ID_COLUMN_CANDIDATES)
    if id_idx == smi_idx:
        id_idx = None

    has_header = smi_idx is not None
    if smi_idx is None:
        # No SMILES header: assume first column is SMILES and no header row.
        smi_idx = 0
        data_rows: Iterable[list[str]] = rows
    else:
        data_rows = rows[1:]

    out: list[dict[str, str]] = []
    for row in data_rows:
        if smi_idx >= len(row):
            continue
        smi = row[smi_idx].strip()
        if not smi:
            continue
        item: dict[str, str] = {"smiles": smi}
        if id_idx is not None and id_idx < len(row):
            mid = row[id_idx].strip()
            if mid:
                item["id"] = mid
        out.append(item)

    if not has_header and id_idx is not None:
        # We can't have detected an ID column without a header; keep mypy happy.
        logger.debug("ID column ignored because no header row was detected")

    return out


def parse_smiles_csv(
    path: Path | str,
    *,
    smiles_column: str | None = None,
    id_column: str | None = None,
) -> list[dict[str, str]]:
    """Parse a CSV file into ``[{"smiles", "id"?}, ...]``.

    Heuristics:
      1. Header row scanned for a SMILES column (``smiles``,
         ``canonical_smiles``, …). If found, also scan for an ID column
         (``id``, ``name``, ``compound_id``, …). Both are case-insensitive.
      2. If no SMILES header, the first column is treated as SMILES with no
         header row, and IDs are not extracted.
      3. Explicit ``smiles_column`` / ``id_column`` overrides skip the
         heuristic. A missing column raises ``ValueError``.
    """
    data = Path(path).read_bytes()
    return _parse_smiles_delimited(data, ",", smiles_column=smiles_column, id_column=id_column)


def parse_smiles_tsv(
    path: Path | str,
    *,
    smiles_column: str | None = None,
    id_column: str | None = None,
) -> list[dict[str, str]]:
    """Tab-separated variant of :func:`parse_smiles_csv`."""
    data = Path(path).read_bytes()
    return _parse_smiles_delimited(data, "\t", smiles_column=smiles_column, id_column=id_column)


def parse_smiles_text(
    path: Path | str,
    *,
    smiles_column: str | None = None,  # accepted for parity, ignored
    id_column: str | None = None,
) -> list[dict[str, str]]:
    """One SMILES per line. ``<smiles>\\t<id>`` or ``<smiles>,<id>`` pulls an ID.

    Skips blank lines and lines starting with ``#``.
    """
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    out: list[dict[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Allow either TSV or CSV pair on a single line.
        parts: list[str]
        if "\t" in line:
            parts = [p.strip() for p in line.split("\t", 1)]
        elif "," in line:
            parts = [p.strip() for p in line.split(",", 1)]
        else:
            parts = [line]
        if not parts[0]:
            continue
        item: dict[str, str] = {"smiles": parts[0]}
        if len(parts) > 1 and parts[1]:
            item["id"] = parts[1]
        out.append(item)
    return out


def parse_smiles_json(
    path: Path | str,
    *,
    smiles_column: str | None = None,  # accepted for parity, ignored
    id_column: str | None = None,
) -> list[dict[str, str]]:
    """Parse a JSON paste — either ``["CCO", ...]`` or ``[{"smiles", "id"}]``.

    Accepts the shape paste mode used to emit before all input modes were
    unified through MinIO, so legacy pastes keep working without UI change.
    """
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        # Fall back to one-SMILES-per-line.
        return parse_smiles_text(path)

    if isinstance(payload, dict):
        # Treat {"smiles": [...]} the same as the bare array.
        if isinstance(payload.get("smiles"), list):
            payload = payload["smiles"]
        else:
            return []
    if not isinstance(payload, list):
        return []

    out: list[dict[str, str]] = []
    for item in payload:
        if isinstance(item, str):
            s = item.strip()
            if s:
                out.append({"smiles": s})
        elif isinstance(item, dict):
            smi = (item.get("smiles") or "").strip()
            if not smi:
                continue
            row: dict[str, str] = {"smiles": smi}
            mid = item.get("id")
            if isinstance(mid, str) and mid.strip():
                row["id"] = mid.strip()
            out.append(row)
    return out


def parse_smiles_sdf(
    path: Path | str,
    *,
    smiles_column: str | None = None,  # accepted for parity, ignored
    id_column: str | None = None,
) -> list[dict[str, str]]:
    """Parse an SDF using RDKit. Uses ``_Name`` (or named SD tag) as ``id``.

    ``id_column`` may be set to an SD-tag name to pull the ID from a property
    block other than ``_Name``.
    """
    try:
        from rdkit import Chem
    except ImportError as exc:
        raise RuntimeError(
            "parse_smiles_sdf requires rdkit. Install it or supply a "
            "tool-level parse() that doesn't need it."
        ) from exc

    suppl = Chem.SDMolSupplier(str(path), removeHs=False)
    out: list[dict[str, str]] = []
    for mol in suppl:
        if mol is None:
            continue
        smi = Chem.MolToSmiles(mol)
        if not smi:
            continue
        item: dict[str, str] = {"smiles": smi}
        if id_column:
            if mol.HasProp(id_column):
                item["id"] = mol.GetProp(id_column).strip()
        else:
            if mol.HasProp("_Name"):
                name = mol.GetProp("_Name").strip()
                if name:
                    item["id"] = name
        out.append(item)
    return out


# ── Entry point used by the runner ──────────────────────────────────────


def parse(
    file_path: Path | str,
    *,
    input_kind: str = "smiles_list",
    content_type: str | None = None,
    params: dict[str, Any] | None = None,
) -> Any:
    """Dispatch a downloaded file to the parser for its ``input_kind``.

    Delegates to :mod:`techneos_tool_runtime.kinds` — the registry is the
    single source of truth for what kinds exist and which parser each
    one uses. ``content_type`` and per-field options like
    ``smiles_column`` / ``id_column`` are forwarded as kwargs.

    An unknown kind falls back to :class:`~kinds.InputKind.SMILES_LIST`
    so legacy tools that haven't declared a kind yet keep working.
    """
    from techneos_tool_runtime import kinds

    params = params or {}
    spec = kinds.resolve(input_kind) or kinds.require(kinds.InputKind.SMILES_LIST)
    if spec.kind.value != input_kind:
        logger.warning(
            "Unknown input_kind %r; falling back to %s",
            input_kind,
            spec.kind.value,
        )

    return spec.default_parser(
        file_path,
        content_type=content_type,
        smiles_column=params.get("smiles_column"),
        id_column=params.get("id_column"),
    )


__all__ = [
    "parse",
    "parse_smiles_csv",
    "parse_smiles_json",
    "parse_smiles_sdf",
    "parse_smiles_text",
    "parse_smiles_tsv",
]
