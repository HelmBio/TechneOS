"""Canonical pipeline **shape** vs. per-version **binding** — shared helpers.

Single source of truth for the canonical pipeline identity — shape vs.
binding. The Alembic migration, the pipeline-service API/CRUD, and the
orchestrator all import from here so that identity (the ``topology_hash``) and
the shape⊕binding merge are computed *exactly* the same way everywhere.

Vocabulary
----------
- **shape** — the canonical, immutable DAG of a pipeline: per-step ``name`` /
  ``tool_slug`` / ``depends_on`` / ``inputs`` wiring, the ``edges``, and the
  run-I/O ``parameters_schema`` (with ``x-input`` / ``x-step`` routing). Lives on
  the parent ``pipelines`` row. Identified by ``topology_hash``.
- **binding** — what a version pins/tunes: ``{ step_name -> { tool_version,
  parameters } }``. Lives on the ``pipeline_versions`` row.

A legacy ``steps`` list (as stored today on ``pipeline_versions``) interleaves
both: each step carries shape fields *and* ``tool_version`` + ``parameters``.
``extract_shape`` / ``extract_bindings`` split them; ``merge`` recombines them.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, cast

# Step keys that belong to the BINDING, not the shape. Everything else on a
# step dict is part of the shape and contributes to identity.
_BINDING_STEP_KEYS: frozenset[str] = frozenset({"tool_version", "parameters"})


# ── Shape / binding extraction ───────────────────────────────────────────────


def extract_shape_step(step: dict[str, Any]) -> dict[str, Any]:
    """Project a (possibly legacy, interleaved) step onto its shape fields.

    Strips the binding keys (``tool_version``, ``parameters``); keeps ``name``,
    ``tool_slug``, ``depends_on``, ``inputs`` and any other shape metadata.
    """
    return {k: v for k, v in step.items() if k not in _BINDING_STEP_KEYS}


def extract_binding_step(step: dict[str, Any]) -> dict[str, Any]:
    """Project a step onto its binding: ``{tool_version, parameters}``."""
    return {
        "tool_version": step.get("tool_version"),
        "parameters": step.get("parameters") or {},
    }


def extract_shape(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Shape-only step list (binding fields removed from each step)."""
    return [extract_shape_step(s) for s in steps or []]


def extract_bindings(steps: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Build a binding map ``{step_name -> {tool_version, parameters}}``."""
    bindings: dict[str, dict[str, Any]] = {}
    for s in steps or []:
        name = s.get("name")
        if not name:
            continue
        bindings[name] = extract_binding_step(s)
    return bindings


def merge(
    shape_steps: list[dict[str, Any]],
    bindings: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Recombine parent **shape** with a version **binding** into effective steps.

    Produces the same ``steps`` shape the orchestrator and the run dialog
    consume today: each shape step augmented with the version's ``tool_version``
    pin and ``parameters`` for that step. Steps with no binding entry default to
    ``tool_version=None`` (latest) and ``parameters={}``.
    """
    bindings = bindings or {}
    merged: list[dict[str, Any]] = []
    for shape_step in shape_steps or []:
        name = shape_step.get("name", "")
        binding = bindings.get(name) or {}
        merged.append(
            {
                **shape_step,
                "tool_version": binding.get("tool_version"),
                "parameters": binding.get("parameters") or {},
            }
        )
    return merged


def schema_defaults(parameters_schema: dict[str, Any] | None) -> dict[str, Any]:
    """Extract run-input defaults declared as JSON-Schema ``default`` per property.

    Run-input defaults live on the ``parameters_schema`` itself rather
    than in a separate ``default_parameters`` blob. This reads them back out for
    run submission (``{property_name -> default}``).
    """
    if not isinstance(parameters_schema, dict):
        return {}
    props = parameters_schema.get("properties")
    if not isinstance(props, dict):
        return {}
    return {
        name: spec["default"]
        for name, spec in props.items()
        if isinstance(spec, dict) and "default" in spec
    }


def fold_default_parameters(
    parameters_schema: dict[str, Any],
    default_parameters: dict[str, Any] | None,
) -> dict[str, Any]:
    """Fold a legacy ``default_parameters`` map into the schema.

    There is no separate ``default_parameters`` blob: run-input
    defaults belong on each ``parameters_schema`` property as a JSON-Schema
    ``default``. Used by the backfill migration; returns a new schema dict and
    does not mutate the input. Existing property ``default`` values win.
    """
    if not default_parameters:
        return parameters_schema or {}
    schema = json.loads(json.dumps(parameters_schema or {}))  # deep copy
    props = schema.get("properties")
    if not isinstance(props, dict):
        return cast(dict[str, Any], schema)
    for key, value in default_parameters.items():
        prop = props.get(key)
        if isinstance(prop, dict) and "default" not in prop:
            prop["default"] = value
    return cast(dict[str, Any], schema)


# ── Canonical identity (topology_hash) ───────────────────────────────────────


def _canonical_inputs(inputs: Any) -> dict[str, Any]:
    """Normalize a step's ``inputs`` wiring for hashing.

    Keeps only the structural routing keys (``from_step``, ``path``, ``filter``)
    per named input, sorted by input name.
    """
    if not isinstance(inputs, dict):
        return {}
    out: dict[str, Any] = {}
    for name in sorted(inputs):
        spec = inputs[name]
        if isinstance(spec, dict):
            out[name] = {
                "from_step": spec.get("from_step"),
                "path": spec.get("path"),
                "filter": spec.get("filter"),
            }
        else:
            out[name] = spec
    return out


def _canonical_schema_routing(parameters_schema: Any) -> dict[str, Any]:
    """Extract the run-I/O *routing* from ``parameters_schema`` for hashing.

    Only the parts that define the contract's topology are included: which
    declared inputs exist (``x-input``) and which step each is routed to
    (``x-step``). Descriptions, examples, and validation details are excluded so
    that doc-only edits to the schema do not change pipeline identity.
    """
    if not isinstance(parameters_schema, dict):
        return {}
    props = parameters_schema.get("properties")
    routing: dict[str, Any] = {}
    if isinstance(props, dict):
        for name in sorted(props):
            spec = props[name]
            if isinstance(spec, dict) and spec.get("x-input"):
                routing[name] = {
                    "x-step": spec.get("x-step"),
                    "type": spec.get("type"),
                }
    required = parameters_schema.get("required")
    return {
        "inputs": routing,
        "required": sorted(required) if isinstance(required, list) else [],
    }


def canonical_topology(
    steps: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    parameters_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalized, order-independent projection of a pipeline's shape.

    Accepts either shape-only steps or legacy interleaved steps (binding fields
    are ignored). The result is deterministic regardless of the ordering of
    steps, edges, or ``depends_on`` lists, so it can be hashed for identity.
    """
    norm_steps = []
    for s in steps or []:
        norm_steps.append(
            {
                "name": s.get("name"),
                "tool_slug": s.get("tool_slug"),
                "depends_on": sorted(s.get("depends_on") or []),
                "inputs": _canonical_inputs(s.get("inputs")),
            }
        )
    norm_steps.sort(key=lambda s: str(s.get("name") or ""))

    norm_edges = sorted(
        (
            {"from_step": e.get("from_step"), "to_step": e.get("to_step")}
            for e in edges or []
        ),
        key=lambda e: (e.get("from_step") or "", e.get("to_step") or ""),
    )

    return {
        "steps": norm_steps,
        "edges": norm_edges,
        "schema": _canonical_schema_routing(parameters_schema),
    }


def topology_hash(
    steps: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    parameters_schema: dict[str, Any] | None = None,
) -> str:
    """Stable SHA-256 hex digest of a pipeline's canonical topology.

    This is the pipeline's structural fingerprint — its identity beyond the
    slug. Two pipelines (or two versions) with the same hash have the same DAG
    shape and run-I/O routing.
    """
    canonical = canonical_topology(steps, edges, parameters_schema)
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
