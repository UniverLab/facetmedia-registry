"""This registry as facet itself parses it.

The core is a dev dependency of the registry suite, so the tests that care
about what a piece keeps after validation load the manifests through
``facetmedia.registry`` and check them with ``facetmedia.schema.validate``.
A hand-built request would not prove that an omitted ``width`` or ``height``
survives facet's own default filling and reaches the runner.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from facetmedia.registry import load_registry
from facetmedia.registry_types import Capability

ROOT = Path(__file__).resolve().parents[1]


@cache
def facet_capability(capability_id: str) -> Capability:
    """One capability of one package's manifest, as facet loads it."""
    package_id, _, _name = capability_id.partition(".")
    package = load_registry(ROOT).packages[package_id]
    return next(cap for cap in package.capabilities if cap.id == capability_id)
