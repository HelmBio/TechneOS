"""Aggregate the downstream services' OpenAPI schemas into the gateway's docs.

The gateway forwards every ``/api/v1/*`` request to a backend service through a
single catch-all proxy, so its own generated schema documents nothing useful. To
give ``/docs`` the real, per-resource API, this module fetches each service's
``/openapi.json`` and merges it into the gateway schema:

- component **schemas are namespaced** per service (``Tools``/``Pipelines``/…) so
  that identically-named models (``PaginatedResponse``, ``TokenPayload``, …)
  from different services don't collide, and every ``$ref`` is rewritten to match;
- the service paths already carry the ``/api/v1`` prefix, so they line up with the
  gateway's proxy routes and merge in as-is;
- the result is **cached** after the first build and **resilient** — a service
  that is down or unreachable is skipped, never breaking the gateway's own docs.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse

from core.auth.openapi import annotate_schema_requirements
from core.config import get_settings

logger = logging.getLogger(__name__)

# How long to wait on a single service's /openapi.json before giving up on it.
_FETCH_TIMEOUT = 5.0

_HTTP_METHODS = ("get", "post", "put", "patch", "delete", "options", "head")

# Sentinel owner for tags on the gateway's own routes (not a backend service).
_GATEWAY_OWNER = ""

# Past this many callers a "Used by" list stops informing and just adds noise
# (HTTPValidationError is reachable from ~every operation), so show a count.
_MAX_USAGE_LINKS = 8

# The one auth scheme worth exercising interactively is the Bearer JWT. "HTTPBearer"
# reuses the name the backend services already reference in their per-operation
# security, so those references resolve to this definition. (The gateway also
# accepts an X-API-Key, but a key can only be minted while already authenticated,
# so it adds nothing to the "Try it out" flow and is left out of the docs.)
_SECURITY_SCHEMES = {
    "HTTPBearer": {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": (
            "JWT access token. To get one:\n\n"
            "- **Email / password:** run `POST /api/v1/auth/login` below and copy the "
            "`access_token` from the response.\n"
            "- **Google / GitHub (SSO):** sign in through the portal, then copy "
            "`techneos_access_token` from the browser's Local Storage "
            "(DevTools → Application → Local Storage). SSO logins are re-issued as a "
            "local JWT, so this works the same for every sign-in method."
        ),
    },
}


def _service_urls() -> dict[str, str]:
    """Backend service name -> base URL. The name doubles as the schema
    namespace prefix (title-cased) and the OpenAPI tag group."""
    s = get_settings()
    return {
        "auth": s.auth_service_url,
        "datasets": s.dataset_service_url,
        "tools": s.tool_service_url,
        "tasks": s.task_service_url,
        "pipelines": s.pipeline_service_url,
        "agents": s.agent_service_url,
        "notifications": s.notification_service_url,
        "apps": s.app_service_url,
    }


def _rewrite_refs(node: Any, resolve: Callable[[str], str]) -> Any:
    """Recursively rewrite ``#/components/schemas/X`` refs through ``resolve``.
    Mutates and returns ``node`` in place (the input is a throwaway document)."""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            node["$ref"] = f"#/components/schemas/{resolve(ref.rsplit('/', 1)[1])}"
        for value in node.values():
            _rewrite_refs(value, resolve)
    elif isinstance(node, list):
        for item in node:
            _rewrite_refs(item, resolve)
    return node


def _referenced_names(node: Any, sink: set[str]) -> set[str]:
    """Collect every schema name referenced anywhere under ``node``."""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            sink.add(ref.rsplit("/", 1)[1])
        for value in node.values():
            _referenced_names(value, sink)
    elif isinstance(node, list):
        for item in node:
            _referenced_names(item, sink)
    return sink


def _shared_schema_names(docs: dict[str, dict[str, Any]]) -> set[str]:
    """Names that can keep their bare, un-prefixed form.

    A name is shared when every service defining it defines it *identically* —
    which covers both the common case (only one service has it) and the genuinely
    duplicated ones (FastAPI's ValidationError, core's PaginatedResponse). Only a
    name carrying different bodies in different services needs a service prefix.

    A shared schema must also only reference other shared schemas: if it pointed at
    a name that gets prefixed per service, its rewritten body would differ per
    service and merging it would silently bind one service's model to another's.
    Demote those until the set is stable.
    """
    bodies: dict[str, dict[str, str]] = defaultdict(dict)
    for service, doc in docs.items():
        for name, body in (doc.get("components", {}).get("schemas", {})).items():
            bodies[name][service] = json.dumps(body, sort_keys=True)

    shared = {name for name, per_service in bodies.items() if len(set(per_service.values())) == 1}

    changed = True
    while changed:
        changed = False
        for name in sorted(shared):
            for doc in docs.values():
                body = (doc.get("components", {}).get("schemas", {})).get(name)
                if body is None:
                    continue
                if _referenced_names(body, set()) - shared:
                    shared.discard(name)
                    changed = True
                    break
    return shared


def _fetch(url: str) -> dict[str, Any] | None:
    """Fetch and parse a service's ``/openapi.json``; return ``None`` on any
    failure so an unreachable service is simply skipped."""
    try:
        resp = httpx.get(url, timeout=_FETCH_TIMEOUT)
        resp.raise_for_status()
        doc = resp.json()
        return doc if isinstance(doc, dict) else None
    except Exception as exc:
        # Any failure (connection refused, timeout, bad JSON) means "skip this
        # service" — a downstream service being unavailable must never break the
        # gateway's own docs.
        logger.warning("OpenAPI aggregation: skipping %s (%s)", url, exc)
        return None


def _annotate_schema_usage(schema: dict[str, Any]) -> None:
    """Append a "Used by" line to each schema, linking the operations using it.

    Swagger's Schemas section gives no way back to the endpoints a model belongs
    to. Walk each operation's refs transitively (a model reached only through
    another model still belongs to that endpoint) and note the callers on the
    schema, deep-linked so they are clickable. Schemas used almost everywhere
    (HTTPValidationError and friends) get a count instead of a useless wall of
    links.
    """
    schemas: dict[str, Any] = schema.get("components", {}).get("schemas", {})
    if not schemas:
        return
    nested = {name: _referenced_names(body, set()) for name, body in schemas.items()}
    usage: dict[str, set[tuple[str, str | None]]] = defaultdict(set)

    for path, item in schema.get("paths", {}).items():
        for method, operation in item.items():
            if method.lower() not in _HTTP_METHODS or not isinstance(operation, dict):
                continue
            reached: set[str] = set()
            stack = list(_referenced_names(operation, set()))
            while stack:
                name = stack.pop()
                if name in reached:
                    continue
                reached.add(name)
                stack.extend(nested.get(name, ()))
            tags = operation.get("tags") or []
            operation_id = operation.get("operationId")
            anchor = f"#/{tags[0]}/{operation_id}" if tags and operation_id else None
            for name in reached:
                usage[name].add((f"{method.upper()} {path}", anchor))

    for name, callers in usage.items():
        body = schemas.get(name)
        if not isinstance(body, dict):
            continue
        if len(callers) > _MAX_USAGE_LINKS:
            note = f"**Used by** {len(callers)} operations."
        else:
            links = [
                f"[`{label}`]({anchor})" if anchor else f"`{label}`"
                for label, anchor in sorted(callers)
            ]
            note = "**Used by:** " + ", ".join(links)
        body["description"] = f"{body.get('description') or ''}\n\n{note}".strip()


def build_gateway_openapi(app: FastAPI) -> dict[str, Any]:
    """Build the merged schema: the gateway's own routes plus every reachable
    service's namespaced paths and schemas."""
    schema: dict[str, Any] = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    paths: dict[str, Any] = schema.setdefault("paths", {})
    components = schema.setdefault("components", {})
    schemas: dict[str, Any] = components.setdefault("schemas", {})

    # Which backend owns each tag, so the docs can label every section with the
    # service behind it. Seeded with the gateway's own tags (paths holds only the
    # gateway's routes until the merge below).
    tag_owner: dict[str, str] = {}
    for item in paths.values():
        for method, operation in item.items():
            if method.lower() in _HTTP_METHODS and isinstance(operation, dict):
                for tag in operation.get("tags") or []:
                    tag_owner.setdefault(tag, _GATEWAY_OWNER)

    # Fetch everything first: whether a schema name needs a service prefix can only
    # be judged once every service's definition of it is in hand.
    docs: dict[str, dict[str, Any]] = {}
    for name, base_url in _service_urls().items():
        doc = _fetch(f"{base_url.rstrip('/')}/openapi.json")
        if doc:
            docs[name] = doc
    shared = _shared_schema_names(docs)

    for name, doc in docs.items():
        prefix = name.title().replace("-", "")

        def resolve(schema_name: str, _prefix: str = prefix) -> str:
            return schema_name if schema_name in shared else f"{_prefix}{schema_name}"

        for schema_name, schema_def in (doc.get("components", {}).get("schemas", {})).items():
            schemas[resolve(schema_name)] = _rewrite_refs(schema_def, resolve)

        for path, item in doc.get("paths", {}).items():
            _rewrite_refs(item, resolve)
            for method, operation in item.items():
                if method.lower() in _HTTP_METHODS:
                    # Group under the service name unless the service already
                    # tagged the operation more specifically.
                    operation.setdefault("tags", [name])
                    for tag in operation.get("tags") or []:
                        tag_owner.setdefault(tag, name)
            paths.setdefault(path, item)

    # Advertise the gateway's auth so "Try it out" can send a token. Applied
    # globally, then cleared on the endpoints the gateway leaves unauthenticated
    # (health/docs, the auth handlers, and client distribution) so their lock
    # icons stay accurate. Mirrors the middleware's own test, prefixes included —
    # matching only the exact paths would leave a lock on endpoints that take no
    # token, which is the misdirection the lock icon exists to prevent.
    from gateway.middleware.auth import AUTH_PATHS, PUBLIC_PATHS

    components.setdefault("securitySchemes", {}).update(_SECURITY_SCHEMES)
    schema["security"] = [{"HTTPBearer": []}]
    for path, item in paths.items():
        if not (path in PUBLIC_PATHS or path in AUTH_PATHS):
            continue
        for method, operation in item.items():
            if method.lower() in _HTTP_METHODS and isinstance(operation, dict):
                operation["security"] = []

    # Label every section with the service behind it, ordered so that a service's
    # sections sit together (Swagger renders tags in this order).
    schema["tags"] = [
        {
            "name": tag,
            "description": (
                "Served by the API gateway itself."
                if owner == _GATEWAY_OWNER
                else f"Served by the `{owner}` service."
            ),
        }
        for tag, owner in sorted(tag_owner.items(), key=lambda kv: (kv[1], kv[0]))
    ]

    # Service paths arrive already annotated with their required permission/role;
    # annotate the gateway's *own* routes (e.g. the superuser-gated admin ones) too.
    annotate_schema_requirements(schema, app)

    # Link each schema back to the operations that use it (last: it reads the
    # merged paths, and the operationIds the links point at).
    _annotate_schema_usage(schema)

    # Swagger lists schemas in key order, which so far has been the order services
    # happened to be merged in. Sort them: the names are resource-prefixed
    # (AgentCreate/AgentResponse/AgentUpdate, ToolRunCreate/ToolRunResponse), so
    # alphabetical also groups each resource's models together.
    components["schemas"] = dict(sorted(schemas.items(), key=lambda kv: kv[0].lower()))

    return schema


def install_openapi(app: FastAPI) -> None:
    """Override ``app.openapi`` with a cached aggregating builder. The build is
    lazy (first ``/openapi.json`` or ``/docs`` request) so backend services
    don't need to be up at gateway startup."""
    cache: dict[str, dict[str, Any]] = {}

    def _aggregated_openapi() -> dict[str, Any]:
        if "schema" not in cache:
            cache["schema"] = build_gateway_openapi(app)
        return cache["schema"]

    app.openapi = _aggregated_openapi  # type: ignore[method-assign]


# Header tweaks: Swagger's stock header burns ~340px before the first section
# (the info block alone carries 50px margins top and bottom). Tighten it, put the
# collapse/expand toggles on the same row as the auth button, and relabel that
# button "Authenticate". The relabel is done in CSS rather than by rewriting the
# node's text so it survives React re-rendering the button (e.g. on auth state
# change).
_HEADER_TWEAKS = """
<style>
  .swagger-ui .info { margin: 14px 0 0; }
  .swagger-ui .information-container { padding-bottom: 0; }
  /* hgroup carries margin-bottom:20px and — now that the description lives inside
     it — is .info's last child, so that margin collapses out through .info and
     .information-container (neither has padding or a border to contain it) and
     reappears as a gap above the auth row. Drop it so the row's own padding is
     what sets the spacing. */
  .swagger-ui .info hgroup.main { margin-bottom: 0; }
  /* Strip Swagger's full-bleed white card + shadow. The rule must NOT live here:
     .scheme-container has no max-width, while sections sit inside
     .wrapper{max-width:1460px} — so above 1460 a rule here runs wider than the
     section separators (identical below it, which makes the bug easy to miss). */
  .swagger-ui .scheme-container {
    background: transparent;
    box-shadow: none;
    margin: 0 0 5px;
    padding: 0;
  }
  /* The auth row is styled as a section row: auth button left, expand-all chevron
     right, and the separator underneath. The rule lives here because .auth-wrapper
     fills .schemes.wrapper's content box — the same max-width-capped, 20px-inset
     box as .opblock-tag — so the two rules match at any window width. Swagger
     ships .auth-wrapper as a shrink-to-fit box its parent right-aligns, hence the
     widening; the padding mirrors .opblock-tag's so the columns line up too. */
  .swagger-ui .scheme-container .schemes .auth-wrapper {
    flex: 1 1 auto;
    justify-content: space-between;
    align-items: center;
    /* Symmetric vertical padding: equal breathing room above and below the row. */
    padding: 8px 20px 8px 10px;
    border-bottom: 1px solid rgba(59, 65, 81, .3);
  }
  .swagger-ui .btn.authorize span { font-size: 0; }
  .swagger-ui .btn.authorize span::after { content: "Authenticate"; font-size: 14px; }
  /* ...and the dialog it opens, which otherwise still says "Authorize". These
     labels are bare text nodes (no span to target), so zero the element's font
     and re-inject through ::after. Scoping the button rule to .authorize keeps
     the rename off the Logout button it becomes once signed in — that one drops
     the class. */
  .swagger-ui .dialog-ux .modal-ux-header h3 { font-size: 0; }
  .swagger-ui .dialog-ux .modal-ux-header h3::after {
    content: "Authentication";
    font-size: 20px;
  }
  .swagger-ui .dialog-ux .btn.modal-btn.auth.authorize { font-size: 0; }
  .swagger-ui .dialog-ux .btn.modal-btn.auth.authorize::after {
    content: "Authenticate";
    font-size: 14px;
  }
  .swagger-ui [data-docs-toggle] svg.arrow { transition: transform .2s; }
  /* Spec link and description share one line, separated by a dot. */
  .swagger-ui .info hgroup.main .link,
  .swagger-ui .info .info__description { display: inline-block; vertical-align: baseline; }
  /* The whole chain has to go inline — the markdown wrapper is a block and would
     otherwise break the line. */
  .swagger-ui .info .info__description .renderedMarkdown,
  .swagger-ui .info .info__description p { display: inline; margin: 0; }
  .swagger-ui .info .info__description::before {
    content: "·";
    margin: 0 8px;
    color: rgba(59, 65, 81, .6);
  }
</style>
<script>
(function () {
  function eachTag(open) {
    var sys = ui.getSystem();
    sys.specSelectors.taggedOperations().keySeq().forEach(function (tag) {
      sys.layoutActions.show(["operations-tag", tag], open);
    });
  }
  function anyExpanded() { return document.querySelectorAll(".opblock").length > 0; }
  // Clone a real section chevron so the master toggle is identical to the
  // per-section ones rather than a hand-drawn lookalike.
  function makeToggle(proto) {
    var btn = proto.cloneNode(true);
    btn.setAttribute("data-docs-toggle", "");
    var svg = btn.querySelector("svg");
    function sync(open) {
      if (svg) { svg.style.transform = open ? "rotate(180deg)" : "rotate(0deg)"; }
      btn.setAttribute("aria-expanded", open ? "true" : "false");
      btn.title = open ? "Collapse all sections" : "Expand all sections";
    }
    btn.onclick = function () {
      var open = !anyExpanded();
      eachTag(open);
      sync(open);
    };
    sync(anyExpanded());
    return btn;
  }
  // The spec link sits in the title hgroup and the description is a block below
  // it; move the description up beside the link so the two share one line.
  function combineHeaderLines() {
    var link = document.querySelector(".info hgroup.main .link");
    var desc = document.querySelector(".info .info__description");
    if (link && desc && desc.parentNode !== link.parentNode) {
      link.parentNode.appendChild(desc);
    }
  }
  function mount() {
    var wrapper = document.querySelector(".auth-wrapper");
    var scheme = document.querySelector(".scheme-container");
    var proto = document.querySelector(".opblock-tag .expand-operation");
    // `ui` is a top-level `const` in Swagger's own script: it lives in the global
    // lexical scope, NOT on `window` — so test the binding, not window.ui.
    if (!wrapper || !scheme || !proto || typeof ui === "undefined") {
      return setTimeout(mount, 100);
    }
    combineHeaderLines();
    wrapper.appendChild(makeToggle(proto));
    // React re-renders this container (authorizing swaps the lock icon) and drops
    // our toggle with it — put it back when that happens.
    new MutationObserver(function () {
      var w = document.querySelector(".auth-wrapper");
      var p = document.querySelector(".opblock-tag .expand-operation");
      if (w && p && !w.querySelector("[data-docs-toggle]")) { w.appendChild(makeToggle(p)); }
    }).observe(scheme, { childList: true, subtree: true });
  }
  mount();
})();
</script>
"""


def swagger_ui_html(app: FastAPI) -> HTMLResponse:
    """Swagger UI, with two gateway-specific tweaks.

    1. "Try it out" must NOT ride the session cookie. /docs and the API are
       same-origin, so the browser would otherwise attach the login cookie to
       every try-it-out request — making an un-Authorized (open lock) call
       succeed and misrepresenting what the API requires. A request interceptor
       forces ``credentials: 'omit'`` so a call is authenticated only by a token
       pasted into Authorize, and the lock icons mean what they say.
    2. The page opens collapsed with Collapse/Expand-all controls, so ~30
       sections across eight services are a readable index rather than a wall.
    """
    rendered = get_swagger_ui_html(
        openapi_url=app.openapi_url or "/openapi.json",
        title=f"{app.title} — Swagger UI",
        swagger_ui_parameters={"docExpansion": "none"},
    )
    html = bytes(rendered.body).decode()
    html = html.replace(
        "SwaggerUIBundle({",
        "SwaggerUIBundle({ requestInterceptor: (req) => { req.credentials = 'omit'; return req; },",
        1,
    )
    html = html.replace("</body>", f"{_HEADER_TWEAKS}</body>", 1)
    return HTMLResponse(html)
