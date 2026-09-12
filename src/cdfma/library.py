"""YAML loading, validation and id resolution for the library layer.

Per CLAUDE.md §5, ``data/*.yaml`` is the store and the source of truth: this
module reads it, validates it against the ``schema.py`` models, and resolves
ids to objects. It holds no domain content and no derived values — only
loading and lookup.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel, ValidationError

from cdfma.schema import ConnectionType, ElementType, ProjectParameters

_T = TypeVar("_T", bound=BaseModel)


class LibraryError(Exception):
    """Raised for any load-time failure: malformed YAML, a record that
    fails schema validation, or a duplicate id within a collection."""


def _read_yaml(path: Path) -> object:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LibraryError(f"could not read {path}: {exc}") from exc
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise LibraryError(f"{path}: invalid YAML: {exc}") from exc


def _load_records(path: Path, key: str, model: type[_T]) -> dict[str, _T]:
    """Load a top-level ``key: [...]`` list of records from ``path``,
    validate each against ``model``, and return them keyed by id — raising
    on any validation failure or duplicate id.
    """
    document = _read_yaml(path)
    if not isinstance(document, dict) or key not in document:
        raise LibraryError(f"{path}: expected a top-level {key!r} list")
    raw_records = document[key]
    if not isinstance(raw_records, list):
        raise LibraryError(f"{path}: {key!r} must be a list")

    records: dict[str, _T] = {}
    for index, raw_record in enumerate(raw_records):
        try:
            record = model.model_validate(raw_record)
        except ValidationError as exc:
            record_id = raw_record.get("id", "<no id>") if isinstance(raw_record, dict) else "<not a mapping>"
            raise LibraryError(
                f"{path}: {key}[{index}] (id={record_id!r}) failed validation:\n{exc}"
            ) from exc
        record_id = getattr(record, "id")
        if record_id in records:
            raise LibraryError(f"{path}: duplicate id {record_id!r} in {key}")
        records[record_id] = record
    return records


def load_element_types(path: Path) -> dict[str, ElementType]:
    """Load and validate ``element_types.yaml``, keyed by id."""
    return _load_records(path, "element_types", ElementType)


def append_element_type(path: Path, element_type: ElementType) -> None:
    """Add one new element type to ``element_types.yaml`` (spec §2.1) —
    the manual-entry path CLAUDE.md §6's Interface (application) section
    describes for the library layer.

    Appends the validated record as text rather than re-serializing the
    whole file: ``data/*.yaml`` carries hand-written comments (PLACEHOLDER
    notes, provenance explanations) that a parse-and-dump round trip would
    silently discard. The rest of the file is never touched.

    Raises ``LibraryError`` if ``element_type.id`` already exists in the
    file — never overwrites a record.
    """
    existing = load_element_types(path)
    if element_type.id in existing:
        raise LibraryError(f"element type id {element_type.id!r} already exists in {path}")
    _append_record(path, "element_types", element_type)


# An empty flow-style list ("key: []") cannot be followed by a block-style
# item on the next line — appending text after it would produce invalid
# YAML. Matched so it can be turned into a bare "key:" block header first.
_EMPTY_FLOW_LIST = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*:)[ \t]*\[[ \t]*\][ \t]*$", re.MULTILINE)


def _append_record(path: Path, key: str, record: BaseModel) -> None:
    text = path.read_text(encoding="utf-8")
    match = _EMPTY_FLOW_LIST.search(text)
    if match is not None and match.group(1) == f"{key}:":
        text = text[: match.start()] + f"{key}:" + text[match.end() :]
        path.write_text(text, encoding="utf-8")

    block = yaml.safe_dump(
        [record.model_dump(mode="json")], default_flow_style=False, sort_keys=False, allow_unicode=True
    )
    indented = "\n".join(("  " + line if line else line) for line in block.splitlines())
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n" + indented + "\n")


def load_connection_types(path: Path) -> dict[str, ConnectionType]:
    """Load and validate ``connection_types.yaml``, keyed by id."""
    return _load_records(path, "connection_types", ConnectionType)


def append_connection_type(path: Path, connection_type: ConnectionType) -> None:
    """Add one new connection type to ``connection_types.yaml`` (spec
    §2.4) — the manual-entry path for connections, mirroring
    ``append_element_type`` above (see its docstring for why this appends
    text rather than re-serializing the file).

    Raises ``LibraryError`` if ``connection_type.id`` already exists.
    """
    existing = load_connection_types(path)
    if connection_type.id in existing:
        raise LibraryError(f"connection type id {connection_type.id!r} already exists in {path}")
    _append_record(path, "connection_types", connection_type)


def load_project_parameters(path: Path) -> ProjectParameters:
    """Load and validate the single ``project_parameters.yaml`` record."""
    document = _read_yaml(path)
    if not isinstance(document, dict) or "project_parameters" not in document:
        raise LibraryError(f"{path}: expected a top-level 'project_parameters' mapping")
    raw = document["project_parameters"]
    try:
        return ProjectParameters.model_validate(raw)
    except ValidationError as exc:
        raise LibraryError(f"{path}: project_parameters failed validation:\n{exc}") from exc


class Library:
    """The loaded, validated library: element types, connection types and
    project parameters, resolved by id.
    """

    def __init__(
        self,
        element_types: dict[str, ElementType],
        connection_types: dict[str, ConnectionType],
        project_parameters: ProjectParameters,
    ) -> None:
        self.element_types = element_types
        self.connection_types = connection_types
        self.project_parameters = project_parameters

    @classmethod
    def load(
        cls,
        directory: Path,
        *,
        element_types_file: str = "element_types.yaml",
        connection_types_file: str = "connection_types.yaml",
        project_parameters_file: str = "project_parameters.yaml",
    ) -> Library:
        """Load all three library files from ``directory``."""
        return cls(
            element_types=load_element_types(directory / element_types_file),
            connection_types=load_connection_types(directory / connection_types_file),
            project_parameters=load_project_parameters(directory / project_parameters_file),
        )

    def get_element_type(self, element_type_id: str) -> ElementType:
        try:
            return self.element_types[element_type_id]
        except KeyError:
            raise LibraryError(f"no element type with id {element_type_id!r}") from None

    def get_connection_type(self, connection_type_id: str) -> ConnectionType:
        try:
            return self.connection_types[connection_type_id]
        except KeyError:
            raise LibraryError(f"no connection type with id {connection_type_id!r}") from None
