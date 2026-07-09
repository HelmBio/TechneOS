"""Tests for techneos_tool_runtime.parsers — file → list[dict] conversion."""

from __future__ import annotations

import pytest

from techneos_tool_runtime import parsers

# ── CSV ────────────────────────────────────────────────────────────────


def test_csv_with_smiles_header(tmp_path):
    p = tmp_path / "mols.csv"
    p.write_text("smiles\nCCO\nc1ccccc1\n")
    assert parsers.parse_smiles_csv(p) == [
        {"smiles": "CCO"},
        {"smiles": "c1ccccc1"},
    ]


def test_csv_with_id_and_smiles_columns(tmp_path):
    p = tmp_path / "mols.csv"
    p.write_text("id,smiles\nmol-1,CCO\nmol-2,c1ccccc1\n")
    assert parsers.parse_smiles_csv(p) == [
        {"smiles": "CCO", "id": "mol-1"},
        {"smiles": "c1ccccc1", "id": "mol-2"},
    ]


def test_csv_picks_name_column_as_id(tmp_path):
    """`name` is a recognised ID-column alias."""
    p = tmp_path / "mols.csv"
    p.write_text("name,smiles\nethanol,CCO\nbenzene,c1ccccc1\n")
    rows = parsers.parse_smiles_csv(p)
    assert rows[0]["id"] == "ethanol"
    assert rows[1]["id"] == "benzene"


def test_csv_without_header_assumes_first_column(tmp_path):
    """No SMILES header → first column is treated as SMILES, no IDs."""
    p = tmp_path / "mols.csv"
    p.write_text("CCO\nc1ccccc1\n")
    assert parsers.parse_smiles_csv(p) == [
        {"smiles": "CCO"},
        {"smiles": "c1ccccc1"},
    ]


def test_csv_explicit_column_overrides(tmp_path):
    p = tmp_path / "mols.csv"
    p.write_text("ChEMBL ID,Canonical SMILES,MW\nCHEMBL1,CCO,46.07\nCHEMBL2,c1ccccc1,78.11\n")
    rows = parsers.parse_smiles_csv(p, smiles_column="Canonical SMILES", id_column="ChEMBL ID")
    assert rows == [
        {"smiles": "CCO", "id": "CHEMBL1"},
        {"smiles": "c1ccccc1", "id": "CHEMBL2"},
    ]


def test_csv_explicit_missing_column_raises(tmp_path):
    p = tmp_path / "mols.csv"
    p.write_text("smiles\nCCO\n")
    with pytest.raises(ValueError, match="not found"):
        parsers.parse_smiles_csv(p, smiles_column="not_a_column")


def test_csv_skips_blank_smiles_values(tmp_path):
    p = tmp_path / "mols.csv"
    p.write_text("id,smiles\nmol-1,CCO\nmol-2,\nmol-3,c1ccccc1\n")
    rows = parsers.parse_smiles_csv(p)
    assert [r["smiles"] for r in rows] == ["CCO", "c1ccccc1"]


# ── TSV ────────────────────────────────────────────────────────────────


def test_tsv_with_id_column(tmp_path):
    p = tmp_path / "mols.tsv"
    p.write_text("id\tsmiles\nmol-1\tCCO\nmol-2\tc1ccccc1\n")
    rows = parsers.parse_smiles_tsv(p)
    assert rows == [
        {"smiles": "CCO", "id": "mol-1"},
        {"smiles": "c1ccccc1", "id": "mol-2"},
    ]


# ── plain text ─────────────────────────────────────────────────────────


def test_text_one_smiles_per_line(tmp_path):
    p = tmp_path / "paste.txt"
    p.write_text("CCO\nc1ccccc1\n")
    assert parsers.parse_smiles_text(p) == [
        {"smiles": "CCO"},
        {"smiles": "c1ccccc1"},
    ]


def test_text_with_tab_separated_ids(tmp_path):
    p = tmp_path / "paste.txt"
    p.write_text("CCO\tethanol\nc1ccccc1\tbenzene\n")
    assert parsers.parse_smiles_text(p) == [
        {"smiles": "CCO", "id": "ethanol"},
        {"smiles": "c1ccccc1", "id": "benzene"},
    ]


def test_text_skips_blank_and_comments(tmp_path):
    p = tmp_path / "paste.txt"
    p.write_text("# header comment\nCCO\n\n# mid comment\nc1ccccc1\n")
    assert parsers.parse_smiles_text(p) == [
        {"smiles": "CCO"},
        {"smiles": "c1ccccc1"},
    ]


# ── JSON paste ─────────────────────────────────────────────────────────


def test_json_array_of_strings(tmp_path):
    p = tmp_path / "paste.json"
    p.write_text('["CCO", "c1ccccc1"]')
    assert parsers.parse_smiles_json(p) == [
        {"smiles": "CCO"},
        {"smiles": "c1ccccc1"},
    ]


def test_json_array_of_objects_preserves_ids(tmp_path):
    p = tmp_path / "paste.json"
    p.write_text('[{"smiles": "CCO", "id": "mol-1"}, {"smiles": "c1ccccc1"}]')
    assert parsers.parse_smiles_json(p) == [
        {"smiles": "CCO", "id": "mol-1"},
        {"smiles": "c1ccccc1"},
    ]


def test_json_falls_back_to_text_on_parse_failure(tmp_path):
    p = tmp_path / "paste.json"
    p.write_text("CCO\nc1ccccc1\n")  # not valid JSON
    assert parsers.parse_smiles_json(p) == [
        {"smiles": "CCO"},
        {"smiles": "c1ccccc1"},
    ]


# ── parse() dispatcher ─────────────────────────────────────────────────


def test_dispatcher_picks_csv_from_extension(tmp_path):
    p = tmp_path / "mols.csv"
    p.write_text("smiles\nCCO\n")
    assert parsers.parse(p, input_kind="smiles_list") == [{"smiles": "CCO"}]


def test_dispatcher_picks_csv_from_content_type(tmp_path):
    p = tmp_path / "ambiguous"
    p.write_text("smiles\nCCO\n")
    rows = parsers.parse(p, input_kind="smiles_list", content_type="text/csv")
    assert rows == [{"smiles": "CCO"}]


def test_dispatcher_picks_tsv_from_content_type(tmp_path):
    p = tmp_path / "ambiguous"
    p.write_text("smiles\tid\nCCO\tmol-1\n")
    rows = parsers.parse(p, input_kind="smiles_list", content_type="text/tab-separated-values")
    assert rows == [{"smiles": "CCO", "id": "mol-1"}]


def test_dispatcher_passes_column_overrides_via_params(tmp_path):
    p = tmp_path / "mols.csv"
    p.write_text("ChEMBL ID,Canonical SMILES\nCHEMBL1,CCO\n")
    rows = parsers.parse(
        p,
        input_kind="smiles_list",
        content_type="text/csv",
        params={"smiles_column": "Canonical SMILES", "id_column": "ChEMBL ID"},
    )
    assert rows == [{"smiles": "CCO", "id": "CHEMBL1"}]


def test_dispatcher_unknown_kind_falls_back_to_smiles_list(tmp_path):
    p = tmp_path / "mols.csv"
    p.write_text("smiles\nCCO\n")
    rows = parsers.parse(p, input_kind="unknown_kind", content_type="text/csv")
    assert rows == [{"smiles": "CCO"}]
