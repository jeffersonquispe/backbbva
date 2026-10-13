"""Manage local-auth users through the API (create, list, change password).

Stdlib only, so it runs with any python3 on the host. Every call is
authorised by the provisioning token (AUTH_BOOTSTRAP_TOKEN on the API);
nothing is stored on disk.

    python3 scripts/local_users.py            # interactive menu
    python3 scripts/local_users.py create
    python3 scripts/local_users.py list
    python3 scripts/local_users.py passwd

Env: ARIA_API_URL (default http://localhost:8000), ARIA_BOOTSTRAP_TOKEN
(asked for, hidden, when unset).
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

ROLES = [
    ("manager", "Manager"),
    ("channel_manager", "Channel manager — todos los permisos del frontend"),
    ("release_manager", "Release manager"),
    ("data_analyst", "Data analyst"),
    ("fraud_analyst", "Fraud analyst — solo la cola"),
    ("ops_analyst", "Ops analyst"),
]
MIN_PASSWORD_LENGTH = 8


# ─── terminal helpers ──────────────────────────────────────────────────────────

def _read_key() -> str:
    import select as io_select
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        key = os.read(fd, 1).decode(errors="ignore")
        if key == "\x1b" and io_select.select([fd], [], [], 0.05)[0]:  # arrow keys send ESC [ A/B
            key += os.read(fd, 2).decode(errors="ignore")
        return key
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def select(title: str, options: list[str]) -> int:
    """Arrow-key (↑/↓ or j/k, Enter) picker; numbered prompt when not a TTY."""
    if not options:
        raise SystemExit("No hay opciones para elegir.")
    if not (sys.stdin.isatty() and sys.stdout.isatty()) or os.name == "nt":
        print(title)
        for i, option in enumerate(options, 1):
            print(f"  {i}) {option}")
        while True:
            answer = input("Número: ").strip()
            if answer.isdigit() and 1 <= int(answer) <= len(options):
                return int(answer) - 1
            print("Opción no válida.", file=sys.stderr)

    index = 0
    print(f"{title}  \033[2m(↑/↓, Enter; q para salir)\033[0m")
    sys.stdout.write("\033[?25l")  # hide cursor
    try:
        while True:
            for i, option in enumerate(options):
                line = f"\033[36m❯ {option}\033[0m" if i == index else f"  {option}"
                sys.stdout.write(f"\r\033[2K{line}\n")
            sys.stdout.flush()
            key = _read_key()
            if key in ("\r", "\n"):
                break
            if key in ("\x1b[A", "k"):
                index = (index - 1) % len(options)
            elif key in ("\x1b[B", "j"):
                index = (index + 1) % len(options)
            elif key in ("q", "\x03", "\x1b"):
                sys.stdout.write(f"\033[{len(options)}A\033[J")
                raise SystemExit("Cancelado.")
            sys.stdout.write(f"\033[{len(options)}A")
        # collapse the list to the chosen line
        sys.stdout.write(f"\033[{len(options)}A\033[J\033[36m❯ {options[index]}\033[0m\n")
        return index
    finally:
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()


def ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        value = input(f"{prompt}{suffix}: ").strip() or (default or "")
        if value:
            return value
        print("No puede estar vacío.", file=sys.stderr)


def ask_new_password() -> str:
    while True:
        password = getpass.getpass("Contraseña: ")
        if len(password) < MIN_PASSWORD_LENGTH:
            print(f"Debe tener al menos {MIN_PASSWORD_LENGTH} caracteres.", file=sys.stderr)
            continue
        if getpass.getpass("Repite la contraseña: ") != password:
            print("Las contraseñas no coinciden.", file=sys.stderr)
            continue
        return password


# ─── API client ────────────────────────────────────────────────────────────────

class Api:
    def __init__(self, base_url: str, token: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token

    def request(self, method: str, path: str, payload: dict | None = None):
        request = Request(
            f"{self._base_url}/api/v0/auth{path}",
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Content-Type": "application/json", "X-Bootstrap-Token": self._token},
            method=method,
        )
        try:
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read() or b"null")
        except HTTPError as exc:
            body = exc.read().decode(errors="replace")
            try:
                body = json.loads(body).get("detail", body)
            except (ValueError, AttributeError):
                pass
            raise SystemExit(f"La API respondió HTTP {exc.code}: {body}") from exc
        except URLError as exc:
            raise SystemExit(f"No se pudo conectar a {self._base_url}: {exc.reason}") from exc


# ─── commands ──────────────────────────────────────────────────────────────────

def _role_label(role: str) -> str:
    return dict(ROLES).get(role, role).split(" — ")[0]


def _user_option(user: dict) -> str:
    status = "" if user.get("is_active", True) else "  (inactivo)"
    return f"{user['email']:<36} {user['name']:<24} {_role_label(user['role'])}{status}"


def cmd_list(api: Api) -> None:
    users = api.request("GET", "/users")
    if not users:
        print("No hay usuarios.")
        return
    print(f"{'CORREO':<36} {'NOMBRE':<24} {'ROL':<18} {'ACTIVO':<7} CREADO")
    for user in users:
        print(f"{user['email']:<36} {user['name']:<24} {_role_label(user['role']):<18} "
              f"{'sí' if user['is_active'] else 'no':<7} {user['created_at'][:10]}")
    print(f"\n{len(users)} usuario(s).")


def cmd_create(api: Api) -> None:
    name = ask("Nombre")
    email = ask("Correo")
    role = ROLES[select("Rol:", [label for _, label in ROLES])][0]
    password = ask_new_password()
    user = api.request("POST", "/users", {"name": name, "email": email, "role": role, "password": password})
    print(f"Usuario creado: {user['email']} ({_role_label(user['role'])}).")


def cmd_passwd(api: Api) -> None:
    users = api.request("GET", "/users")
    if not users:
        raise SystemExit("No hay usuarios.")
    user = users[select("Usuario:", [_user_option(u) for u in users])]
    password = ask_new_password()
    api.request("PUT", f"/users/{quote(user['id'])}/password", {"password": password})
    print(f"Contraseña actualizada para {user['email']}.")


COMMANDS = {
    "create": ("Crear usuario", cmd_create),
    "list": ("Listar usuarios", cmd_list),
    "passwd": ("Cambiar contraseña", cmd_passwd),
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Gestiona los usuarios locales de ARIA a través de la API.")
    parser.add_argument("command", nargs="?", choices=list(COMMANDS), help="sin comando: menú interactivo")
    parser.add_argument("--api-url", default=os.getenv("ARIA_API_URL") or None,
                        help="URL base de la API (env ARIA_API_URL; por defecto se pregunta, http://localhost:8000)")
    args = parser.parse_args()

    try:
        command = args.command or list(COMMANDS)[select("¿Qué quieres hacer?", [label for label, _ in COMMANDS.values()])]
        api_url = args.api_url or ask("URL de API", "http://localhost:8000")
        token = os.getenv("ARIA_BOOTSTRAP_TOKEN") or getpass.getpass("Token de aprovisionamiento: ")
        COMMANDS[command][1](Api(api_url, token))
    except (KeyboardInterrupt, EOFError):
        print()
        raise SystemExit("Cancelado.") from None


if __name__ == "__main__":
    main()
