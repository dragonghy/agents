"""Shared utilities for loading agents.yaml with environment variable resolution.

Provides:
  - load_dotenv(path): Parse a .env file and inject into os.environ
  - resolve_env_vars(obj): Recursively replace ${VAR} and ${VAR:-default} in strings
"""

import os
import re

_ENV_VAR_RE = re.compile(r"\$\{([^}]+)\}")


def load_dotenv(dotenv_path):
    """Load a .env file into os.environ (does not override existing vars)."""
    if not os.path.isfile(dotenv_path):
        return
    with open(dotenv_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            # Don't override existing environment variables
            if key not in os.environ:
                os.environ[key] = value


def _resolve_match(match):
    """Resolve a single ${VAR} or ${VAR:-default} match."""
    expr = match.group(1)
    if ":-" in expr:
        var_name, _, default = expr.partition(":-")
        return os.environ.get(var_name.strip(), default)
    return os.environ.get(expr.strip(), match.group(0))


def resolve_env_vars(obj):
    """Recursively resolve ${VAR} and ${VAR:-default} patterns in a config object.

    Walks dicts and lists. String values containing ${...} are replaced
    with the corresponding environment variable value. If the entire string
    is a single ${VAR} reference (no surrounding text) and the var is not set,
    the original placeholder string is preserved.

    Returns a new object (does not mutate the input).
    """
    if isinstance(obj, str):
        return _ENV_VAR_RE.sub(_resolve_match, obj)
    if isinstance(obj, dict):
        return {k: resolve_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [resolve_env_vars(item) for item in obj]
    return obj
