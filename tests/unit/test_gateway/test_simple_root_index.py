"""Tests for the synthesized PEP 503 root index (/simple/).

CodeArtifact does not serve the root listing, so the gateway renders it from
the control-plane package list. These cover the pure rendering/normalization;
the boto3 enumeration itself is exercised against a live repo.
"""

from gateway.routes.artifacts import _normalize_pep503, _render_root_index


class TestNormalize:
    def test_underscores_and_dots_become_hyphens(self):
        assert _normalize_pep503("techneos_management") == "techneos-management"
        assert _normalize_pep503("Foo.Bar_Baz") == "foo-bar-baz"

    def test_runs_collapse(self):
        assert _normalize_pep503("a__b..c--d") == "a-b-c-d"

    def test_already_normalized_is_stable(self):
        assert _normalize_pep503("techneos-cli") == "techneos-cli"


class TestRenderRootIndex:
    def test_lists_each_package_once_sorted(self):
        html = _render_root_index(["techneos_management", "techneos-cli", "techneos_management"])
        # Deduplicated after normalization.
        assert html.count("techneos-management/") == 1
        # Sorted: cli before management.
        assert html.index("techneos-cli/") < html.index("techneos-management/")

    def test_hrefs_are_normalized_pep503_names(self):
        html = _render_root_index(["Foo_Bar"])
        assert '<a href="foo-bar/">foo-bar</a>' in html

    def test_empty_index_renders_valid_page(self):
        html = _render_root_index([])
        assert "<!DOCTYPE html>" in html
        assert "<a " not in html
