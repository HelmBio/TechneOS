"""RDKit-based molecule standardization.

Opt-in per tool. Driven by a ``params["standardize"]`` block in the run
parameters, e.g.::

    {"standardize": {"strip_salts": true, "canonicalize": true}}

Standardizers operate on the ``list[dict]`` rows produced by
:mod:`techneos_tool_runtime.parsers`. The ``id`` key on each row is preserved
across standardization — only the ``smiles`` value is rewritten in place.

RDKit is imported lazily so tools that don't standardize don't pay the
import cost (and the runtime stays usable in environments without RDKit
for non-molecule tools).
"""

from __future__ import annotations

import logging
from typing import Any, cast

logger = logging.getLogger(__name__)


def _require_rdkit() -> Any:
    try:
        from rdkit import Chem
        from rdkit.Chem.MolStandardize import rdMolStandardize
    except ImportError as exc:
        raise RuntimeError(
            "Standardization requires rdkit. Install it in the tool image "
            "or omit the 'standardize' params block."
        ) from exc
    return Chem, rdMolStandardize


def standardize_smiles(
    smiles: str,
    *,
    sanitize: bool = True,
    strip_salts: bool = False,
    canonicalize: bool = True,
    neutralize_charges: bool = False,
) -> str | None:
    """Standardize a single SMILES string. Returns ``None`` if invalid.

    Steps run in order: parse → sanitize → strip_salts → neutralize_charges
    → canonicalize. Any failure short-circuits and returns ``None``.
    """
    Chem, rdMolStandardize = _require_rdkit()  # noqa: N806 — RDKit module names

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None

    if sanitize:
        try:
            Chem.SanitizeMol(mol)
        except Exception:
            return None

    if strip_salts:
        try:
            remover = rdMolStandardize.LargestFragmentChooser()
            mol = remover.choose(mol)
        except Exception:
            return None
        if mol is None:
            return None

    if neutralize_charges:
        try:
            uncharger = rdMolStandardize.Uncharger()
            mol = uncharger.uncharge(mol)
        except Exception:
            return None
        if mol is None:
            return None

    if canonicalize:
        try:
            return cast(str | None, Chem.MolToSmiles(mol))
        except Exception:
            return None

    return cast(str | None, Chem.MolToSmiles(mol))


def standardize_smiles_list(
    items: list[dict[str, str]],
    *,
    sanitize: bool = True,
    strip_salts: bool = False,
    canonicalize: bool = True,
    neutralize_charges: bool = False,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Standardize every row's ``smiles`` value in place.

    Returns ``(kept, dropped)``. A row is dropped when standardization
    yields ``None`` (invalid SMILES, salt stripping left nothing, etc.).
    The ``id`` key is preserved on both sides.
    """
    kept: list[dict[str, str]] = []
    dropped: list[dict[str, str]] = []
    for row in items:
        smi = row.get("smiles")
        if not smi:
            dropped.append(dict(row))
            continue
        standardized = standardize_smiles(
            smi,
            sanitize=sanitize,
            strip_salts=strip_salts,
            canonicalize=canonicalize,
            neutralize_charges=neutralize_charges,
        )
        if standardized is None:
            dropped.append(dict(row))
            continue
        new_row = dict(row)
        new_row["smiles"] = standardized
        kept.append(new_row)
    return kept, dropped


def apply(
    items: list[dict[str, str]],
    config: dict[str, Any] | bool | None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Apply standardization driven by a ``params["standardize"]`` value.

    Accepts a bool (``True`` → defaults), a dict of options, or
    ``None``/``False`` (no-op, returns the input unchanged).
    """
    if not config:
        return items, []
    if config is True:
        opts: dict[str, Any] = {}
    else:
        opts = dict(config)
    return standardize_smiles_list(items, **opts)


__all__ = [
    "apply",
    "standardize_smiles",
    "standardize_smiles_list",
]
