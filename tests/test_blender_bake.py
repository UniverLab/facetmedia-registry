"""Baking the glTF root's transform into each piece, with no Blender.

A stub ``bpy`` answers the two ops ``bake_pieces`` uses — clearing the
parent while keeping the world transform, then applying rotation and scale
to the mesh data — and records which piece each op touched.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "blender"

STUB_BPY = r'''
"""A stub bpy: only the two object ops the bake uses, and their trail."""

TRAIL = {"calls": []}


class MeshData:
    def __init__(self, name):
        self.name = name
        self.baked = False


class Object:
    def __init__(self, name, kind="MESH", parent=None):
        self.name = name
        self.type = kind
        self.parent = parent
        self.scale = [0.001, 0.001, 0.001]
        self._euler = [0.0, 0.0, 0.0]
        self.selected = False
        self.data = MeshData(name) if kind == "MESH" else object()

    @property
    def rotation_euler(self):
        return list(self._euler)

    def select_set(self, value):
        self.selected = value


class Objects:
    def __init__(self):
        self.active = None


class ViewLayer:
    def __init__(self):
        self.objects = Objects()

    def update(self):
        TRAIL["calls"].append("update")
        return None


class Context:
    def __init__(self):
        self.view_layer = ViewLayer()


class ObjectOps:
    def parent_clear(self, **kwargs):
        assert kwargs == {"type": "CLEAR_KEEP_TRANSFORM"}
        obj = context.view_layer.objects.active
        TRAIL["calls"].append(f"parent_clear:{obj.name}")
        obj.parent = None

    def transform_apply(self, location=False, rotation=True, scale=True):
        obj = context.view_layer.objects.active
        TRAIL["calls"].append(f"transform_apply:{obj.name}")
        assert location is False
        assert rotation is True and scale is True
        obj.scale = [1.0, 1.0, 1.0]
        obj._euler = [0.0, 0.0, 0.0]
        if isinstance(obj.data, MeshData):
            obj.data.baked = True


class Ops:
    def __init__(self):
        self.object = ObjectOps()


context = Context()
ops = Ops()
'''


def _stub_bpy() -> object:
    """Load the bake stub as ``bpy``."""
    sys.modules.pop("bpy", None)
    module = type(sys)("bpy")
    exec(STUB_BPY, module.__dict__)
    sys.modules["bpy"] = module
    return module


def _escena():
    spec = importlib.util.spec_from_file_location("blender_escena", PACKAGE / "escena.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


escena = _escena()


class _Scene:
    def __init__(self, objects):
        self.objects = objects


def test_bake_clears_parent_and_bakes() -> None:
    """A parented piece loses its parent and gains identity rotation/scale."""
    bpy = _stub_bpy()
    root = bpy.Object("estudio", kind="EMPTY")
    root._euler = [-1.5707963, 0.0, 0.0]
    child = bpy.Object("muros", parent=root)
    scene = _Scene([root, child])

    escena.bake_pieces(bpy, scene)

    assert child.parent is None
    assert child.name == "muros"
    assert list(child.rotation_euler) == [0.0, 0.0, 0.0]
    assert list(child.scale) == [1.0, 1.0, 1.0]
    assert child.data.baked is True
    assert root.name == "estudio"
    assert bpy.TRAIL["calls"] == [
        "update",
        "parent_clear:muros",
        "transform_apply:muros",
    ]
    sys.modules.pop("bpy", None)


def test_bake_skips_parentless_and_empties() -> None:
    """Parentless meshes and parented empties never reach the ops."""
    bpy = _stub_bpy()
    root = bpy.Object("estudio", kind="EMPTY")
    lone = bpy.Object("suelo")
    lone.scale = [1.0, 1.0, 1.0]
    helper = bpy.Object("helper", kind="EMPTY", parent=root)
    scene = _Scene([root, lone, helper])

    escena.bake_pieces(bpy, scene)

    assert bpy.TRAIL["calls"] == ["update"]
    assert lone.parent is None
    assert helper.parent is root
    sys.modules.pop("bpy", None)
