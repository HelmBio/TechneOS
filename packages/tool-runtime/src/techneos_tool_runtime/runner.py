"""Generic container entry point: import a tool's run() and call it.

The base image's ENTRYPOINT is `python -m techneos_tool_runtime.runner`. The
specific tool sets ENTRYPOINT_SPEC=module.path:function so the runner knows
what to invoke.

Flow:
    1. Resolve work dir (TECHNEOS_WORK_DIR or /work).
    2. Read inputs.json + params.json.
    3. Import ENTRYPOINT_SPEC.
    4. Call run(inputs, params).
    5. Write returned dict to output/result.json.
    6. Exit 0 on success, non-zero with a structured error.json on failure.

The same runner is invoked for pypi tools — the worker just shells in a
pip-install step first and sets ENTRYPOINT_SPEC to the entry point declared
on the tool version. So a single code path handles both delivery channels.
"""

from __future__ import annotations

import argparse
import importlib
import json
import logging
import os
import sys
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from techneos_tool_runtime import parsers, standardizers
from techneos_tool_runtime.io import (
    WorkDir,
    read_inputs,
    read_params,
    write_result,
)

logger = logging.getLogger("techneos_tool_runner")


class RunnerError(Exception):
    """Raised when the runner can't even reach the tool's run() function."""


def _parse_entrypoint_spec(spec: str) -> tuple[str, str]:
    """Split 'module.path:function' into ('module.path', 'function')."""
    if ":" not in spec:
        raise RunnerError(f"ENTRYPOINT_SPEC must be 'module.path:function', got: {spec!r}")
    module_path, func_name = spec.rsplit(":", 1)
    if not module_path or not func_name:
        raise RunnerError(f"ENTRYPOINT_SPEC has empty module or function: {spec!r}")
    return module_path, func_name


def resolve_entrypoint(spec: str) -> Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]:
    """Import the entrypoint and return the callable.

    Raises RunnerError with a useful message — these failures usually mean
    the image was built wrong or the package isn't installed.
    """
    module_path, func_name = _parse_entrypoint_spec(spec)
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise RunnerError(
            f"Could not import module {module_path!r} for entrypoint {spec!r}: {exc}"
        ) from exc

    try:
        func = getattr(module, func_name)
    except AttributeError as exc:
        raise RunnerError(
            f"Module {module_path!r} has no attribute {func_name!r} (entrypoint {spec!r})"
        ) from exc

    if not callable(func):
        raise RunnerError(f"Entrypoint {spec!r} resolved to a non-callable: {type(func).__name__}")

    return cast(Callable[[dict[Any, Any], dict[Any, Any]], dict[Any, Any]], func)


def resolve_optional_attr(spec: str, attr: str) -> Callable[..., Any] | None:
    """Look up an *optional* attribute on the entrypoint's module.

    Used to discover a tool-supplied ``parse(file_path, params)`` sitting
    alongside ``run``. Returns ``None`` when the module doesn't expose the
    attribute — never raises for that case.
    """
    module_path, _ = _parse_entrypoint_spec(spec)
    try:
        module = importlib.import_module(module_path)
    except ImportError:
        return None
    candidate = getattr(module, attr, None)
    return candidate if callable(candidate) else None


def _preprocess_inputs(
    inputs: dict[str, Any],
    params: dict[str, Any],
    tool_parse: Callable[..., Any] | None,
) -> dict[str, Any]:
    """Turn ``{field}_file`` paths into a parsed Python value under ``{field}``.

    The worker writes one ``{field}_file`` entry per typed-pointer input
    (paste / upload / dataset) and a matching ``{field}_source`` sidecar
    with ``{"type", "content_type"}``. Here we:

    1. Pick a parser for each file — the tool's own ``parse(file_path,
       params)`` if it provides one, otherwise
       :func:`techneos_tool_runtime.parsers.parse` driven by ``input_kind``
       (which the tool author sets in ``input_schema``; we look it up
       from the sidecar).
    2. Replace ``inputs[{field}_file]`` with ``inputs[{field}] = parsed``.
    3. If ``params["standardize"]`` is truthy and the value is a
       ``list[dict]`` of SMILES rows, run it through the standardizer
       and record dropped rows under ``inputs["_standardization_errors"]``.

    The result has the same shape paste mode used to produce — tools
    don't need to know which source provided the data.
    """
    from techneos_tool_runtime import kinds

    result = dict(inputs)
    errors: dict[str, list[dict[str, str]]] = {}

    # ``_input_kind`` is the tool-wide kind the worker copied from the
    # tool version's input_schema. A single tool consumes one canonical
    # input shape (e.g. SMILES_LIST), so the same kind applies to every
    # data file we preprocess in this run. Legacy tools that haven't
    # declared a kind fall through to the registry's default
    # (SMILES_LIST). An *explicit but unknown* kind is a hard error —
    # this can only happen via DB rewrite or runtime downgrade after
    # registration, and silently dispatching to the wrong parser would
    # produce confusing failures inside the tool.
    raw_kind = result.get("_input_kind")
    if raw_kind is None:
        spec: kinds.KindSpec | None = kinds.require(kinds.InputKind.SMILES_LIST)
    else:
        spec = kinds.resolve(raw_kind)
        if spec is None:
            registered = sorted(k.value for k in kinds.REGISTRY)
            raise RunnerError(
                f"inputs.json declared input_kind={raw_kind!r}, which is not "
                f"in this runtime's registry. Registered kinds: {registered}. "
                "Either upgrade techneos-tool-runtime to a version that supports "
                f"{raw_kind!r}, or re-register the tool with a supported kind."
            )
    # Non-None here: the None branch above raises, the other assigns a KindSpec.
    assert spec is not None
    input_kind = spec.kind.value

    for key in list(result.keys()):
        if not key.endswith("_file"):
            continue
        field = key[: -len("_file")]
        file_path = result[key]
        if not isinstance(file_path, str):
            continue

        source = result.get(f"{field}_source") or {}
        if not isinstance(source, dict):
            source = {}
        content_type = source.get("content_type")
        field_params = params.get(field) if isinstance(params.get(field), dict) else {}

        if tool_parse is not None:
            logger.info("Using tool-supplied parse() for %s", field)
            try:
                parsed = tool_parse(file_path, params)
            except TypeError:
                # Allow keyword-style signatures too.
                parsed = tool_parse(file_path=file_path, params=params)
        else:
            parsed = parsers.parse(
                file_path,
                input_kind=input_kind,
                content_type=content_type,
                params={**(field_params or {})},
            )

        # Standardization is opt-in via params and gated by the kind —
        # only kinds whose registry entry declares
        # supports_standardization=True honour the params["standardize"]
        # block. (RDKit standardization is meaningless for, say, a
        # protein sequence.)
        std_cfg = params.get("standardize")
        if std_cfg and spec is not None and spec.supports_standardization:
            kept, dropped = standardizers.apply(parsed, std_cfg)
            parsed = kept
            if dropped:
                errors[field] = dropped

        result[field] = parsed

    if errors:
        result["_standardization_errors"] = errors
    return result


def write_error(work_dir: WorkDir, error: dict[str, Any]) -> None:
    """Write a structured error to output/error.json. Best-effort."""
    try:
        work_dir.ensure()
        (work_dir.output_dir / "error.json").write_text(json.dumps(error, indent=2))
    except Exception:
        logger.exception("Failed to write error.json")


def run_tool(
    entrypoint_spec: str,
    work_dir: WorkDir | None = None,
) -> dict[str, Any]:
    """Drive a single tool invocation. Returns the result dict.

    Raises whatever the tool raises; the CLI wrapper turns exceptions into
    structured exits. Kept separate from main() so tests can exercise the
    happy path without subprocess overhead.
    """
    wd = work_dir or WorkDir.from_env()
    wd.ensure()

    from techneos_tool_runtime.s3_sync import download_work_dir, s3_sync_enabled

    if s3_sync_enabled():
        download_work_dir(wd.root)

    inputs = read_inputs(wd)
    params = read_params(wd)

    logger.info(
        "Invoking entrypoint %s with %d input key(s), %d param key(s)",
        entrypoint_spec,
        len(inputs),
        len(params),
    )

    func = resolve_entrypoint(entrypoint_spec)
    tool_parse = resolve_optional_attr(entrypoint_spec, "parse")
    inputs = _preprocess_inputs(inputs, params, tool_parse)
    result = func(inputs, params)

    if not isinstance(result, dict):
        raise RunnerError(
            f"Tool {entrypoint_spec!r} returned {type(result).__name__}, expected dict"
        )

    write_result(result, wd)
    logger.info("Wrote result.json (%d top-level keys)", len(result))

    from techneos_tool_runtime.s3_sync import s3_sync_enabled, upload_outputs

    if s3_sync_enabled():
        upload_outputs(wd.root)

    return result


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns an exit code."""
    logging.basicConfig(
        level=os.environ.get("TECHNEOS_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        prog="techneos-tool-runner",
        description="Generic runner for TechneOS tools.",
    )
    parser.add_argument(
        "--entrypoint",
        default=os.environ.get("ENTRYPOINT_SPEC", ""),
        help="Tool entry point as 'module.path:function'. Defaults to $ENTRYPOINT_SPEC.",
    )
    parser.add_argument(
        "--work-dir",
        default=os.environ.get("TECHNEOS_WORK_DIR", ""),
        help="Working directory containing inputs.json/params.json. "
        "Defaults to $TECHNEOS_WORK_DIR or /work.",
    )
    args = parser.parse_args(argv)

    if not args.entrypoint:
        print(  # noqa: T201 — CLI usage error to stderr
            "error: --entrypoint or $ENTRYPOINT_SPEC is required",
            file=sys.stderr,
        )
        return 2

    wd = WorkDir(root=Path(args.work_dir)) if args.work_dir else WorkDir.from_env()

    try:
        run_tool(args.entrypoint, work_dir=wd)
    except RunnerError as exc:
        logger.error("Runner error: %s", exc)
        write_error(wd, {"type": "runner_error", "message": str(exc)})
        return 3
    except Exception as exc:
        logger.exception("Tool raised an exception")
        write_error(
            wd,
            {
                "type": exc.__class__.__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            },
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
