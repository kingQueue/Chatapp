"""The ticket worker uses Character Room's declarative FreeCAD adapter."""
from importlib import import_module
import os
from pathlib import Path


TOOL_ID = "freecad_workbench"
NAME = TOOL_ID + "__cad_create"
DESCRIPTION = (
    "Create editable FreeCAD, STEP and STL files from 1–32 primitives in millimetres. "
    "Use a new relative output stem such as models/bracket. Supported shapes are "
    "box(length,width,height), cylinder(radius,height), sphere(radius), and "
    "cone(radius,radius2,height). Optional positions x,y,z and rotations rx,ry,rz "
    "are in millimetres/degrees. The first primitive must add. Later primitives "
    "may add or cut. Use only declarative geometry."
)
DIMENSIONS = {
    "box": ["length", "width", "height"],
    "cylinder": ["radius", "height"],
    "sphere": ["radius"],
    "cone": ["radius", "radius2", "height"],
}
TRANSFORM = {field: {"type": "number"} for field in ("x", "y", "z", "rx", "ry", "rz")}
PARAMETERS = {
    "type": "object", "required": ["output", "shapes"], "additionalProperties": False,
    "properties": {
        "output": {"type": "string", "description": "A fresh relative filename stem without an extension."},
        "shapes": {"type": "array", "minItems": 1, "maxItems": 32, "items": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": list(DIMENSIONS)},
                "operation": {"type": "string", "enum": ["add", "cut"]},
                **{field: {"type": "number", "exclusiveMinimum": 0}
                   for field in ("length", "width", "height", "radius", "radius2")},
                **TRANSFORM,
            },
            "required": ["type"], "additionalProperties": False,
        }},
    },
}


def schema(tool_name=NAME):
    return {"type": "function", "function": {
        "name": tool_name, "description": DESCRIPTION, "parameters": PARAMETERS,
    }}


def generate(project, args):
    if set(args) != {"output", "shapes"}:
        raise ValueError("Provide output and shapes.")
    shapes = args["shapes"]
    if not isinstance(shapes, list):
        raise ValueError("Supply shapes as a list.")
    for shape in shapes:
        if not isinstance(shape, dict) or not isinstance(shape.get("type"), str) or shape["type"] not in DIMENSIONS:
            raise ValueError("Use only supported declarative primitives.")
        allowed = {"type", "operation", *DIMENSIONS[shape["type"]], *TRANSFORM}
        if set(shape) - allowed:
            raise ValueError("A CAD shape contains unsupported fields.")
    runtime = import_module("tool_runtime")
    executable = os.getenv("FREECAD_EXECUTABLE") or runtime.discover()["freecad"]
    if not executable or not Path(executable).is_file():
        raise ValueError("Install FreeCAD or configure FREECAD_EXECUTABLE on the PC.")
    project.mkdir(parents=True, exist_ok=True)
    files = runtime.cad_create(project, executable, args, project / ".work")
    return {
        "files": [Path(file).as_posix() for file in files["files"]],
        "units": "mm", "shape_validated": True,
    }
