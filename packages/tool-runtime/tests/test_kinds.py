"""Tests for the input-kind registry."""

from __future__ import annotations

import pytest

from techneos_tool_runtime import kinds
from techneos_tool_runtime.kinds import InputKind, KindSpec


def test_smiles_list_registered():
    spec = kinds.resolve("smiles_list")
    assert spec is not None
    assert spec.kind is InputKind.SMILES_LIST
    assert spec.supports_standardization is True


def test_resolve_accepts_enum_value():
    spec = kinds.resolve(InputKind.SMILES_LIST)
    assert spec is not None
    assert spec.kind is InputKind.SMILES_LIST


def test_resolve_unknown_returns_none():
    assert kinds.resolve("nonsense_kind") is None
    assert kinds.resolve(None) is None


def test_require_raises_on_unknown():
    with pytest.raises(ValueError, match="Unknown input_kind"):
        kinds.require("nonsense_kind")


def test_smiles_list_parser_routes_by_extension(tmp_path):
    """The smiles_list parser delegates to the right format helper."""
    spec = kinds.require(InputKind.SMILES_LIST)

    csv_path = tmp_path / "mols.csv"
    csv_path.write_text("smiles\nCCO\n")
    assert spec.default_parser(csv_path) == [{"smiles": "CCO"}]

    text_path = tmp_path / "mols.txt"
    text_path.write_text("CCO\nc1ccccc1\n")
    assert spec.default_parser(text_path) == [
        {"smiles": "CCO"},
        {"smiles": "c1ccccc1"},
    ]


def test_smiles_list_parser_uses_content_type_when_extension_ambiguous(tmp_path):
    spec = kinds.require(InputKind.SMILES_LIST)
    p = tmp_path / "no_extension"
    p.write_text("smiles\nCCO\n")
    assert spec.default_parser(p, content_type="text/csv") == [{"smiles": "CCO"}]


def test_registry_is_a_dict_of_specs():
    """Sanity: every registered entry is a KindSpec keyed by its own enum."""
    for key, spec in kinds.REGISTRY.items():
        assert isinstance(key, InputKind)
        assert isinstance(spec, KindSpec)
        assert spec.kind is key


# ── PROTEIN_STRUCTURE ──────────────────────────────────────────────────


def test_protein_structure_registered_and_no_standardization():
    """Small-molecule standardization shouldn't apply to proteins."""
    spec = kinds.require(InputKind.PROTEIN_STRUCTURE)
    assert spec.supports_standardization is False


def test_protein_structure_parser_returns_path_for_valid_pdb(tmp_path):
    pdb = tmp_path / "1ABC.pdb"
    pdb.write_text(
        "HEADER    HYDROLASE                               01-JAN-00   1ABC\n"
        "ATOM      1  N   ALA A   1      11.104  13.207  10.000  1.00 20.00           N\n"
        "ATOM      2  CA  ALA A   1      12.560  13.215  10.000  1.00 20.00           C\n"
    )
    spec = kinds.require(InputKind.PROTEIN_STRUCTURE)
    assert spec.default_parser(pdb) == str(pdb)


def test_protein_structure_parser_accepts_mmcif(tmp_path):
    cif = tmp_path / "1ABC.cif"
    cif.write_text("data_1ABC\nloop_\n_atom_site.group_PDB\n_atom_site.id\nATOM 1\nATOM 2\n")
    spec = kinds.require(InputKind.PROTEIN_STRUCTURE)
    assert spec.default_parser(cif) == str(cif)


def test_protein_structure_parser_rejects_empty_file(tmp_path):
    bad = tmp_path / "empty.pdb"
    bad.write_text("")
    spec = kinds.require(InputKind.PROTEIN_STRUCTURE)
    with pytest.raises(ValueError, match="empty"):
        spec.default_parser(bad)


def test_protein_structure_parser_rejects_pdb_without_atom_records(tmp_path):
    """A .pdb file that doesn't actually contain ATOM/HETATM records fails fast."""
    bad = tmp_path / "fake.pdb"
    bad.write_text("This is not a PDB file at all.\nJust some text.\n")
    spec = kinds.require(InputKind.PROTEIN_STRUCTURE)
    with pytest.raises(ValueError, match="no ATOM/HETATM"):
        spec.default_parser(bad)


def test_protein_structure_parser_rejects_cif_without_data_block(tmp_path):
    bad = tmp_path / "fake.cif"
    bad.write_text("Just plain text, no data_ block here.\n")
    spec = kinds.require(InputKind.PROTEIN_STRUCTURE)
    with pytest.raises(ValueError, match="mmCIF"):
        spec.default_parser(bad)


def test_protein_structure_parser_keeps_hetatm_records(tmp_path):
    """A PDB with a bound ligand (HETATM block) is accepted — that's the point."""
    pdb = tmp_path / "1ABC.pdb"
    pdb.write_text(
        "HEADER    LIGAND-BOUND COMPLEX\n"
        "ATOM      1  N   ALA A   1      11.104  13.207  10.000  1.00 20.00           N\n"
        "HETATM 1500  C1  STI A 500      20.000  30.000  40.000  1.00 30.00           C\n"
    )
    spec = kinds.require(InputKind.PROTEIN_STRUCTURE)
    assert spec.default_parser(pdb) == str(pdb)
