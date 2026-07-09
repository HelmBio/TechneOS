"""The platform's controlled vocabulary of tool input kinds.

A tool declares ``input_kind`` once at the top level of its
``input_schema`` — it's a contract about *what shape the tool's ``run()``
receives*, not about the file format the user supplied. The parsers
registered here translate any of a kind's supported file formats into
that canonical Python shape.

Adding a new kind
-----------------
1. Add an entry to :class:`InputKind`.
2. Add a :class:`KindSpec` to :data:`REGISTRY` describing the canonical
   shape and the default parser.
3. Bump ``techneos-tool-runtime`` and have tools that want the new kind
   target the new version.

Tools that need something outside this list can still ship their own
``parse(file_path, params)`` alongside ``run()`` — the runner picks it
up automatically and skips the registry.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class InputKind(StrEnum):
    """Canonical input kinds the platform parsers know how to produce.

    Each value documents the *Python shape* the tool's ``run(inputs,
    params)`` will see — not the file format on disk. See
    :data:`REGISTRY` for the per-kind parser/standardizer wiring.

    Naming convention
    -----------------
    The kind name encodes the Python shape, which transitively encodes
    cardinality:

    - **Bare name** = singleton (``str``, ``dict``, ``Path``…). The tool
      receives one item. Used when the natural unit of work is one —
      e.g. ``protein_structure`` (one receptor for docking).
    - **``_list`` suffix** = batch. The tool receives ``list[...]``. Used
      when the natural unit of work is many — e.g. ``smiles_list``
      (thousands of ligands in a virtual screen).

    The asymmetry between ``smiles_list`` and ``protein_structure``
    mirrors the dominant drug-discovery workflow: "screen many ligands
    x one receptor". When a rarer cardinality is needed, add a separate
    kind rather than overloading an existing one — e.g.
    ``protein_structure_list`` for ensemble docking or MD trajectory
    frames, ``smiles`` (singular) for single-molecule lead profiling.
    """

    #: ``list[{"smiles": str, "id": str?}]`` — small molecules.
    SMILES_LIST = "smiles_list"

    #: ``str`` — absolute path to a protein structure file. Accepts
    #: ``.pdb``, ``.cif``/``.mmcif`` (newer macromolecular CIF format),
    #: and ``.ent``. The file may contain bound ligands, cofactors,
    #: waters, or ions as HETATM records — they ride along with the
    #: structure and the tool decides whether to keep or strip them.
    PROTEIN_STRUCTURE = "protein_structure"


@dataclass(frozen=True)
class KindSpec:
    """Per-kind metadata used by the runtime preprocessor.

    ``default_parser`` is called with the downloaded file path plus
    keyword arguments from ``params`` (e.g. ``smiles_column``,
    ``id_column``). It must return the canonical Python shape documented
    on the corresponding :class:`InputKind` value.

    ``supports_standardization`` is the gate that decides whether the
    ``params["standardize"]`` block is honoured for fields of this kind.
    Today only molecular kinds set this true; protein/structure kinds
    will get their own normalization config when introduced.
    """

    kind: InputKind
    description: str
    default_parser: Callable[..., Any]
    supports_standardization: bool = False


def _smiles_list_parser(
    file_path: Path | str,
    *,
    content_type: str | None = None,
    smiles_column: str | None = None,
    id_column: str | None = None,
    **_: Any,
) -> list[dict[str, str]]:
    """Format dispatcher for SMILES_LIST.

    Defined here (not in :mod:`parsers`) so the registry stays the single
    source of truth for "what does this kind do". The format-specific
    helpers live in :mod:`parsers`; this just routes to them.
    """
    from techneos_tool_runtime.parsers import (
        parse_smiles_csv,
        parse_smiles_json,
        parse_smiles_sdf,
        parse_smiles_text,
        parse_smiles_tsv,
    )

    p = Path(file_path)
    suffix = p.suffix.lower().lstrip(".")
    ct = (content_type or "").lower()

    if suffix == "tsv" or "tab-separated" in ct:
        return parse_smiles_tsv(p, smiles_column=smiles_column, id_column=id_column)
    if suffix in ("sdf", "mol", "sd"):
        return parse_smiles_sdf(p, id_column=id_column)
    if suffix == "csv" or "csv" in ct:
        return parse_smiles_csv(p, smiles_column=smiles_column, id_column=id_column)
    if suffix == "json" or "json" in ct:
        return parse_smiles_json(p)
    if suffix in ("smi", "smiles", "txt") or ct.startswith("text/plain"):
        return parse_smiles_text(p)

    # Last resort: try CSV (handles header-less single-column files too).
    return parse_smiles_csv(p, smiles_column=smiles_column, id_column=id_column)


def _protein_structure_parser(
    file_path: Path | str,
    *,
    content_type: str | None = None,
    **_: Any,
) -> str:
    """Identity-style parser for PROTEIN_STRUCTURE.

    Tools want the file path, not Python-parsed atoms — every downstream
    library (RDKit, Bio.PDB, OpenBabel, PyMOL, MDAnalysis) ingests the
    file directly. We only sanity-check that the file exists, isn't
    empty, and looks like a structure file (has at least one ATOM or
    HETATM record for PDB; an ``_atom_site`` loop for mmCIF). Tools
    can then open the path with whichever library they prefer.
    """
    p = Path(file_path)
    if not p.is_file():
        raise FileNotFoundError(f"Structure file not found: {p}")
    if p.stat().st_size == 0:
        raise ValueError(f"Structure file is empty: {p}")

    suffix = p.suffix.lower().lstrip(".")
    ct = (content_type or "").lower()
    is_mmcif = suffix in ("cif", "mmcif") or "mmcif" in ct or "cif" in ct
    is_pdb = suffix in ("pdb", "ent") or "pdb" in ct

    if not (is_pdb or is_mmcif):
        # Don't reject — the tool may know better than we do. Just warn.
        logger.warning(
            "File %s has unrecognised structure extension/content-type; passing through anyway",
            p,
        )
        return str(p)

    # Lightweight format sniff so an upload mislabeled as PDB but
    # actually mmCIF (or vice versa) fails here with a clear message
    # rather than deep inside the tool.
    head = p.read_bytes()[:4096].decode("utf-8", errors="replace")
    if is_pdb and not any(
        line.startswith(("ATOM ", "HETATM", "MODEL ", "HEADER")) for line in head.splitlines()
    ):
        raise ValueError(
            f"File {p.name} has a .pdb-like extension but no ATOM/HETATM/HEADER "
            "records were found in the first 4 KB."
        )
    if is_mmcif and "_atom_site" not in head and not head.lstrip().startswith("data_"):
        raise ValueError(
            f"File {p.name} has a .cif-like extension but doesn't look like "
            "mmCIF (no data_ block or _atom_site loop in the first 4 KB)."
        )

    return str(p)


REGISTRY: dict[InputKind, KindSpec] = {
    InputKind.SMILES_LIST: KindSpec(
        kind=InputKind.SMILES_LIST,
        description=(
            "Small-molecule list. Shape: list[{smiles, id?}]. "
            "Accepts CSV, TSV, SDF, JSON, and one-per-line text."
        ),
        default_parser=_smiles_list_parser,
        supports_standardization=True,
    ),
    InputKind.PROTEIN_STRUCTURE: KindSpec(
        kind=InputKind.PROTEIN_STRUCTURE,
        description=(
            "Protein structure file, optionally with bound ligands, "
            "cofactors, waters, or ions. Shape: str (absolute file path). "
            "Accepts PDB (.pdb, .ent) and mmCIF (.cif, .mmcif). Tools "
            "open the file with their preferred library; the platform "
            "does not pre-parse atoms."
        ),
        default_parser=_protein_structure_parser,
        # Small-molecule standardization (sanitize/strip salts/canonicalize)
        # doesn't apply to proteins. If protein normalization (strip
        # waters, fill missing atoms, …) is needed later, it gets its
        # own params key and gate — not the smiles_list one.
        supports_standardization=False,
    ),
}


def resolve(kind: str | InputKind | None) -> KindSpec | None:
    """Look up a :class:`KindSpec` by string or enum, or ``None`` if unknown.

    Callers that want a hard error on an unknown kind should use
    :func:`require`. ``None`` is returned for missing/unrecognised input
    so callers can fall back to extension-based parsing for legacy tools
    that haven't declared a kind yet.
    """
    if kind is None:
        return None
    try:
        key = InputKind(kind) if not isinstance(kind, InputKind) else kind
    except ValueError:
        return None
    return REGISTRY.get(key)


def require(kind: str | InputKind) -> KindSpec:
    """Like :func:`resolve` but raises when the kind isn't registered."""
    spec = resolve(kind)
    if spec is None:
        raise ValueError(
            f"Unknown input_kind {kind!r}. Registered: {sorted(k.value for k in REGISTRY)}"
        )
    return spec


__all__ = ["REGISTRY", "InputKind", "KindSpec", "require", "resolve"]
