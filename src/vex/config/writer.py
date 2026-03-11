"""Config writer — read-modify-write for vex.toml / config.toml.

Preserves comments and formatting by doing line-level TOML manipulation
rather than full serialization.
"""

from __future__ import annotations

import re
from pathlib import Path


def find_config_path() -> Path | None:
    """Return the first existing config file, or the default path to create."""
    candidates = [
        Path.cwd() / "vex.toml",
        Path.home() / ".vex" / "config.toml",
    ]
    for p in candidates:
        if p.is_file():
            return p
    # Default: create in ~/.vex/config.toml
    return candidates[1]


def config_set(key: str, value: str, config_path: Path | None = None) -> Path:
    """Set a dotted key in the TOML config file.

    Examples:
        config_set("llm.provider", "anthropic")
        config_set("security.autonomy_level", "3")
        config_set("network.enabled", "true")
        config_set("telegram.allowed_users", "[123, 456]")

    Returns the path of the config file that was written.
    """
    path = config_path or find_config_path()
    if path is None:
        path = Path.home() / ".vex" / "config.toml"

    path.parent.mkdir(parents=True, exist_ok=True)

    # Read existing content
    if path.is_file():
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    else:
        lines = []

    # Parse the dotted key into section parts + leaf key
    parts = key.split(".")
    if len(parts) == 1:
        section_parts: list[str] = []
        leaf = parts[0]
    else:
        section_parts = parts[:-1]
        leaf = parts[-1]

    # Convert value string to appropriate TOML representation
    toml_value = _to_toml_value(value)

    # Build the section header we're looking for
    section_header = ".".join(section_parts) if section_parts else None

    # Try to find and update the key in-place
    updated = _update_in_place(lines, section_header, leaf, toml_value)

    if not updated:
        # Key/section not found — append it
        _append_key(lines, section_header, leaf, toml_value)

    path.write_text("".join(lines), encoding="utf-8")
    return path


def config_get(key: str, config_path: Path | None = None) -> str | None:
    """Read a dotted key from the TOML config file (raw string value)."""
    path = config_path or find_config_path()
    if path is None or not path.is_file():
        return None

    # Use tomllib for reliable reading
    import sys
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        try:
            import tomllib  # type: ignore[import-not-found]
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]

    with open(path, "rb") as f:
        config = tomllib.load(f)

    parts = key.split(".")
    obj = config
    for part in parts:
        if isinstance(obj, dict) and part in obj:
            obj = obj[part]
        else:
            return None
    return str(obj)


def _to_toml_value(value: str) -> str:
    """Convert a CLI string value to a TOML value representation."""
    low = value.lower()

    # Booleans
    if low in ("true", "false"):
        return low

    # Integer
    try:
        int(value)
        return value
    except ValueError:
        pass

    # Float
    try:
        float(value)
        return value
    except ValueError:
        pass

    # Array (user typed something like [1, 2, 3] or ["a", "b"])
    if value.startswith("[") and value.endswith("]"):
        return value

    # Otherwise, it's a string — quote it
    return f'"{value}"'


# Regex to match a TOML section header like [llm] or [llm.ollama]
_SECTION_RE = re.compile(r"^\[([^\[\]]+)\]\s*(?:#.*)?$")
# Regex to match a key = value line (possibly commented out)
_KEY_RE = re.compile(r"^#?\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*=")


def _update_in_place(
    lines: list[str],
    section_header: str | None,
    leaf: str,
    toml_value: str,
) -> bool:
    """Try to find the key in-place and update it. Returns True if updated."""
    current_section: str | None = None
    target_section = section_header

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Track current section
        m = _SECTION_RE.match(stripped)
        if m:
            current_section = m.group(1).strip()
            continue

        if current_section != target_section:
            continue

        # Check if this line has our key (even if commented out)
        km = _KEY_RE.match(stripped)
        if km and km.group(1) == leaf:
            # Determine indentation from the original line
            indent = line[: len(line) - len(line.lstrip())]
            # Build the new line (uncomment if necessary)
            newline = f"{indent}{leaf} = {toml_value}\n"
            lines[i] = newline
            return True

    return False


def _append_key(
    lines: list[str],
    section_header: str | None,
    leaf: str,
    toml_value: str,
) -> None:
    """Append the key to the correct section, creating the section if needed."""
    new_line = f"{leaf} = {toml_value}\n"

    if section_header is None:
        # Top-level key — insert at the beginning (after any comments)
        insert_at = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                break
            insert_at = i + 1
        lines.insert(insert_at, new_line)
        return

    # Find the section
    target = f"[{section_header}]"
    for i, line in enumerate(lines):
        stripped = line.strip()
        m = _SECTION_RE.match(stripped)
        if m and m.group(1).strip() == section_header:
            # Found the section — find the end of it (next section or EOF)
            insert_at = i + 1
            for j in range(i + 1, len(lines)):
                jstripped = lines[j].strip()
                if _SECTION_RE.match(jstripped):
                    break
                insert_at = j + 1
            lines.insert(insert_at, new_line)
            return

    # Section doesn't exist — append section + key at the end
    if lines and not lines[-1].endswith("\n"):
        lines.append("\n")
    lines.append(f"\n[{section_header}]\n")
    lines.append(new_line)
