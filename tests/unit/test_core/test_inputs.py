"""Tests for core.inputs — reference detection and dataset inlining."""

from __future__ import annotations

from core.inputs import inline_dataset_values, looks_like_storage_ref


class TestLooksLikeStorageRef:
    def test_upload_ref(self):
        assert looks_like_storage_ref("upload:abc-123") is True

    def test_dataset_ref(self):
        assert looks_like_storage_ref("pubchem-peptides:v3") is True

    def test_dataset_ref_with_dots(self):
        assert looks_like_storage_ref("my.dataset:v1") is True

    def test_dataset_ref_with_dash(self):
        assert looks_like_storage_ref("my-dataset:v1") is True

    def test_plain_string_not_ref(self):
        assert looks_like_storage_ref("CCO") is False

    def test_slug_without_version_not_ref(self):
        assert looks_like_storage_ref("pubchem-peptides") is False

    def test_non_string_not_ref(self):
        assert looks_like_storage_ref(["CCO"]) is False
        assert looks_like_storage_ref(123) is False


class TestInlineDatasetValues:
    def test_tsv_with_smiles_column(self):
        data = b"CID\tSMILES\n1\tCCO\n2\tc1ccccc1\n"
        assert inline_dataset_values(data, "data.tsv") == ["CCO", "c1ccccc1"]

    def test_csv_with_smiles_column(self):
        data = b"id,smiles\n1,CCO\n2,c1ccccc1\n"
        assert inline_dataset_values(data, "data.csv") == ["CCO", "c1ccccc1"]

    def test_no_smiles_column_skips_header(self):
        data = b"name,value\nCCO,10\nc1ccccc1,20\n"
        assert inline_dataset_values(data, "data.csv") == ["CCO", "c1ccccc1"]

    def test_empty_file_returns_none(self):
        assert inline_dataset_values(b"", "empty.tsv") is None

    def test_single_data_row(self):
        data = b"SMILES\nCCO\n"
        vals = inline_dataset_values(data, "data.tsv")
        assert vals == ["CCO"]

    def test_single_row_no_header(self):
        data = b"CCO\n"
        assert inline_dataset_values(data, "data.tsv") == ["CCO"]
