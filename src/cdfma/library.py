"""YAML loading, validation and id resolution for the library layer.

Per CLAUDE.md §5, ``data/*.yaml`` is the store and the source of truth: this
module reads it, validates it against the ``schema.py`` models, and resolves
ids to objects. It holds no domain content and no derived values — only
loading and lookup.
"""

from __future__ import annotations

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


def load_connection_types(path: Path) -> dict[str, ConnectionType]:
    """Load and validate ``connection_types.yaml``, keyed by id."""
    return _load_records(path, "connection_types", ConnectionType)


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
