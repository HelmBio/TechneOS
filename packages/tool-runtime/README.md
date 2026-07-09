# techneos-tool-runtime

Shared runtime for TechneOS tools. Defines the single execution
contract that every tool implements, regardless of how it's delivered (pypi
package or Docker container).

## The contract

Every tool exposes one function:

```python
def run(inputs: dict, params: dict) -> dict:
    """
    inputs: resolved file paths and upstream artifact paths
            (e.g. {"dataset_file": "/work/input/zinc20.csv",
                   "upstream": {"prep_ligands": ["/work/input/upstream/prep_ligands/ligands.sdf"]}})
    params: step parameters from the pipeline / agent call
    returns: a JSON-serialisable dict that is written verbatim to /work/output/result.json
    """
```

Side-effect files (CSVs, PDFs, plots) are written via `write_artifact()`
helpers — never by reaching for `/output/` directly. The runtime is the
single source of truth for where artifacts go.

## How it runs

### Container tools

A container tool's image inherits from `techneos/tool-runtime` (installing any extra
system deps it needs) and sets one env var:

```dockerfile
FROM techneos/tool-runtime:1
COPY . /app
RUN pip install --no-cache-dir /app
ENV ENTRYPOINT_SPEC=dataset_profiler.core:run
# ENTRYPOINT inherited from base: ["python", "-m", "techneos_tool_runtime.runner"]
```

The worker writes `/work/inputs.json` and `/work/params.json` to a bind mount,
launches the container, and collects everything under `/work/output/`.

### Pypi tools

The worker pip-installs the package into the shared `techneos/tool-runtime`
image and invokes `techneos-tool-runner` the same way — same files, same output
layout. The only difference is *where the package code came from*.

## Module layout

- `runner.py` — generic entrypoint (`python -m techneos_tool_runtime.runner`)
- `io.py` — `write_artifact()`, `read_inputs()`, `read_params()`, and the
  `WorkDir` abstraction that gives tools a consistent view of input/output
  paths whether running in a container or in-process.
