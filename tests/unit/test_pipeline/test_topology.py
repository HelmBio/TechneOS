"""Tests for core.pipeline_topology — shape/binding split + topology_hash."""

import copy

from core.pipeline_topology import (
    extract_bindings,
    extract_shape,
    fold_default_parameters,
    merge,
    schema_defaults,
    topology_hash,
)

# A representative 3-step pipeline (mirrors catalog/pipelines/hit-triage).
STEPS = [
    {"name": "screen", "tool_slug": "structure-alerts", "tool_version": None,
     "parameters": {"filter_catalogs": ["PAINS"]}, "depends_on": []},
    {"name": "cluster", "tool_slug": "compound-clustering", "tool_version": 2,
     "parameters": {"method": "butina"}, "depends_on": ["screen"],
     "inputs": {"compounds": {"from_step": "screen", "path": "results", "filter": {"passed": True}}}},
    {"name": "dock", "tool_slug": "autodock-vina", "tool_version": None,
     "parameters": {"exhaustiveness": 8}, "depends_on": ["cluster"]},
]
EDGES = [
    {"from_step": "screen", "to_step": "cluster"},
    {"from_step": "cluster", "to_step": "dock"},
]
SCHEMA = {
    "type": "object",
    "properties": {
        "compounds": {"type": "array", "x-input": True, "x-step": "screen"},
        "receptor": {"type": "string", "x-input": True, "x-step": "dock"},
    },
    "required": ["compounds", "receptor"],
}


def test_extract_shape_strips_binding_fields():
    shape = extract_shape(STEPS)
    for s in shape:
        assert "tool_version" not in s
        assert "parameters" not in s
    # shape keeps wiring + identity fields
    assert shape[1]["inputs"]["compounds"]["from_step"] == "screen"
    assert {s["name"] for s in shape} == {"screen", "cluster", "dock"}


def test_extract_bindings_captures_pins_and_params():
    b = extract_bindings(STEPS)
    assert b["cluster"] == {"tool_version": 2, "parameters": {"method": "butina"}}
    assert b["screen"]["tool_version"] is None


def test_merge_roundtrips_effective_steps():
    shape = extract_shape(STEPS)
    bindings = extract_bindings(STEPS)
    merged = merge(shape, bindings)
    for original, eff in zip(STEPS, merged, strict=True):
        assert eff["tool_version"] == original["tool_version"]
        assert eff["parameters"] == original["parameters"]
        assert eff["tool_slug"] == original["tool_slug"]


def test_merge_defaults_when_binding_missing():
    shape = extract_shape(STEPS)
    merged = merge(shape, {})  # no bindings at all
    assert all(s["tool_version"] is None and s["parameters"] == {} for s in merged)


def test_topology_hash_is_order_independent():
    h1 = topology_hash(STEPS, EDGES, SCHEMA)
    shuffled = list(reversed(copy.deepcopy(STEPS)))
    h2 = topology_hash(shuffled, list(reversed(EDGES)), SCHEMA)
    assert h1 == h2


def test_topology_hash_ignores_binding_and_doc_changes():
    base = topology_hash(STEPS, EDGES, SCHEMA)
    # Changing only a pin/param (a binding) must not change identity.
    s2 = copy.deepcopy(STEPS)
    s2[0]["tool_version"] = 9
    s2[0]["parameters"]["filter_catalogs"] = ["BRENK"]
    assert topology_hash(s2, EDGES, SCHEMA) == base
    # Doc-only schema edits must not change identity.
    sch2 = copy.deepcopy(SCHEMA)
    sch2["properties"]["receptor"]["description"] = "a receptor"
    assert topology_hash(STEPS, EDGES, sch2) == base


def test_topology_hash_changes_on_structural_edits():
    base = topology_hash(STEPS, EDGES, SCHEMA)
    # Swap a tool slug.
    s2 = copy.deepcopy(STEPS)
    s2[2]["tool_slug"] = "smina"
    assert topology_hash(s2, EDGES, SCHEMA) != base
    # Rewire an input route.
    sch2 = copy.deepcopy(SCHEMA)
    sch2["properties"]["receptor"]["x-step"] = "cluster"
    assert topology_hash(STEPS, EDGES, sch2) != base
    # Rewire a dependency.
    s3 = copy.deepcopy(STEPS)
    s3[2]["depends_on"] = ["screen"]
    assert topology_hash(s3, EDGES, SCHEMA) != base


def test_fold_default_parameters_onto_schema():
    schema = {"properties": {"exhaustiveness": {"type": "integer"}}}
    folded = fold_default_parameters(schema, {"exhaustiveness": 8})
    assert folded["properties"]["exhaustiveness"]["default"] == 8
    # original is not mutated
    assert "default" not in schema["properties"]["exhaustiveness"]
    # existing defaults win
    schema2 = {"properties": {"x": {"default": 1}}}
    assert fold_default_parameters(schema2, {"x": 99})["properties"]["x"]["default"] == 1


def test_schema_defaults_reads_back():
    schema = {"properties": {"a": {"default": 1}, "b": {"type": "string"}, "c": {"default": "z"}}}
    assert schema_defaults(schema) == {"a": 1, "c": "z"}
    assert schema_defaults({}) == {}
