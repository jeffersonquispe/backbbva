#!/usr/bin/env python3
"""Build the ARIA project knowledge graph used for the chat agent's graph-RAG.

Sources (nothing is fetched from a running system):
  * frontend  — ``scripts/ts_scan.mjs`` (TypeScript compiler API, syntax only):
                routes, components, JSX usage, API-function references, labels.
  * backend   — Python ``ast`` over the API routers, use cases, ports and
                adapters, plus ``ROLE_PERMISSIONS``.
  * curated   — ``scripts/project_graph_curated.json``: view/component
                descriptions, user tasks (ordered steps) and domain concepts.
                Every id it references is validated; a dangling id fails the
                build so the curated layer cannot rot silently.

Writes ``src/infrastructure/agents/project_graph/project_graph.json``.

Node kinds   view, component, action, api_call, endpoint, use_case, port,
             adapter, resource, asset, role, permission, task, concept
Relations    renders, offers, calls, requests, handled_by, belongs_to,
             navigates_to, uses_asset, can_open, grants, requires, uses_port,
             implemented_by, starts_at, involves (ordered), manifested_in

Run: ``make project-graph`` · stale check: ``make project-graph-check``.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
DEFAULT_FRONTEND = BACKEND.parent / "frontend_mockup"
OUTPUT = BACKEND / "src/infrastructure/agents/project_graph/project_graph.json"
CURATED = SCRIPTS / "project_graph_curated.json"

API_PREFIX = "/api/v0"
MAX_KEYWORDS = 40

CONST_PATH_RE = re.compile(
    r"""^(?:export )?const ([A-Za-z_]+) = ["'`](/api/[^"'`]*)["'`]""", re.M
)
LOCAL_CONST_RE = re.compile(r"""const (\w+) = `(/api/[^`]*)`""")
API_FETCH_RE = re.compile(
    r"""(?:apiFetch(?:<[^>]*>)?|\bfetch)\(\s*(?P<url>`[^`]*`|"[^"]*"|'[^']*')(?P<rest>.{0,240}?)\)\s*;?""",
    re.S,
)
METHOD_RE = re.compile(r"""method:\s*["'](GET|POST|PUT|PATCH|DELETE)["']""")
FUNC_RE = re.compile(r"""export\s+(?:async\s+)?function\s+(?P<name>[A-Za-z0-9_]+)""")
USE_CASE_RE = re.compile(r"\b([A-Z][A-Za-z0-9]+UseCase)\b")
GET_USE_CASE_RE = re.compile(r"\bget_([a-z0-9_]+)_use_case\b")
ROUTE_DECORATORS = {"get", "post", "put", "patch", "delete"}


def slug(value: str) -> str:
    text = unicodedata.normalize("NFKD", value)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def humanize(name: str) -> str:
    words = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    return re.sub(r"[_\-.]+", " ", words).strip()


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


VERB_GLOSS = {
    "create": "crear crea", "list": "listar lista ver", "get": "obtener consultar ver",
    "update": "actualizar editar modificar", "delete": "borrar eliminar", "add": "agregar añadir",
    "remove": "quitar retirar", "import": "importar cargar", "upload": "subir cargar",
    "download": "descargar", "train": "entrenar", "activate": "activar", "approve": "aprobar",
    "start": "iniciar arrancar", "stop": "detener", "pause": "pausar", "resume": "reanudar",
    "preview": "previsualizar", "score": "puntuar", "review": "revisar", "take": "tomar",
    "release": "liberar", "resolve": "resolver", "cancel": "cancelar", "request": "solicitar",
    "save": "guardar", "propose": "proponer", "reject": "rechazar", "analyze": "analizar",
    "extract": "extraer", "check": "verificar", "test": "probar", "search": "buscar",
    "query": "consultar buscar", "confirm": "confirmar", "send": "enviar", "generate": "generar",
    "promote": "promover", "restore": "restaurar", "export": "exportar", "curate": "curar",
    "ingest": "ingerir cargar", "validate": "validar", "evaluate": "evaluar",
}  # fmt: skip
HTTP_GLOSS = {
    "POST": "crear crea agregar enviar",
    "GET": "consultar listar obtener ver",
    "PATCH": "actualizar editar modificar",
    "PUT": "actualizar reemplazar",
    "DELETE": "borrar eliminar quitar",
}


def spanish_gloss(name: str, http_method: str = "") -> list[str]:
    """Spanish verbs for an English identifier, so Spanish questions match it."""
    words = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name).replace("_", " ").lower().split()
    gloss = [VERB_GLOSS[w] for w in words if w in VERB_GLOSS]
    if http_method:
        gloss.append(HTTP_GLOSS.get(http_method, ""))
    return [" ".join(part for part in gloss if part)] if any(gloss) else []


def snake_to_camel(value: str) -> str:
    return "".join(part.capitalize() for part in value.split("_"))


class Graph:
    def __init__(self) -> None:
        self.nodes: dict[str, dict] = {}
        self.edges: dict[tuple[str, str, str], dict] = {}

    def node(
        self,
        node_id: str,
        kind: str,
        name: str,
        description: str = "",
        keywords: list[str] | None = None,
        **attrs: str,
    ) -> str:
        current = self.nodes.setdefault(
            node_id,
            {
                "id": node_id,
                "kind": kind,
                "name": name,
                "description": "",
                "keywords": [],
                "attrs": {},
            },
        )
        if description and not current["description"]:
            current["description"] = description
        for word in keywords or []:
            if word not in current["keywords"] and len(current["keywords"]) < MAX_KEYWORDS:
                current["keywords"].append(word)
        current["attrs"].update({k: v for k, v in attrs.items() if v})
        return node_id

    def edge(
        self, source: str, target: str, relation: str, position: int | None = None
    ) -> None:
        if source == target or source not in self.nodes or target not in self.nodes:
            return
        item = {"source": source, "target": target, "relation": relation}
        if position is not None:
            item["position"] = position
        self.edges[(source, target, relation)] = item


# --------------------------------------------------------------------------
# Frontend
# --------------------------------------------------------------------------


def run_ts_scan(frontend: Path) -> dict[str, dict]:
    result = subprocess.run(
        ["node", str(SCRIPTS / "ts_scan.mjs"), str(frontend)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"ts_scan failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def resolve_import(src: str, importer: str, files: set[str]) -> str | None:
    if src.startswith("@/"):
        base = src[2:]
    elif src.startswith("."):
        stack: list[str] = []
        for part in (Path(importer).parent / src).as_posix().split("/"):
            if part == "..":
                if stack:
                    stack.pop()
            elif part != ".":
                stack.append(part)
        base = "/".join(stack)
    else:
        return None
    for suffix in (".tsx", ".ts", "/index.tsx", "/index.ts"):
        if base + suffix in files:
            return base + suffix
    return None


def build_api_calls(graph: Graph, frontend: Path) -> dict[str, str]:
    api_dir = frontend / "src/lib/api"
    functions: dict[str, str] = {}
    for path in sorted(api_dir.glob("*.functions.ts")):
        text = path.read_text(encoding="utf-8")
        constants = dict(CONST_PATH_RE.findall(text))
        matches = list(FUNC_RE.finditer(text))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            body = text[match.end() : end]
            fetch = API_FETCH_RE.search(body)
            if not fetch:
                continue  # helper, not a network call
            name = match.group("name")
            url = fetch.group("url")[1:-1].replace("${API_BASE}", "")
            local = dict(LOCAL_CONST_RE.findall(body))
            for const_name, const_value in {**constants, **local}.items():
                url = url.replace("${" + const_name + "}", const_value)
            method = METHOD_RE.search(fetch.group("rest"))
            http = method.group(1) if method else "GET"
            shown = re.sub(r"\$\{(?:qs|query|search|params)[^}]*\}?.*$", "", url)
            shown = re.sub(r"\$\{[^}]*\}", "{id}", shown)
            node_id = f"api:{path.stem.split('.')[0]}.{name}"
            graph.node(
                node_id,
                "api_call",
                name,
                f"{http} {shown}".strip(),
                spanish_gloss(name, http),
                http_method=http,
                url=url,
                file=path.relative_to(frontend / "src").as_posix(),
            )
            functions[name] = node_id
    return functions


def read_nav_labels(frontend: Path) -> dict[str, str]:
    sidebar = frontend / "src/components/AppSidebar.tsx"
    if not sidebar.is_file():
        return {}
    return {
        m.group(1): m.group(2)
        for m in re.finditer(
            r"""\{\s*to:\s*["'](/[^"']+)["']\s*,\s*label:\s*["']([^"']+)["']""",
            sidebar.read_text(encoding="utf-8"),
        )
    }


def build_frontend(graph: Graph, frontend: Path) -> None:
    scan = run_ts_scan(frontend)
    files = set(scan)
    api_functions = build_api_calls(graph, frontend)
    nav_labels = read_nav_labels(frontend)

    file_node: dict[str, str] = {}
    for relative, info in scan.items():
        if relative.startswith("routes/") and info["route"]:
            view_path = info["route"].rstrip("/") or "/"
            node_id = f"view:{view_path}"
            label = nav_labels.get(view_path)
            graph.node(
                node_id,
                "view",
                view_path,
                f"Vista «{label}»." if label else info["comment"],
                [label] if label else [],
                file=relative,
                label=label or "",
            )
            file_node[relative] = node_id
        elif relative.startswith("components/") and relative.endswith(".tsx"):
            node_id = "component:" + relative.removeprefix("components/").removesuffix(".tsx")
            graph.node(node_id, "component", Path(relative).stem, info["comment"], [],
                       file=relative)
            file_node[relative] = node_id

    public = frontend / "public"
    assets = {p.name: p for p in public.rglob("*") if p.is_file()} if public.is_dir() else {}

    for relative, node_id in file_node.items():
        info = scan[relative]
        used = set(info["jsx"]) | set(info["refs"])
        node = graph.nodes[node_id]
        graph.node(node_id, node["kind"], node["name"], keywords=info["texts"])
        for imported in info["imports"]:
            target = resolve_import(imported["src"], relative, files)
            if target is None:
                continue
            if target in file_node and target != relative:
                if used & set(imported["names"]):
                    graph.edge(node_id, file_node[target], "renders")
            elif target.startswith("lib/api/"):
                for name in imported["names"]:
                    if name in api_functions and name in used:
                        graph.edge(node_id, api_functions[name], "calls")
        for label in info["actions"]:
            action_id = f"action:{slug(label)}@{slug(node_id)}"
            graph.node(action_id, "action", label, f"Acción «{label}» en {node['name']}.",
                       [label], owner=node_id)
            graph.edge(node_id, action_id, "offers")
        for target_path in sorted(set(info["links"])):
            graph.edge(node_id, f"view:{target_path.rstrip('/') or '/'}", "navigates_to")
        source = (frontend / "src" / relative).read_text(encoding="utf-8")
        for asset_name, asset_path in assets.items():
            if asset_name in source:
                asset_id = f"asset:{asset_path.relative_to(public).as_posix()}"
                graph.node(asset_id, "asset", asset_name, f"Archivo estático {asset_name}.",
                           [humanize(asset_path.stem)], subtype="static")
                graph.edge(node_id, asset_id, "uses_asset")


# --------------------------------------------------------------------------
# Backend (Python ast)
# --------------------------------------------------------------------------


def parse(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return None


def first_paragraph(doc: str | None) -> str:
    return clean_text((doc or "").strip().split("\n\n")[0])[:220]


def collect_classes(root: Path) -> list[tuple[Path, ast.ClassDef]]:
    found: list[tuple[Path, ast.ClassDef]] = []
    for path in sorted(root.rglob("*.py")):
        module = parse(path)
        if module is not None:
            found.extend((path, n) for n in ast.walk(module) if isinstance(n, ast.ClassDef))
    return found


def annotation_names(node: ast.AST | None) -> set[str]:
    names: set[str] = set()
    for sub in ast.walk(node) if node is not None else []:
        if isinstance(sub, ast.Name):
            names.add(sub.id)
        elif isinstance(sub, ast.Attribute):
            names.add(sub.attr)
        elif isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            names.update(re.findall(r"[A-Za-z_]\w*", sub.value))
    return names


def enum_values(module: ast.Module, enum_name: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == enum_name:
            for stmt in node.body:
                if (
                    isinstance(stmt, ast.Assign)
                    and isinstance(stmt.targets[0], ast.Name)
                    and isinstance(stmt.value, ast.Constant)
                ):
                    values[stmt.targets[0].id] = str(stmt.value.value)
    return values


def role_permissions(backend: Path) -> dict[str, set[str]]:
    module = parse(backend / "src/application/ports/local_auth_port.py")
    if module is None:
        return {}
    roles = enum_values(module, "LocalRole")
    result: dict[str, set[str]] = {}
    for node in module.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "ROLE_PERMISSIONS"
            and isinstance(node.value, ast.Dict)
        ):
            for key, value in zip(node.value.keys, node.value.values, strict=False):
                if isinstance(key, ast.Attribute) and key.attr in roles:
                    result[roles[key.attr]] = {
                        c.value
                        for c in ast.walk(value)
                        if isinstance(c, ast.Constant) and isinstance(c.value, str)
                    }
    return result


def library_writer_roles(backend: Path) -> set[str]:
    module = parse(backend / "src/infrastructure/entrypoint/api/authorization.py")
    roles_module = parse(backend / "src/application/ports/local_auth_port.py")
    if module is None or roles_module is None:
        return set()
    roles = enum_values(roles_module, "LocalRole")
    for node in module.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "LIBRARY_WRITER_ROLES" for t in node.targets
        ):
            return {
                roles[a.attr]
                for a in ast.walk(node.value)
                if isinstance(a, ast.Attribute) and a.attr in roles
            }
    return set()


def frontend_role_nav(frontend: Path) -> tuple[dict[str, list[str]], dict[str, str]]:
    text = (frontend / "src/hooks/useRole.ts").read_text(encoding="utf-8")
    nav: dict[str, list[str]] = {}
    block = re.search(r"ROLE_NAV[^=]*=\s*\{(.*?)\n\};", text, re.S)
    if block:
        for match in re.finditer(r"(\w+):\s*\[(.*?)\]", block.group(1), re.S):
            nav[match.group(1)] = re.findall(r'"(/[^"]*)"', match.group(2))
    labels: dict[str, str] = {}
    label_block = re.search(r"ROLE_LABELS[^=]*=\s*\{(.*?)\};", text, re.S)
    if label_block:
        labels = dict(re.findall(r'(\w+):\s*"([^"]+)"', label_block.group(1)))
    return nav, labels


def permissions_in(expr: ast.AST, aliases: dict[str, set[str]]) -> set[str]:
    found: set[str] = set()
    for sub in ast.walk(expr):
        if (
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Name)
            and sub.func.id == "require_permission"
            and sub.args
            and isinstance(sub.args[0], ast.Constant)
        ):
            found.add(str(sub.args[0].value))
        elif isinstance(sub, ast.Name):
            if sub.id == "require_library_access":
                found.add("library_write")
            found |= aliases.get(sub.id, set())
    return found


def build_backend(graph: Graph, backend: Path) -> None:
    use_cases_root = backend / "src/application/use_cases"
    ports_root = backend / "src/application/ports"
    infra_root = backend / "src/infrastructure"

    use_case_classes = {
        cls.name: cls
        for _path, cls in collect_classes(use_cases_root)
        if cls.name.endswith("UseCase")
    }
    port_classes = {cls.name: cls for _p, cls in collect_classes(ports_root)}

    endpoint_patterns: list[tuple[list[str], str]] = []
    for path in sorted((infra_root / "entrypoint/api/routers").glob("*_router.py")):
        text = path.read_text(encoding="utf-8")
        module = parse(path)
        if module is None:
            continue
        aliases: dict[str, set[str]] = {}
        routers: dict[str, tuple[str, str, set[str]]] = {}
        for node in module.body:
            if not isinstance(node, ast.Assign) or not isinstance(node.targets[0], ast.Name):
                continue
            value = node.value
            name = node.targets[0].id
            if isinstance(value, ast.Call) and getattr(value.func, "id", "") == "APIRouter":
                prefix, tag = "", path.stem.removesuffix("_router")
                router_perms: set[str] = set()
                for kw in value.keywords:
                    if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                        prefix = str(kw.value.value)
                    elif kw.arg == "tags" and isinstance(kw.value, ast.List) and kw.value.elts:
                        first = kw.value.elts[0]
                        if isinstance(first, ast.Constant):
                            tag = str(first.value)
                    elif kw.arg == "dependencies":
                        router_perms |= permissions_in(kw.value, aliases)
                routers[name] = (prefix, tag, router_perms)
                graph.node(f"resource:{tag}", "resource", tag, f"Recurso de API «{tag}».",
                           [humanize(tag)], file=path.relative_to(backend).as_posix())
            else:
                perms = permissions_in(value, aliases)
                if perms:
                    aliases[name] = perms
        for func in (
            n for n in ast.walk(module) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
        ):
            route = next(
                (
                    d
                    for d in func.decorator_list
                    if isinstance(d, ast.Call)
                    and isinstance(d.func, ast.Attribute)
                    and d.func.attr in ROUTE_DECORATORS
                    and isinstance(d.func.value, ast.Name)
                    and d.func.value.id in routers
                ),
                None,
            )
            if route is None or not isinstance(route.func, ast.Attribute):
                continue
            router_name = route.func.value.id  # type: ignore[union-attr]
            prefix, tag, router_perms = routers[router_name]
            resource_id = f"resource:{tag}"
            method = route.func.attr.upper()
            sub_path = (
                str(route.args[0].value)
                if route.args and isinstance(route.args[0], ast.Constant)
                else ""
            )
            full = f"{API_PREFIX}{prefix}{sub_path}"
            endpoint_id = f"endpoint:{method} {full}"
            graph.node(endpoint_id, "endpoint", f"{method} {full}",
                       first_paragraph(ast.get_docstring(func)),
                       [humanize(func.name), *spanish_gloss(func.name, method)],
                       http_method=method, route=full)
            graph.edge(endpoint_id, resource_id, "belongs_to")
            perms = set(router_perms)
            for decorator in func.decorator_list:
                perms |= permissions_in(decorator, aliases)
            perms |= permissions_in(func.args, aliases)
            for permission in sorted(perms):
                graph.node(f"permission:{permission}", "permission", permission,
                           f"Permiso «{permission}».", [])
                graph.edge(endpoint_id, f"permission:{permission}", "requires")
            segment = ast.get_source_segment(text, func) or ""
            names = set(USE_CASE_RE.findall(segment))
            for helper in GET_USE_CASE_RE.findall(segment):
                candidate = snake_to_camel(helper) + "UseCase"
                if candidate in use_case_classes:
                    names.add(candidate)
            for use_case in sorted(names):
                cls = use_case_classes.get(use_case)
                use_case_id = graph.node(
                    f"use_case:{use_case}",
                    "use_case",
                    use_case,
                    first_paragraph(ast.get_docstring(cls)) if cls else "",
                    [
                        humanize(use_case.removesuffix("UseCase")),
                        *spanish_gloss(use_case.removesuffix("UseCase")),
                    ],
                )
                graph.edge(endpoint_id, use_case_id, "handled_by")
            endpoint_patterns.append((full.strip("/").split("/"), endpoint_id))

    link_api_calls(graph, endpoint_patterns)
    build_layers(graph, use_case_classes, port_classes, infra_root, backend)
    build_roles(graph, backend)


def link_api_calls(graph: Graph, endpoint_patterns: list[tuple[list[str], str]]) -> None:
    for node in list(graph.nodes.values()):
        if node["kind"] != "api_call":
            continue
        url = node["attrs"].get("url", "")
        if not url.startswith(API_PREFIX):
            continue
        normalized = re.sub(r"\$\{(?:query|qs|search|params).*$", "", url.split("?")[0])
        normalized = re.sub(r"\$\{[^}]*\}", "x", normalized)
        segments = normalized.strip("/").split("/")
        method = node["attrs"].get("http_method", "GET")
        for pattern, endpoint_id in endpoint_patterns:
            if not endpoint_id.startswith(f"endpoint:{method} "):
                continue
            if len(pattern) == len(segments) and all(
                a == b or a.startswith("{") or b == "x"
                for a, b in zip(pattern, segments, strict=False)
            ):
                graph.edge(node["id"], endpoint_id, "requests")
                break


def build_layers(
    graph: Graph,
    use_case_classes: dict[str, ast.ClassDef],
    port_classes: dict[str, ast.ClassDef],
    infra_root: Path,
    backend: Path,
) -> None:
    """use_case -uses_port-> port -implemented_by-> adapter (reachable only)."""
    used_ports: set[str] = set()
    for use_case_id in [n for n in graph.nodes if n.startswith("use_case:")]:
        cls = use_case_classes.get(graph.nodes[use_case_id]["name"])
        init = next(
            (s for s in (cls.body if cls else []) if isinstance(s, ast.FunctionDef) and s.name == "__init__"),
            None,
        )
        if init is None:
            continue
        for arg in [*init.args.args, *init.args.kwonlyargs]:
            for name in sorted(annotation_names(arg.annotation) & port_classes.keys()):
                port_id = graph.node(
                    f"port:{name}", "port", name,
                    first_paragraph(ast.get_docstring(port_classes[name])), [humanize(name)],
                )
                graph.edge(use_case_id, port_id, "uses_port")
                used_ports.add(name)
    for path, cls in collect_classes(infra_root):
        base_names = {b.id if isinstance(b, ast.Name) else getattr(b, "attr", "") for b in cls.bases}
        matched = (base_names & used_ports) or {
            port for port in used_ports if cls.name != port and cls.name.endswith(port)
        }
        for port in sorted(matched):
            adapter_id = graph.node(
                f"adapter:{cls.name}", "adapter", cls.name,
                first_paragraph(ast.get_docstring(cls)), [humanize(cls.name)],
                file=path.relative_to(backend).as_posix(),
            )
            graph.edge(f"port:{port}", adapter_id, "implemented_by")


def build_roles(graph: Graph, backend: Path) -> None:
    writers = library_writer_roles(backend)
    for role, granted in role_permissions(backend).items():
        role_id = graph.node(f"role:{role}", "role", role, f"Rol «{role}».", [humanize(role)])
        for permission in sorted(granted | ({"library_write"} if role in writers else set())):
            permission_id = graph.node(f"permission:{permission}", "permission", permission,
                                       f"Permiso «{permission}».", [])
            graph.edge(role_id, permission_id, "grants")


def build_role_navigation(graph: Graph, frontend: Path) -> None:
    nav, labels = frontend_role_nav(frontend)
    for role, paths in nav.items():
        role_id = graph.node(f"role:{role}", "role", role, f"Rol «{role}».", [])
        if role in labels:
            graph.node(role_id, "role", role, keywords=[labels[role]])
        for path in paths:
            graph.edge(role_id, f"view:{path}", "can_open")


# --------------------------------------------------------------------------
# Docs + curated layer
# --------------------------------------------------------------------------


def build_docs(graph: Graph, frontend: Path, backend: Path) -> None:
    for root, label in ((backend, "backend"), (frontend, "frontend")):
        docs = root / "docs"
        for path in sorted(docs.glob("*.md")) if docs.is_dir() else []:
            heading = next(
                (ln.lstrip("# ").strip()
                 for ln in path.read_text(encoding="utf-8").splitlines() if ln.startswith("#")),
                path.stem,
            )
            graph.node(f"asset:docs/{label}/{path.name}", "asset", path.name,
                       f"Documento {label}: {heading}", [heading], subtype="doc")


def resolve_ref(graph: Graph, ref: str) -> str | None:
    """Curated ids: exact node id, or ``action:<label>@<owner id>`` shorthand."""
    if ref in graph.nodes:
        return ref
    match = re.fullmatch(r"action:(.+)@((?:view|component):.+)", ref)
    if match:
        candidate = f"action:{slug(match.group(1))}@{slug(match.group(2))}"
        return candidate if candidate in graph.nodes else None
    return None


def apply_curated(graph: Graph, curated_path: Path) -> list[str]:
    if not curated_path.is_file():
        return []
    curated = json.loads(curated_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    for view_path, info in curated.get("views", {}).items():
        node = graph.nodes.get(f"view:{view_path}")
        if node is None:
            errors.append(f"curated view not found: {view_path}")
            continue
        node["description"] = info["description"]
        if info.get("label"):
            node["attrs"]["label"] = info["label"]
        for alias in info.get("aliases", []):
            if alias not in node["keywords"]:
                node["keywords"].append(alias)
    for key, info in curated.get("components", {}).items():
        node = graph.nodes.get(f"component:{key}")
        if node is None:
            errors.append(f"curated component not found: {key}")
            continue
        node["description"] = info["description"]
    for task in curated.get("tasks", []):
        node_id = graph.node(f"task:{task['id']}", "task", task["name"], task["description"],
                             task.get("aliases", []))
        if f"view:{task['view']}" not in graph.nodes:
            errors.append(f"task {task['id']}: view not found {task['view']}")
        else:
            graph.edge(node_id, f"view:{task['view']}", "starts_at")
        for position, ref in enumerate(task.get("steps", [])):
            resolved = resolve_ref(graph, ref)
            if resolved is None:
                errors.append(f"task {task['id']}: step not found {ref}")
            else:
                graph.edge(node_id, resolved, "involves", position)
    for concept in curated.get("concepts", []):
        node_id = graph.node(f"concept:{concept['id']}", "concept", concept["name"],
                             concept["description"], concept.get("aliases", []))
        for ref in concept.get("nodes", []):
            resolved = resolve_ref(graph, ref)
            if resolved is None:
                errors.append(f"concept {concept['id']}: node not found {ref}")
            else:
                graph.edge(node_id, resolved, "manifested_in")
    return errors


# --------------------------------------------------------------------------


def build(frontend: Path) -> tuple[Graph, list[str]]:
    graph = Graph()
    build_frontend(graph, frontend)
    build_backend(graph, BACKEND)
    build_role_navigation(graph, frontend)
    build_docs(graph, frontend, BACKEND)
    return graph, apply_curated(graph, CURATED)


def render(graph: Graph) -> str:
    payload = {
        "version": 2,
        "nodes": sorted(graph.nodes.values(), key=lambda n: n["id"]),
        "edges": sorted(
            graph.edges.values(), key=lambda e: (e["source"], e["target"], e["relation"])
        ),
    }
    return json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend", type=Path, default=DEFAULT_FRONTEND)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--check", action="store_true", help="fail if the committed file is stale")
    args = parser.parse_args()
    if not (args.frontend / "src").is_dir():
        print(f"frontend not found at {args.frontend}", file=sys.stderr)
        return 2
    graph, errors = build(args.frontend)
    if errors:
        print("\n".join(f"- {e}" for e in errors), file=sys.stderr)
        return 1
    rendered = render(graph)
    if args.check:
        current = args.output.read_text(encoding="utf-8") if args.output.is_file() else ""
        if current != rendered:
            print("project_graph.json is stale: run `make project-graph`", file=sys.stderr)
            return 1
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    kinds: dict[str, int] = defaultdict(int)
    for node in graph.nodes.values():
        kinds[node["kind"]] += 1
    rels: dict[str, int] = defaultdict(int)
    for edge in graph.edges.values():
        rels[edge["relation"]] += 1
    print(f"nodes={len(graph.nodes)} {dict(kinds)}")
    print(f"edges={len(graph.edges)} {dict(rels)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
