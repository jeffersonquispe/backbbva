"""
Carga manual de variables de entorno desde un archivo .env, sin dependencia
extra de python-dotenv. Antes esta misma función vivía copiada y pegada en
app/app.py, scripts/validate_keys.py y scripts/benchmark_eval.py.
"""

import os


def parse_dotenv(env_path: str, override: bool = False) -> None:
    """Lee `env_path` y setea cada `CLAVE=valor` en `os.environ`.

    Si `override` es False (default), no pisa variables que ya existan en el
    entorno (útil cuando el shell/CI ya inyectó credenciales reales).
    """
    if not os.path.exists(env_path):
        return
    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                k = k.strip()
                if override or k not in os.environ:
                    os.environ[k] = v.strip()
