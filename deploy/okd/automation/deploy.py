#!/usr/bin/env python3
"""Build, stage, publish and prepare the project-owned OKD images."""
from __future__ import annotations

import argparse
import base64
import concurrent.futures
import getpass
import hashlib
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import tarfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "deploy/okd/automation/services.json"
DEFAULT_STAGE = Path(os.environ.get("ARIA_IMAGE_STAGING", "~/.cache/aria-okd/images")).expanduser()
ARTIFACTORY = "artifactory.globaldevtools.bbva.com:443"
RETRY_DELAYS = (10, 30, 60)


def run(args: list[str], *, cwd: Path = ROOT, input_text: str | None = None,
        capture: bool = False, check: bool = True, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, input=input_text, text=True,
                          stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.PIPE if capture else None, check=check, env=env)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def deployment_image(path: Path, container: str) -> str:
    text = path.read_text()
    pattern = re.compile(r"(?ms)^        - name: " + re.escape(container) + r"\s*\n(?P<body>.*?)(?=^        - name:|\Z)")
    match = pattern.search(text)
    image = re.search(r"(?m)^\s+image:\s*([^\s#]+)", match.group("body")) if match else None
    if not image:
        raise ValueError(f"No se encontró la imagen de {container} en {path.relative_to(ROOT)}")
    return image.group(1)


def load_config() -> dict:
    config = json.loads(CONFIG.read_text())
    for name, service in config["services"].items():
        service["name"] = name
        service["deployment_path"] = ROOT / service["deployment"]
        service["current_image"] = deployment_image(service["deployment_path"], service["container"])
        if service.get("dockerfile"):
            definition_repo = config["repositories"].get(service.get("build_definition_repository", service["repository"]))
            service["dockerfile_path"] = (ROOT / service["dockerfile"]).resolve()
            service["_definition_default_root"] = ROOT
            if not definition_repo:
                raise ValueError(f"Repositorio de definición desconocido para {name}")
            service["_definition_repo"] = service.get("build_definition_repository", service["repository"])
    return config


def service_root(service: dict) -> Path:
    return Path(service.get("_source_path", ROOT / service.get("source_root", ".")).resolve())


def source_commit(service: dict | None = None) -> str:
    repo = service_root(service) if service else ROOT
    return run(["git", "rev-parse", "HEAD"], cwd=repo, capture=True).stdout.strip()


def source_branch(service: dict | None = None) -> str:
    if service and service.get("_branch"):
        return service["_branch"]
    repo = service_root(service) if service else ROOT
    return run(["git", "branch", "--show-current"], cwd=repo, capture=True).stdout.strip() or "detached"


def local_repository_checkout(repo_key: str, config: dict, expected_branch: str) -> Path:
    """Return a clean configured checkout for an intentional local-only source build."""
    checkout = (ROOT / config["repositories"][repo_key]["local_checkout"]).resolve()
    if not checkout.is_dir():
        raise RuntimeError(f"no existe el checkout local configurado para {repo_key}: {checkout}")
    branch = source_branch({"_source_path": checkout})
    if branch != expected_branch:
        raise RuntimeError(f"checkout local de {repo_key} está en {branch}; se esperaba {expected_branch}")
    status = run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=checkout, capture=True).stdout
    if status:
        raise RuntimeError(f"checkout local de {repo_key} tiene cambios; no se usará para construir: {checkout}")
    return checkout


def _credential_payload(remote: str, username: str = "", password: str = "") -> str:
    from urllib.parse import urlparse

    parsed = urlparse(remote)
    return f"protocol={parsed.scheme}\nhost={parsed.hostname}\n" + (
        f"username={username}\npassword={password}\n" if username or password else "") + "\n"


def github_credentials(remote: str, *, renew: bool = False) -> tuple[str, str] | None:
    if not renew:
        lookup = subprocess.run(["git", "credential", "fill"], input=_credential_payload(remote),
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                check=False, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
        if lookup.returncode == 0:
            values = dict(line.split("=", 1) for line in lookup.stdout.splitlines() if "=" in line)
            if values.get("username") and values.get("password"):
                return values["username"], values["password"]
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            return os.environ.get("GITHUB_USERNAME", "x-access-token"), token
    if not sys.stdin.isatty():
        return None
    token = getpass.getpass("Token GitHub Enterprise (entrada oculta): ")
    if not token:
        raise RuntimeError("se requiere un token de GitHub Enterprise para acceder al repositorio")
    username = os.environ.get("GITHUB_USERNAME", "x-access-token")
    approved = subprocess.run(["git", "credential", "approve"], input=_credential_payload(remote, username, token),
                              text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    if approved.returncode:
        print("No se pudo guardar la credencial en el helper Git configurado; se usará solo en esta ejecución.", file=sys.stderr)
    return username, token


def git_askpass(credentials: tuple[str, str]):
    directory = tempfile.TemporaryDirectory(prefix="aria-git-askpass-")
    helper = Path(directory.name) / "askpass.sh"
    helper.write_text("#!/bin/sh\ncase \"$1\" in\n  *sername*) printf '%s\\n' \"$ARIA_GIT_USERNAME\" ;;\n  *) printf '%s\\n' \"$ARIA_GIT_TOKEN\" ;;\nesac\n")
    helper.chmod(0o700)
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("GIT_TRACE") or key in {"GIT_CURL_VERBOSE", "GIT_TRACE_CURL_NO_DATA"}:
            env.pop(key, None)
    env.update({"GIT_ASKPASS": str(helper), "GIT_TERMINAL_PROMPT": "0",
                "GCM_INTERACTIVE": "Never", "ARIA_GIT_USERNAME": credentials[0],
                "ARIA_GIT_TOKEN": credentials[1]})
    return directory, env


def _authenticated_git(remote: str, args: list[str], credentials: tuple[str, str] | None,
                       *, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    if credentials is None:
        return subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              check=False, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    temporary, env = git_askpass(credentials)
    try:
        return subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              check=False, env=env)
    finally:
        temporary.cleanup()


def _is_auth_error(result: subprocess.CompletedProcess[str]) -> bool:
    return bool(re.search(r"(?i)(authentication failed|could not read username|http 401|http 403|invalid username|access denied)",
                          (result.stdout or "") + "\n" + (result.stderr or "")))


def cleanup_podman_build_secrets(directory: Path) -> None:
    """Remove Podman remote-build secret staging files left by interrupted clients."""
    for path in directory.glob("podman-build-secret*"):
        if re.fullmatch(r"podman-build-secret[0-9]+", path.name) and path.is_file() and not path.is_symlink():
            path.unlink()


def prepare_source(repo_key: str, branch: str, config: dict, stage: Path,
                   credential_cache: dict[str, tuple[str, str] | None], *, refresh: bool = True) -> Path:
    from urllib.parse import urlparse

    repo = config["repositories"][repo_key]
    remote = repo["url"]
    check = run(["git", "check-ref-format", "--branch", branch], capture=True, check=False)
    if check.returncode:
        raise ValueError(f"nombre de rama Git inválido: {branch!r}")
    cache_key = hashlib.sha256(f"{remote}\0{branch}".encode()).hexdigest()[:16]
    parent = stage / "sources" / repo_key
    parent.mkdir(parents=True, exist_ok=True)
    checkout = parent / cache_key
    credential_key = urlparse(remote).hostname or remote
    credentials = credential_cache.get(credential_key)
    if credential_key not in credential_cache:
        credentials = github_credentials(remote)
        credential_cache[credential_key] = credentials
    if not checkout.exists():
        with tempfile.TemporaryDirectory(prefix=f".{cache_key}.", dir=parent) as temporary:
            candidate = Path(temporary) / "checkout"
            command = ["git", "clone", "--quiet", "--single-branch", "--branch", branch, remote, str(candidate)]
            result = _authenticated_git(remote, command, credentials)
            if result.returncode and _is_auth_error(result):
                credentials = github_credentials(remote, renew=True)
                credential_cache[credential_key] = credentials
                if credentials:
                    result = _authenticated_git(remote, command, credentials)
            if result.returncode:
                raise RuntimeError(f"no fue posible clonar {repo_key} rama {branch}: {(result.stderr or result.stdout).strip()[-500:]}")
            os.replace(candidate, checkout)
    elif refresh:
        cleanup_podman_build_secrets(checkout)
        status = run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=checkout, capture=True).stdout
        if status:
            raise RuntimeError(f"checkout cache de {repo_key}/{branch} tiene cambios locales; no se alteró: {checkout}")
        command = ["git", "fetch", "--quiet", "--prune", "origin", branch]
        result = _authenticated_git(remote, command, credentials, cwd=checkout)
        if result.returncode and _is_auth_error(result):
            credentials = github_credentials(remote, renew=True)
            credential_cache[credential_key] = credentials
            if credentials:
                result = _authenticated_git(remote, command, credentials, cwd=checkout)
        if result.returncode:
            raise RuntimeError(f"no fue posible actualizar {repo_key} rama {branch}: {(result.stderr or result.stdout).strip()[-500:]}")
        run(["git", "checkout", "--quiet", "--detach", "FETCH_HEAD"], cwd=checkout)
    return checkout


def bind_source_paths(config: dict, repo_paths: dict[str, Path], branches: dict[str, str]) -> None:
    for service in config["services"].values():
        if service["repository"] not in repo_paths:
            continue
        service["_source_path"] = repo_paths[service["repository"]]
        service["_branch"] = branches[service["repository"]]
        definition_repo = service.get("_definition_repo", service["repository"])
        if definition_repo in repo_paths:
            service["dockerfile_path"] = repo_paths[definition_repo] / service["dockerfile"]


def docker_context_inputs(service: dict) -> set[str]:
    dockerfile = service.get("dockerfile")
    if not dockerfile:
        return set()
    inputs = {dockerfile, dockerfile + ".dockerignore"}
    # Follow Docker COPY sources instead of treating every repository edit as a build input.
    for line in (ROOT / dockerfile).read_text().splitlines():
        if not line.lstrip().startswith("COPY "):
            continue
        parts = line.split()
        sources = parts[1:-1]
        for source in sources:
            if source.startswith("--"):
                continue
            if source == ".":
                inputs.add(".")
                continue
            normalized = source.lstrip("/")
            if normalized.startswith("--from="):
                continue
            inputs.add(normalized)
            inputs.add(normalized.rstrip("/") + "/")
    return inputs


def input_matches(path: str, inputs: set[str]) -> bool:
    return any(item == "." or path == item or (item.endswith("/") and path.startswith(item)) for item in inputs)


def ensure_committed_inputs(names: list[str], config: dict) -> None:
    relevant: set[str] = set()
    for name in names:
        service = config["services"][name]
        repo = service_root(service)
        dirty = run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=repo, capture=True).stdout.splitlines()
        changed_paths = [line[3:].split(" -> ")[-1] for line in dirty if len(line) > 3]
        relevant.update(f"{name}:{path}" for path in changed_paths
                        if input_matches(path, docker_context_inputs(service)))
        # Some image definitions (frontend) live in the backend automation repo.
        dockerfile = service.get("dockerfile_path")
        if dockerfile and dockerfile.is_relative_to(ROOT):
            root_dirty = run(["git", "status", "--porcelain", "--untracked-files=all"], capture=True).stdout.splitlines()
            relative_dockerfile = dockerfile.relative_to(ROOT).as_posix()
            if any(line[3:].split(" -> ")[-1] == relative_dockerfile for line in root_dirty if len(line) > 3):
                relevant.add(relative_dockerfile)
    if relevant:
        raise RuntimeError("hay entradas de build sin commit; no se puede atribuir la imagen a HEAD: " + ", ".join(sorted(relevant)))


def state_path(stage: Path) -> Path:
    return stage / "state.json"


def read_state(stage: Path) -> dict:
    path = state_path(stage)
    return json.loads(path.read_text()) if path.exists() else {"published": {}, "artifacts": {}}


def write_state(stage: Path, state: dict) -> None:
    stage.mkdir(parents=True, exist_ok=True)
    tmp = state_path(stage).with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, state_path(stage))


def changed_services(config: dict, state: dict, forced: set[str] | None = None) -> list[str]:
    forced = forced or set()
    names: set[str] = set()
    for name, service in config["services"].items():
        if name in forced:
            names.add(name)
    published = state.get("published", {})
    for name, service in config["services"].items():
        if name in forced or not service.get("dockerfile"):
            continue
        current = source_commit(service)
        old = published.get(name, {}).get("commit", "")
        if not old or not re.fullmatch(r"[0-9a-f]{40,64}", old):
            names.add(name)
            continue
        try:
            output = run(["git", "diff", "--name-only", old, current], cwd=service_root(service), capture=True).stdout
        except (subprocess.CalledProcessError, OSError):
            names.add(name)
            continue
        paths = [p for p in output.splitlines() if p]
        dockerfile = service.get("dockerfile")
        if dockerfile and any(input_matches(path, docker_context_inputs(service)) for path in paths):
            names.add(name)
    return sorted(n for n in names if config["services"][n].get("dockerfile"))


def expand_selected_dependencies(selected: list[str], config: dict, state: dict) -> list[str]:
    published = state.get("published", {})
    requested_roots = {service_root(config["services"][name]) for name in selected}
    same_source = [name for name, service in config["services"].items()
                   if service_root(service) in requested_roots]
    changed_paths: set[str] = set()
    for name in selected:
        service = config["services"][name]
        current = source_commit(service)
        old = published.get(name, {}).get("commit", "")
        if not old or not re.fullmatch(r"[0-9a-f]{40,64}", old):
            return sorted(same_source)
        try:
            diff = run(["git", "diff", "--name-only", old, current], cwd=service_root(service), capture=True).stdout
        except (subprocess.CalledProcessError, OSError):
            return sorted(same_source)
        changed_paths.update(path for path in diff.splitlines() if path)
    for name in same_source:
        service = config["services"][name]
        if any(input_matches(path, docker_context_inputs(service)) for path in changed_paths):
            selected.append(name)
    return sorted(set(selected))


def image_target(service: dict, commit: str, custom_tag: str | None, config: dict) -> str:
    current = service["current_image"]
    repository = current.rsplit(":", 1)[0] if ":" in current.rsplit("/", 1)[-1] else current
    tag = custom_tag or commit
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", tag):
        raise ValueError(f"Tag de imagen inválido: {tag!r}")
    return f"{repository}:{tag}"


def build_one(name: str, service: dict, config: dict, stage: Path, commit: str,
              custom_tag: str | None, engine: str, authfile: Path, secret_dir: Path) -> dict:
    if not service.get("dockerfile_path"):
        raise RuntimeError(f"{name}: falta checkout/contexto de frontend; configure ARIA_FRONTEND_REPOSITORY y su integración")
    if not service["dockerfile_path"].is_file():
        raise RuntimeError(f"No existe Dockerfile: {service['dockerfile_path']}")
    target_platform = config.get("target_platform", "linux/amd64")
    if target_platform != "linux/amd64":
        raise RuntimeError(f"Plataforma destino no soportada: {target_platform}")
    target = image_target(service, commit, custom_tag, config)
    artifact_key = hashlib.sha256(
        f"{name}\0{commit}\0{target}\0{target_platform}\0{service['dockerfile']}".encode()).hexdigest()
    final = stage / f"{artifact_key}.oci.tar"
    temp = stage / f".{artifact_key}.{os.getpid()}.tmp.tar"
    local_name = f"localhost/aria-stage-{name}:{commit[:12]}"
    print(f"Iniciando build: {name} ({commit[:12]}) -> {target}", flush=True)
    command = [engine, "build"]
    command.extend(["--platform", target_platform])
    if engine == "podman":
        command.extend(["--authfile", str(authfile)])
    else:
        command.extend(["--config", str(authfile.parent)])
    if engine == "podman":
        command.append("--format=oci")
    command.extend(["--secret", f"id=artifactory_user,src={secret_dir / 'artifactory_user'}",
                    "--secret", f"id=artifactory_password,src={secret_dir / 'artifactory_password'}",
                    "-f", str(service["dockerfile_path"]), "-t", local_name,
                    "--build-arg", "GENAI_ENVIRONMENT=dev", str(service_root(service))])
    build_env = os.environ.copy()
    if engine == "docker":
        build_env["DOCKER_BUILDKIT"] = "1"
    context = service_root(service)
    cleanup_podman_build_secrets(context)
    try:
        run(command, cwd=context, env=build_env)
    finally:
        cleanup_podman_build_secrets(context)
    inspect_command = ([engine, "image", "inspect", "--format", "{{.Os}}/{{.Architecture}}", local_name]
                       if engine == "podman" else
                       [engine, "image", "inspect", "--format", "{{.Os}}/{{.Architecture}}", local_name])
    actual_platform = run(inspect_command, capture=True).stdout.strip()
    if actual_platform != target_platform:
        raise RuntimeError(
            f"{name}: la imagen quedó como {actual_platform}; el destino requiere {target_platform}"
        )
    archive_format = "oci-archive" if engine == "podman" else "docker-archive"
    if engine == "podman":
        run([engine, "save", "--format", archive_format, "-o", str(temp), local_name])
    else:
        run([engine, "image", "save", "-o", str(temp), local_name])
    checksum = sha256(temp)
    os.replace(temp, final)
    marker = {"service": name, "source_commit": commit, "source_branch": source_branch(service),
              "target": target, "artifact": final.name, "sha256": checksum,
              "dockerfile": service["dockerfile"], "archive_format": archive_format,
              "platform": actual_platform, "status": "pending", "created_at": int(time.time())}
    marker_path = stage / f"{artifact_key}.json"
    tmp_marker = marker_path.with_suffix(".tmp")
    tmp_marker.write_text(json.dumps(marker, indent=2) + "\n")
    os.replace(tmp_marker, marker_path)
    return marker


def existing_registry_credentials(auth_path: Path | None = None) -> tuple[str, str] | None:
    candidates = [auth_path] if auth_path else [
        Path.home() / ".config/containers/auth.json", Path.home() / ".docker/config.json"]
    for path in candidates:
        if path is None:
            continue
        try:
            document = json.loads(path.read_text())
            auth = document.get("auths", document) if isinstance(document, dict) else None
            if not isinstance(auth, dict):
                raise ValueError("el archivo debe ser un objeto JSON de credenciales")
            entry = next((value for key, value in auth.items()
                          if key.removeprefix("https://").removeprefix("http://").rstrip("/")
                          .split("/")[0] == ARTIFACTORY), None)
            if not entry:
                continue
            if not isinstance(entry, dict):
                raise ValueError("la entrada del registry debe ser un objeto")
            if entry.get("username") and entry.get("password"):
                return entry["username"], entry["password"]
            if entry.get("auth"):
                decoded = base64.b64decode(entry["auth"]).decode()
                user, password = decoded.split(":", 1)
                return user, password
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
            if auth_path is not None:
                raise ValueError(f"No se pudo leer el archivo de autenticación de Artifactory: {error}") from error
            continue
    if auth_path is not None:
        raise ValueError(f"El archivo de autenticación no contiene credenciales para {ARTIFACTORY}")
    return None


def build_auth(engine: str, auth_path: Path | None = None, *, skip_login: bool = False) -> tuple[tempfile.TemporaryDirectory[str], Path]:
    credentials = existing_registry_credentials(auth_path)
    if skip_login:
        if auth_path is not None:
            raise ValueError("--skip-auth reutiliza la sesión de Podman; no se combina con --auth-file")
        authfile = Path.home() / ".config/containers/auth.json"
        credentials = existing_registry_credentials() or None
        user = credentials[0] if credentials else ""
        password = credentials[1] if credentials else ""
    else:
        user = ((credentials[0] if credentials else None) if auth_path else os.environ.get("ARTIFACTORY_USER")
                or (credentials[0] if credentials else None)) or input(
            "Artifactory usuario (pull de bases y dependencias): ")
        password = ((credentials[1] if credentials else None) if auth_path else os.environ.get("ARTIFACTORY_PASSWORD")
                    or (credentials[1] if credentials else None)) or getpass.getpass(
            "Artifactory token/contraseña: ")
        authfile = None
    temp = tempfile.TemporaryDirectory(prefix="aria-build-auth-")
    directory = Path(temp.name)
    username_file = directory / "artifactory_user"
    password_file = directory / "artifactory_password"
    username_file.write_text(user)
    password_file.write_text(password)
    username_file.chmod(0o600)
    password_file.chmod(0o600)
    if not skip_login:
        authfile = directory / ("auth.json" if engine == "podman" else "config.json")
        authfile.write_text("{}\n")
        authfile.chmod(0o600)
    assert authfile is not None
    if skip_login:
        return temp, authfile
    if engine == "podman":
        command = ["podman", "login", "--authfile", str(authfile), "--username", user, "--password-stdin", ARTIFACTORY]
    else:
        command = ["docker", "--config", str(directory), "login", "--username", user, "--password-stdin", ARTIFACTORY]
    result = run(command, input_text=password + "\n", capture=True, check=False)
    if result.returncode:
        temp.cleanup()
        detail = (result.stderr or result.stdout or "sin detalle devuelto por Podman/Docker").strip()
        for secret in (user, password):
            if secret:
                detail = detail.replace(secret, "[REDACTADO]")
        detail = detail[-1200:]
        raise RuntimeError(
            "No fue posible autenticar con Artifactory para descargar bases/dependencias. "
            f"Diagnóstico (credenciales redactadas): {detail}"
        )
    return temp, authfile


def load_artifacts(stage: Path) -> list[dict]:
    artifacts = []
    for path in sorted(stage.glob("*.json")):
        if path.name == "state.json":
            continue
        data = json.loads(path.read_text())
        artifact = stage / data["artifact"]
        if not artifact.is_file() or sha256(artifact) != data.get("sha256"):
            data["status"] = "invalid"
        data["_path"] = path
        data["_artifact_path"] = artifact
        artifacts.append(data)
    return artifacts


def pending_artifacts_for_platform(items: list[dict], expected_platform: str) -> list[dict]:
    """Select pending artifacts that have explicit metadata for the required platform."""
    pending = []
    for item in items:
        if item.get("status") == "published":
            continue
        if item.get("platform") != expected_platform:
            print(
                f"Se omite staging de {item.get('service', 'servicio desconocido')} "
                f"({item.get('artifact', 'artefacto desconocido')}): plataforma "
                f"{item.get('platform', 'desconocida')}; se requiere {expected_platform}"
            )
            continue
        pending.append(item)
    return pending


def prepare_pending_publications(items: list[dict], expected_platform: str, config: dict,
                                services_arg: str | None = None,
                                custom_tag: str | None = None,
                                latest_artifacts: dict[str, str] | None = None,
                                include_history: bool = False) -> list[dict]:
    """Select pending artifacts and optionally retarget them without rebuilding."""
    requested = {name.strip() for name in (services_arg or "").split(",") if name.strip()}
    unknown = requested - config["services"].keys()
    if unknown:
        raise ValueError(f"--services inválido; desconocidos: {', '.join(sorted(unknown))}")
    if custom_tag and not requested:
        raise ValueError("al cambiar el tag de una publicación pendiente, indique --services explícitamente")
    if latest_artifacts is not None and not include_history:
        current_items = []
        for item in items:
            latest = latest_artifacts.get(item.get("service"))
            if latest is not None and latest != item.get("artifact"):
                print(f"Se conserva staging histórico de {item.get('service')} "
                      f"({item.get('artifact')}); no se publica en esta ejecución. "
                      "Usa ALL_STAGED=1 para incluirlo.")
                continue
            current_items.append(item)
        items = current_items
    pending = pending_artifacts_for_platform(items, expected_platform)
    if requested:
        pending = [item for item in pending if item.get("service") in requested]
    if custom_tag:
        for item in pending:
            service = config["services"][item["service"]]
            item["target"] = image_target(service, item["source_commit"], custom_tag, config)
            print(f"Destino seleccionado para {item['service']}: {item['target']}")
    return pending


def oci_archive_details(archive: Path) -> tuple[bytes, str, str]:
    """Return the OCI manifest bytes and platform without extracting archive paths."""
    try:
        with tarfile.open(archive, "r:*") as image:
            index_file = image.extractfile("index.json")
            if index_file is None:
                raise ValueError("OCI index.json is missing")
            index = json.load(index_file)
            descriptors = index.get("manifests", [])
            if len(descriptors) != 1:
                raise ValueError("OCI archive must contain exactly one image manifest")
            source_ref = descriptors[0].get("annotations", {}).get("org.opencontainers.image.ref.name")
            if not source_ref:
                raise ValueError("OCI archive has no image reference annotation")
            manifest_digest = descriptors[0]["digest"]
            algorithm, digest_hex = manifest_digest.split(":", 1)
            if algorithm != "sha256" or not re.fullmatch(r"[0-9a-f]{64}", digest_hex):
                raise ValueError("OCI manifest digest is invalid")
            manifest_file = image.extractfile(f"blobs/sha256/{digest_hex}")
            if manifest_file is None:
                raise ValueError("OCI manifest blob is missing")
            manifest_bytes = manifest_file.read()
            if hashlib.sha256(manifest_bytes).hexdigest() != digest_hex:
                raise ValueError("OCI manifest checksum mismatch")
            manifest = json.loads(manifest_bytes)
            config_digest = manifest["config"]["digest"]
            config_algorithm, config_hex = config_digest.split(":", 1)
            if config_algorithm != "sha256" or not re.fullmatch(r"[0-9a-f]{64}", config_hex):
                raise ValueError("OCI config digest is invalid")
            config_file = image.extractfile(f"blobs/sha256/{config_hex}")
            if config_file is None:
                raise ValueError("OCI config blob is missing")
            config = json.load(config_file)
            diff_ids = config.get("rootfs", {}).get("diff_ids")
            if not isinstance(diff_ids, list) or len(diff_ids) != len(manifest.get("layers", [])):
                raise ValueError("OCI config diff_ids do not match the manifest layer count")
            platform = f"{config.get('os')}/{config.get('architecture')}"
            return manifest_bytes, platform, source_ref
    except (OSError, KeyError, tarfile.TarError, json.JSONDecodeError, ValueError) as error:
        raise RuntimeError(f"no se pudo validar el archivo OCI {archive.name}: {error}") from error


def registry_manifest(target: str, credentials: tuple[str, str]) -> tuple[str, bytes] | None:
    """Read a Docker Registry v2 manifest over verified HTTPS using basic/bearer auth."""
    registry, image_ref = target.split("/", 1)
    repository, tag = image_ref.rsplit(":", 1)
    base = f"https://{registry}/v2/{repository}"
    url = f"{base}/manifests/{tag}"
    scope = f"repository:{repository}:pull"
    accept = ", ".join((
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
    ))
    user, password = credentials
    basic = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
    context = registry_ssl_context()

    def get(request_url: str, authorization: str) -> tuple[int, bytes, str | None, dict[str, str]]:
        request = Request(request_url, headers={"Authorization": authorization, "Accept": accept})
        try:
            with urlopen(request, timeout=30, context=context) as response:
                return response.status, response.read(), response.headers.get("Docker-Content-Digest"), dict(response.headers.items())
        except HTTPError as error:
            if error.code == 404:
                return 404, b"", None, dict(error.headers.items())
            if error.code != 401:
                detail = error.read(300).decode("utf-8", "replace")
                raise RuntimeError(f"consulta al registry respondió HTTP {error.code}: {detail}") from error
            challenge = error.headers.get("WWW-Authenticate", "")
            if not challenge.lower().startswith("bearer "):
                raise RuntimeError("credenciales rechazadas al consultar el registry (HTTP 401)") from error
            attributes = dict(re.findall(r'([A-Za-z]+)="([^"]*)"', challenge))
            realm = attributes.get("realm")
            if not realm:
                raise RuntimeError("el registry envió un challenge Bearer incompleto") from error
            parsed = urlsplit(realm)
            query = dict(parse_qsl(parsed.query))
            if attributes.get("service"):
                query["service"] = attributes["service"]
            query["scope"] = attributes.get("scope", scope)
            token_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))
            token_request = Request(token_url, headers={"Authorization": basic})
            try:
                with urlopen(token_request, timeout=30, context=context) as token_response:
                    token_data = json.loads(token_response.read())
            except (HTTPError, URLError, json.JSONDecodeError) as token_error:
                raise RuntimeError("no fue posible obtener token Bearer del registry") from token_error
            token = token_data.get("token") or token_data.get("access_token")
            if not token:
                raise RuntimeError("el registry no devolvió un token Bearer")
            try:
                with urlopen(Request(request_url, headers={
                    "Authorization": f"Bearer {token}", "Accept": accept
                }), timeout=30, context=context) as response:
                    return response.status, response.read(), response.headers.get("Docker-Content-Digest"), dict(response.headers.items())
            except HTTPError as bearer_error:
                if bearer_error.code == 404:
                    return 404, b"", None, dict(bearer_error.headers.items())
                detail = bearer_error.read(300).decode("utf-8", "replace")
                raise RuntimeError(f"consulta Bearer al registry respondió HTTP {bearer_error.code}: {detail}") from bearer_error
        except URLError as error:
            raise RuntimeError(f"no se pudo consultar Artifactory por HTTPS: {error.reason}") from error

    status, body, digest, _ = get(url, basic)
    if status == 404:
        return None
    actual = digest or ("sha256:" + hashlib.sha256(body).hexdigest())
    return actual, body


def registry_ssl_context() -> ssl.SSLContext:
    """Use system trust, optionally with an explicitly trusted Artifactory CA bundle."""
    if not registry_tls_verify_enabled():
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context
    bundle = os.environ.get("ARTIFACTORY_CA_BUNDLE")
    if not bundle:
        return ssl.create_default_context()
    path = Path(bundle).expanduser()
    if not path.is_file() or not os.access(path, os.R_OK):
        raise RuntimeError(f"ARTIFACTORY_CA_BUNDLE no apunta a un archivo CA legible: {path}")
    context = ssl.create_default_context()
    try:
        context.load_verify_locations(cafile=str(path))
        return context
    except (OSError, ssl.SSLError) as error:
        raise RuntimeError(f"no se pudo cargar el bundle CA indicado en ARTIFACTORY_CA_BUNDLE: {error}") from error


def registry_tls_verify_enabled() -> bool:
    value = os.environ.get("ARTIFACTORY_TLS_VERIFY", "true").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError("ARTIFACTORY_TLS_VERIFY debe ser true o false")


def image_manifests_match(local_manifest: bytes, remote_manifest: bytes) -> bool:
    """Treat OCI/Docker manifest rewrites as equal only when config and layer count match."""
    try:
        local = json.loads(local_manifest)
        remote = json.loads(remote_manifest)
    except json.JSONDecodeError:
        return False
    local_config = local.get("config", {}).get("digest")
    remote_config = remote.get("config", {}).get("digest")
    local_layers = local.get("layers")
    remote_layers = remote.get("layers")
    if not local_config or local_config != remote_config:
        return False
    if not isinstance(local_layers, list) or not isinstance(remote_layers, list):
        return False
    if len(local_layers) != len(remote_layers):
        return False
    return all(isinstance(layer, dict) and layer.get("digest") and layer.get("size") is not None
               for layer in local_layers + remote_layers)


def publish_one_with_podman(item: dict, auth: Path | None, max_attempts: int,
                            expected_platform: str, manifest_bytes: bytes, source_ref: str) -> dict:
    credentials = existing_registry_credentials(auth)
    if not credentials:
        raise RuntimeError("no se encontraron credenciales de Artifactory para validar el destino")
    expected_digest = "sha256:" + hashlib.sha256(manifest_bytes).hexdigest()
    archive = item["_artifact_path"]
    target = item["target"]
    auth_args = ["--authfile", str(auth)] if auth else []
    message = "sin intento de publicación"
    loaded = run(["podman", "load", "--input", str(archive)], capture=True, check=False)
    if loaded.returncode:
        raise RuntimeError(f"no se pudo cargar staging en Podman: {(loaded.stderr or loaded.stdout)[-500:]}")
    local_platform = run(["podman", "image", "inspect", "--format",
                          "{{.Os}}/{{.Architecture}}", source_ref], capture=True).stdout.strip()
    if local_platform != expected_platform:
        raise RuntimeError(f"la imagen local cargada es {local_platform}; se requiere {expected_platform}")
    for attempt in range(max_attempts):
        remote = registry_manifest(target, credentials)
        if remote:
            if remote[0] == expected_digest or image_manifests_match(manifest_bytes, remote[1]):
                item["status"] = "published"
                item["published_digest"] = remote[0]
                return item
            raise RuntimeError(f"el destino inmutable {target} ya existe con digest diferente; no se sobrescribe")

        tls_flag = "--tls-verify=true" if registry_tls_verify_enabled() else "--tls-verify=false"
        command = ["podman", "push", *auth_args, "--retry", "0", tls_flag, "--format", "oci",
                   source_ref, f"docker://{target}"]
        result = run(command, capture=True, check=False)
        verified = registry_manifest(target, credentials)
        if verified and (verified[0] == expected_digest or image_manifests_match(manifest_bytes, verified[1])):
            item["status"] = "published"
            item["published_digest"] = verified[0]
            return item
        if result.returncode == 0:
            raise RuntimeError(f"la verificación remota de {target} no coincide con el artefacto")

        message = (result.stderr or result.stdout or "podman push falló").strip()
        if re.search(r"(?i)(unauthorized|denied|forbidden|authentication|required|invalid username|manifest invalid)", message):
            raise RuntimeError(f"fallo permanente publicando {target}: {message[-500:]}")
        if attempt + 1 < max_attempts:
            time.sleep(RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)])
    raise RuntimeError(f"falló publicación de {target} tras {max_attempts} intentos: {message[-500:]}")


def auth_file(auth_path: Path | None = None, *, skip_login: bool = False) -> tuple[tempfile.TemporaryDirectory[str], Path | None]:
    if skip_login:
        if auth_path is not None:
            raise ValueError("--skip-auth reutiliza la sesión de Podman; no se combina con --auth-file")
        return tempfile.TemporaryDirectory(prefix="aria-registry-auth-"), None
    credentials = existing_registry_credentials(auth_path)
    if auth_path is not None and not shutil.which("skopeo"):
        return tempfile.TemporaryDirectory(prefix="aria-registry-auth-"), auth_path
    user = ((credentials[0] if credentials else None) if auth_path else os.environ.get("ARTIFACTORY_USER")
            or (credentials[0] if credentials else None)) or input("Artifactory usuario: ")
    password = ((credentials[1] if credentials else None) if auth_path else os.environ.get("ARTIFACTORY_PASSWORD")
                or (credentials[1] if credentials else None)) or getpass.getpass("Artifactory token/contraseña: ")
    temp = tempfile.TemporaryDirectory(prefix="aria-registry-auth-")
    path = Path(temp.name) / "auth.json"
    path.write_text("{}\n")
    path.chmod(0o600)
    login_engine = "skopeo" if shutil.which("skopeo") else "podman"
    tls_args = [] if registry_tls_verify_enabled() else ["--tls-verify=false"]
    run([login_engine, "login", *tls_args, "--authfile", str(path), "--username", user,
         "--password-stdin", ARTIFACTORY], input_text=password + "\n", capture=True)
    return temp, path


def publish_one(item: dict, auth: Path | None, max_attempts: int, expected_platform: str) -> dict:
    if item.get("status") == "invalid":
        raise RuntimeError(f"staging corrupto o incompleto para {item['service']} ({item['artifact']})")
    if item.get("platform") != expected_platform:
        raise RuntimeError(
            f"{item['service']}: staging declara {item.get('platform', 'plataforma desconocida')}; "
            f"el destino requiere {expected_platform}"
        )
    target = item["target"]
    source = f"{item.get('archive_format', 'oci-archive')}:{item['_artifact_path']}"
    manifest_bytes, archive_platform, source_ref = oci_archive_details(item["_artifact_path"])
    if archive_platform != expected_platform:
        raise RuntimeError(f"{item['service']}: artefacto {archive_platform} incompatible con {expected_platform}")
    if not shutil.which("skopeo"):
        if not shutil.which("podman"):
            raise RuntimeError("se necesita skopeo o podman para publicar imágenes")
        return publish_one_with_podman(item, auth, max_attempts, expected_platform,
                                       manifest_bytes, source_ref)
    source_platform = run(["skopeo", "inspect", "--format", "{{.Os}}/{{.Architecture}}", source],
                          capture=True).stdout.strip()
    if source_platform != expected_platform:
        raise RuntimeError(f"{item['service']}: artefacto {source_platform} incompatible con {expected_platform}")
    local_manifest = run(["skopeo", "inspect", "--raw", source], capture=True, check=False)
    if local_manifest.returncode:
        raise RuntimeError(f"no se pudo validar imagen local {item['service']}: {local_manifest.stderr[-400:]}")
    expected_digest = "sha256:" + hashlib.sha256(local_manifest.stdout.encode()).hexdigest()
    auth_args = ["--authfile", str(auth)] if auth else []
    tls_args = [] if registry_tls_verify_enabled() else ["--tls-verify=false"]
    credentials = existing_registry_credentials(auth)
    if not credentials:
        raise RuntimeError("no se encontraron credenciales de Artifactory para validar el destino")
    # Never overwrite a tag that already points at different bytes. Registry digest is
    # recorded after copy; equal config digests permit registries to recompress OCI layers.
    for attempt in range(max_attempts):
        remote = registry_manifest(target, credentials)
        if remote:
            if remote[0] == expected_digest or image_manifests_match(local_manifest.stdout.encode(), remote[1]):
                item["status"] = "published"
                item["published_digest"] = remote[0]
                return item
            raise RuntimeError(f"el destino inmutable {target} ya existe con digest diferente; no se sobrescribe")
        result = run(["skopeo", "copy", *tls_args, *auth_args, "--retry-times", "0", source,
                      f"docker://{target}"], capture=True, check=False)
        verified = registry_manifest(target, credentials)
        if verified and (verified[0] == expected_digest or
                         image_manifests_match(local_manifest.stdout.encode(), verified[1])):
            item["status"] = "published"
            item["published_digest"] = verified[0]
            return item
        if result.returncode == 0:
            raise RuntimeError(f"la verificación remota de {target} no coincide con el artefacto")
        message = result.stderr or result.stdout or "copia falló"
        if re.search(r"(?i)(unauthorized|denied|forbidden|authentication|required|invalid username|manifest invalid)", message):
            raise RuntimeError(f"fallo permanente publicando {target}: {message.strip()[-500:]}")
        if attempt + 1 < max_attempts:
            time.sleep(RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)])
    raise RuntimeError(f"falló publicación de {target} tras {max_attempts} intentos: {message.strip()[-500:]}")


def update_manifests(items: list[dict], config: dict, dry_run: bool) -> None:
    updates = {item["service"]: item for item in items if item.get("status") == "published"}
    for name, item in updates.items():
        service = config["services"][name]
        path = service["deployment_path"]
        text = path.read_text()
        container = re.compile(r"(?ms)(^        - name: " + re.escape(service["container"])
                               + r"\s*\n.*?^\s+image:)\s*[^\s#]+")
        replacement = lambda match: match.group(1) + " " + item["target"]
        changed, count = container.subn(replacement, text, count=1)
        if count != 1:
            raise RuntimeError(f"No se pudo actualizar únicamente {service['container']} en {path}")
        print(f"{'[dry-run] ' if dry_run else ''}{path.relative_to(ROOT)} -> {item['target']}")
        if not dry_run:
            path.write_text(changed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("changed", "all", "services", "resume", "publish", "deploy", "dry-run"), nargs="?", default="changed")
    parser.add_argument("--services", help="Lista separada por comas para el modo services")
    parser.add_argument("--tag", help="Tag inmutable opcional; vacío usa el commit fuente")
    parser.add_argument("--stage", type=Path, default=DEFAULT_STAGE)
    parser.add_argument("--build-concurrency", type=int, default=3)
    parser.add_argument("--push-concurrency", type=int, default=1)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--auth-file", type=Path, default=os.environ.get("ARTIFACTORY_AUTH_FILE"),
                        help="Archivo Docker/Podman auth.json; también puede definirse ARTIFACTORY_AUTH_FILE")
    parser.add_argument("--skip-auth", action="store_true",
                        help="Reutiliza la sesión ya iniciada con podman login; no realiza otro login")
    parser.add_argument("--build-only", action="store_true",
                        help="Construye y conserva imágenes en staging, sin publicarlas")
    parser.add_argument("--backend-branch", default=os.environ.get("ARIA_BACKEND_BRANCH"))
    parser.add_argument("--frontend-branch", default=os.environ.get("ARIA_FRONTEND_BRANCH"))
    parser.add_argument("--use-local-frontend", action="store_true",
                        help="build from the configured clean local frontend checkout, including unpushed commits")
    parser.add_argument("--all-staged", action="store_true",
                        help="include historical staged artifacts, not only each service's current artifact")
    parser.add_argument("--github-token-env", default="GITHUB_TOKEN",
                        help="Nombre de variable de entorno para automatización no interactiva; el token nunca va en argv")
    parser.add_argument("--engine", choices=("podman", "docker"), default=os.environ.get("ARIA_CONTAINER_ENGINE", "podman"))
    parser.add_argument("--allow-manifest-write", action="store_true", help="Autoriza editar localmente los Deployments; no aplica recursos remotos")
    args = parser.parse_args()
    if args.build_concurrency < 1 or args.push_concurrency < 1 or args.attempts < 1:
        parser.error("concurrencias e intentos deben ser mayores que cero")
    if args.skip_auth and (args.engine != "podman" or args.auth_file):
        parser.error("--skip-auth requiere --engine podman y no se combina con --auth-file")
    if args.build_only and args.mode not in ("changed", "all", "services"):
        parser.error("--build-only solo aplica a changed, all o services")
    config = load_config()
    stage = args.stage.expanduser().resolve()
    state = read_state(stage)
    commit = source_commit()
    mode = "dry-run" if args.mode == "dry-run" else args.mode
    branches = {
        "backend": args.backend_branch or config["repositories"]["backend"]["default_branch"],
        "frontend": args.frontend_branch or config["repositories"]["frontend"]["default_branch"],
    }
    token = os.environ.get(args.github_token_env) or os.environ.get("GITHUB_TOKEN")
    if token:
        os.environ["GITHUB_TOKEN"] = token
    if mode in ("all", "changed", "services", "dry-run"):
        if mode == "services" or (mode == "dry-run" and args.services):
            requested = [n.strip() for n in (args.services or "").split(",") if n.strip()]
            unknown = set(requested) - config["services"].keys()
            if not requested or unknown:
                parser.error(f"--services inválido; desconocidos: {', '.join(sorted(unknown))}")
            repo_keys = {config["services"][name]["repository"] for name in requested}
        else:
            repo_keys = set(config["repositories"])
        for name, service in config["services"].items():
            if service["repository"] in repo_keys:
                repo_keys.add(service.get("_definition_repo", service["repository"]))
        repo_paths: dict[str, Path] = {}
        credential_cache: dict[str, tuple[str, str] | None] = {}
        for repo_key in config["repositories"]:
            if repo_key not in repo_keys:
                continue
            repository = config["repositories"][repo_key]
            if mode == "dry-run":
                repo_paths[repo_key] = (ROOT / repository["local_checkout"]).resolve()
                local_branch = source_branch({"_source_path": repo_paths[repo_key]})
                if local_branch != branches[repo_key]:
                    print(f"dry-run: {repo_key} mostrará el checkout local {local_branch}; la ejecución real obtiene la rama {branches[repo_key]}")
                branches[repo_key] = local_branch
            elif repo_key == "frontend" and args.use_local_frontend:
                repo_paths[repo_key] = local_repository_checkout(repo_key, config, branches[repo_key])
            else:
                repo_paths[repo_key] = prepare_source(repo_key, branches[repo_key], config, stage,
                                                      credential_cache, refresh=True)
        bind_source_paths(config, repo_paths, branches)
        commit = source_commit(config["services"]["api"])
    if mode in ("all", "changed", "services", "dry-run"):
        if mode == "all":
            selected = [n for n, s in config["services"].items() if s.get("dockerfile")]
        elif mode == "services":
            selected = [n.strip() for n in (args.services or "").split(",") if n.strip()]
            unknown = set(selected) - config["services"].keys()
            if not selected or unknown:
                parser.error(f"--services inválido; desconocidos: {', '.join(sorted(unknown))}")
            selected = expand_selected_dependencies(selected, config, state)
        elif mode == "dry-run" and args.services:
            selected = [n.strip() for n in args.services.split(",") if n.strip()]
            unknown = set(selected) - config["services"].keys()
            if not selected or unknown:
                parser.error(f"--services inválido; desconocidos: {', '.join(sorted(unknown))}")
            selected = expand_selected_dependencies(selected, config, state)
        else:
            selected = changed_services(config, state)
        print(f"Backend: {commit} ({source_branch()}); modo: {mode}")
        print("Builds: " + (", ".join(selected) if selected else "ninguno; estado sin cambios"))
        if mode == "dry-run":
            for name in selected:
                service = config["services"][name]
                service_commit = source_commit(service)
                context_path = os.path.relpath(service_root(service), ROOT)
                print(f"  {name}: {service_commit} ({source_branch(service)}) {context_path} + {service['dockerfile']} -> {image_target(service, service_commit, args.tag, config)}")
            print("Publicación/despliegue: no ejecutados")
            return 0
        if selected:
            ensure_committed_inputs(selected, config)
            stage.mkdir(parents=True, exist_ok=True)
            if args.engine not in ("podman", "docker") or not shutil.which(args.engine):
                raise RuntimeError(f"No se encuentra el engine {args.engine}")
            build_temp, build_authfile = build_auth(
                args.engine, args.auth_file.expanduser() if args.auth_file else None,
                skip_login=args.skip_auth)
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=args.build_concurrency) as pool:
                    futures = {pool.submit(build_one, n, config["services"][n], config, stage,
                                           source_commit(config["services"][n]), args.tag,
                                           args.engine, build_authfile, Path(build_temp.name)): n for n in selected}
                    for future in concurrent.futures.as_completed(futures):
                        data = future.result()
                        state.setdefault("artifacts", {})[data["service"]] = data["artifact"]
                        print(f"Staging completo: {data['service']} sha256:{data['sha256']}", flush=True)
                        write_state(stage, state)
            finally:
                build_temp.cleanup()
        if args.build_only:
            return 0
        mode = "publish"
    if mode in ("resume", "publish"):
        state["last_published"] = []
        write_state(stage, state)
        expected_platform = config.get("target_platform", "linux/amd64")
        pending = prepare_pending_publications(
            load_artifacts(stage), expected_platform, config, args.services,
            args.tag if mode == "publish" else None, state.get("artifacts"), args.all_staged,
        )
        print(f"Imágenes por publicar: {len(pending)}")
        if pending:
            auth_temp, auth = auth_file(
                args.auth_file.expanduser() if args.auth_file else None, skip_login=args.skip_auth)
            errors: list[str] = []
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=args.push_concurrency) as pool:
                    futures = [pool.submit(publish_one, item, auth, args.attempts, expected_platform)
                               for item in pending]
                    for future in concurrent.futures.as_completed(futures):
                        try:
                            item = future.result()
                            item["_path"].write_text(json.dumps({k: v for k, v in item.items() if not k.startswith("_")}, indent=2) + "\n")
                            state.setdefault("published", {})[item["service"]] = {
                                "commit": item["source_commit"], "target": item["target"],
                                "digest": item.get("published_digest"), "time": int(time.time())}
                            state["last_published"].append({"service": item["service"],
                                                             "commit": item["source_commit"],
                                                             "target": item["target"]})
                            write_state(stage, state)
                            print(f"Publicado y verificado: {item['target']} {item.get('published_digest', '')}")
                        except Exception as exc:  # preserve every artifact and report each failed item
                            errors.append(str(exc))
                            print(f"ERROR publicación: {exc}", file=sys.stderr)
            finally:
                auth_temp.cleanup()
            if errors:
                return 2
        return 0
    if mode == "deploy":
        previous = {(entry["service"], entry["commit"], entry["target"])
                    for entry in state.get("last_published", [])}
        items = [i for i in load_artifacts(stage) if i.get("status") == "published" and
                 (i["service"], i["source_commit"], i["target"]) in previous]
        if not args.allow_manifest_write:
            print("Deploy prepara manifiestos localmente; agregue --allow-manifest-write para permitir escrituras locales. No hace push ni aplica al clúster.")
            update_manifests(items, config, True)
            return 0
        update_manifests(items, config, False)
        return 0
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
