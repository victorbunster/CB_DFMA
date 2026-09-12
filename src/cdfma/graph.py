"""The project graph: instances, composition edges, connection instances,
and manually asserted dependency edges (CLAUDE.md §2, spec §2.5).

Holds facts only, same as ``library.py``: no derived values, no
judgements. Composition and dependency edges are plain id pairs — they
carry no fields of their own — so they are defined here rather than in
``schema.py``, which holds the richer fact and output types shared across
modules.

Derived dependency edges (from ``access_direction``/``clearance``, G3) are
out of scope for Slice 1 (CLAUDE.md §2); every edge here is manually
asserted, and the graph does not label "asserted vs. derived" because
there is only one kind.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

import yaml
from pydantic import ValidationError

from cdfma.library import Library, LibraryError
from cdfma.schema import ConnectionInstance, Instance


class CompositionEdge(NamedTuple):
    """Part-of: ``child_instance_id`` is part of ``parent_instance_id``."""

    parent_instance_id: str
    child_instance_id: str


class DependencyEdge(NamedTuple):
    """Removal of ``dependent_instance_id`` requires prior removal of
    ``blocking_instance_id``."""

    dependent_instance_id: str
    blocking_instance_id: str


class GraphError(Exception):
    """Raised for a malformed graph, a duplicate id, a dangling
    reference to an instance id, or (via ``validate_against_library``) a
    reference to an element/connection type id the library doesn't have.
    """


class Graph:
    """One option's project graph: its instances and edges."""

    def __init__(
        self,
        instances: dict[str, Instance],
        connection_instances: dict[str, ConnectionInstance],
        composition_edges: list[CompositionEdge],
        dependency_edges: list[DependencyEdge],
    ) -> None:
        self.instances = instances
        self.connection_instances = connection_instances
        self.composition_edges = composition_edges
        self.dependency_edges = dependency_edges
        self._validate_internal_references()

    def _validate_internal_references(self) -> None:
        for connection in self.connection_instances.values():
            for instance_id in (connection.element_instance_id, connection.host_instance_id):
                if instance_id not in self.instances:
                    raise GraphError(
                        f"connection instance {connection.id!r} references "
                        f"unknown instance {instance_id!r}"
                    )
        for edge in self.composition_edges:
            for instance_id in (edge.parent_instance_id, edge.child_instance_id):
                if instance_id not in self.instances:
                    raise GraphError(f"composition edge references unknown instance {instance_id!r}")
        for edge in self.dependency_edges:
            for instance_id in (edge.dependent_instance_id, edge.blocking_instance_id):
                if instance_id not in self.instances:
                    raise GraphError(f"dependency edge references unknown instance {instance_id!r}")

    def validate_against_library(self, library: Library) -> None:
        """Check every element_type_id / connection_type_id reference
        against a loaded library. Separate from construction because a
        graph can be built and internally checked before a library is at
        hand; the engine calls this before binding rules.
        """
        for instance in self.instances.values():
            if instance.element_type_id not in library.element_types:
                raise GraphError(
                    f"instance {instance.id!r} references unknown element type "
                    f"{instance.element_type_id!r}"
                )
        for connection in self.connection_instances.values():
            if connection.connection_type_id not in library.connection_types:
                raise GraphError(
                    f"connection instance {connection.id!r} references unknown "
                    f"connection type {connection.connection_type_id!r}"
                )

    def instances_of_element_type(self, element_type_id: str) -> list[Instance]:
        """All instances typed by ``element_type_id`` — the count of the
        result is the "instance count" of spec §5.4's assembly quantity."""
        return sorted(
            (i for i in self.instances.values() if i.element_type_id == element_type_id),
            key=lambda i: i.id,
        )

    def connections_of_instance(self, instance_id: str) -> list[ConnectionInstance]:
        """Every connection touching ``instance_id`` (as element or host side)."""
        return sorted(
            (
                c
                for c in self.connection_instances.values()
                if instance_id in (c.element_instance_id, c.host_instance_id)
            ),
            key=lambda c: c.id,
        )

    def host_of(self, connection: ConnectionInstance) -> Instance:
        return self.instances[connection.host_instance_id]

    def element_of(self, connection: ConnectionInstance) -> Instance:
        return self.instances[connection.element_instance_id]


def _parse_instances(raw: list[dict], context: str) -> dict[str, Instance]:
    instances: dict[str, Instance] = {}
    for index, raw_instance in enumerate(raw):
        try:
            instance = Instance.model_validate(raw_instance)
        except ValidationError as exc:
            raise GraphError(f"{context}: instances[{index}] failed validation:\n{exc}") from exc
        if instance.id in instances:
            raise GraphError(f"{context}: duplicate instance id {instance.id!r}")
        instances[instance.id] = instance
    return instances


def _parse_connection_instances(raw: list[dict], context: str) -> dict[str, ConnectionInstance]:
    connections: dict[str, ConnectionInstance] = {}
    for index, raw_connection in enumerate(raw):
        try:
            connection = ConnectionInstance.model_validate(raw_connection)
        except ValidationError as exc:
            raise GraphError(
                f"{context}: connection_instances[{index}] failed validation:\n{exc}"
            ) from exc
        if connection.id in connections:
            raise GraphError(f"{context}: duplicate connection instance id {connection.id!r}")
        connections[connection.id] = connection
    return connections


def _parse_edges(raw: list[dict], edge_type: type[CompositionEdge | DependencyEdge], keys: tuple[str, str], context: str):
    edges = []
    for index, raw_edge in enumerate(raw):
        if not isinstance(raw_edge, dict) or set(raw_edge) != set(keys):
            raise GraphError(f"{context}: edge[{index}] must have exactly the keys {keys}")
        edges.append(edge_type(*(raw_edge[key] for key in keys)))
    return edges


def _parse_graph(raw: dict, context: str) -> Graph:
    return Graph(
        instances=_parse_instances(raw.get("instances", []), context),
        connection_instances=_parse_connection_instances(raw.get("connection_instances", []), context),
        composition_edges=_parse_edges(
            raw.get("composition_edges", []),
            CompositionEdge,
            ("parent_instance_id", "child_instance_id"),
            context,
        ),
        dependency_edges=_parse_edges(
            raw.get("dependency_edges", []),
            DependencyEdge,
            ("dependent_instance_id", "blocking_instance_id"),
            context,
        ),
    )


def load_options(path: Path) -> dict[str, Graph]:
    """Load ``project_wall.yaml``: a top-level ``options`` mapping of
    option id -> graph (spec §1: "two compared variants"). Each option is
    independently validated; cross-references to the library are checked
    separately via ``Graph.validate_against_library`` once a ``Library``
    is available.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise GraphError(f"could not read {path}: {exc}") from exc
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise GraphError(f"{path}: invalid YAML: {exc}") from exc

    if not isinstance(document, dict) or "options" not in document:
        raise GraphError(f"{path}: expected a top-level 'options' mapping")
    raw_options = document["options"]
    if not isinstance(raw_options, dict) or not raw_options:
        raise GraphError(f"{path}: 'options' must be a non-empty mapping of option id -> graph")

    options: dict[str, Graph] = {}
    for option_id, raw_graph in raw_options.items():
        options[option_id] = _parse_graph(raw_graph or {}, f"{path}:options.{option_id}")
    return options


# An empty flow-style options mapping ("options: {}") cannot be followed
# by a block-style key on the next line, same issue as library.py's
# equivalent for element/connection types.
_EMPTY_FLOW_OPTIONS = re.compile(r"^(options:)[ \t]*\{[ \t]*\}[ \t]*$", re.MULTILINE)


def append_option(path: Path, option_id: str, graph: Graph) -> None:
    """Add one new option (a named project graph) to a project file's
    top-level ``options:`` mapping — the manual graph-building path for
    ``gui.py``'s "Build wall" tab.

    Like ``library.py``'s ``append_element_type``/``append_connection_type``,
    this inserts the new block as text rather than re-serializing the
    whole file, so hand-written comments survive untouched. ``options:``
    is a mapping, not a list, so unlike those two the insertion point is
    "immediately before the next top-level key, or end of file" — found
    by scanning the raw text, not assumed from a fixed layout.

    Creates ``path`` with a bare ``options:`` mapping if it doesn't exist
    yet, rather than requiring it to be pre-seeded.

    Raises ``GraphError`` if ``option_id`` already exists in the file.
    Does not validate ``graph`` against a ``Library`` — call
    ``graph.validate_against_library`` first if that matters to the
    caller (it does for ``gui.py``, which does so before calling this).
    """
    if path.exists():
        text = path.read_text(encoding="utf-8")
        try:
            document = yaml.safe_load(text) or {}
        except yaml.YAMLError as exc:
            raise GraphError(f"{path}: invalid YAML: {exc}") from exc
        if not isinstance(document, dict) or "options" not in document:
            raise GraphError(f"{path}: expected a top-level 'options' mapping")
        existing_options = document["options"] or {}
        if option_id in existing_options:
            raise GraphError(f"{path}: option id {option_id!r} already exists")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = "options:\n"

    match = _EMPTY_FLOW_OPTIONS.search(text)
    if match is not None:
        text = text[: match.start()] + "options:" + text[match.end() :]

    option_dict = {
        "instances": [
            {"id": instance.id, "element_type_id": instance.element_type_id, "label": instance.label}
            for instance in sorted(graph.instances.values(), key=lambda i: i.id)
        ],
        "connection_instances": [
            {
                "id": connection.id,
                "connection_type_id": connection.connection_type_id,
                "element_instance_id": connection.element_instance_id,
                "host_instance_id": connection.host_instance_id,
            }
            for connection in sorted(graph.connection_instances.values(), key=lambda c: c.id)
        ],
        "composition_edges": [
            {"parent_instance_id": edge.parent_instance_id, "child_instance_id": edge.child_instance_id}
            for edge in graph.composition_edges
        ],
        "dependency_edges": [
            {"dependent_instance_id": edge.dependent_instance_id, "blocking_instance_id": edge.blocking_instance_id}
            for edge in graph.dependency_edges
        ],
    }
    block = yaml.safe_dump(
        {option_id: option_dict}, default_flow_style=False, sort_keys=False, allow_unicode=True
    )
    indented = "\n".join(("  " + line if line else line) for line in block.splitlines())

    options_match = re.search(r"^options:[ \t]*$", text, re.MULTILINE)
    if options_match is None:
        raise GraphError(f"{path}: expected a top-level 'options:' line")
    search_from = options_match.end()
    next_top_level = re.search(r"^[A-Za-z_][A-Za-z0-9_]*:", text[search_from:], re.MULTILINE)
    insertion_point = search_from + next_top_level.start() if next_top_level else len(text)

    new_text = text[:insertion_point] + indented + "\n\n" + text[insertion_point:]
    path.write_text(new_text, encoding="utf-8")
