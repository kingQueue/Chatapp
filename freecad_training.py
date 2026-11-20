"""Build a small Soup tool-calling corpus by running every example in FreeCAD."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from uuid import uuid4

from ticketing.freecad import NAME, generate, schema
from ticketing.store import encode


def box(length, width, height, **placement):
    return dict(type="box", length=length, width=width, height=height, **placement)


def cylinder(radius, height, **placement):
    return dict(type="cylinder", radius=radius, height=height, **placement)


def examples():
    for number in range(1, 13):
        width = 20 + number
        length = 34 + 2 * number
        height = 3 + number % 4
        bore = 2 + (number % 3) / 2
        for name, instruction, shapes in [
            ("mounting-plate", f"Make a {length} × {width} × {height} mm plate with two Ø{2*bore:g} mm "
             f"through holes. Put their centres at X=6 and X={length-6}, both at Y={width/2:g}.",
             [box(length, width, height), *[
                 cylinder(bore, height + 2, operation="cut", x=x, y=width / 2, z=-1)
                 for x in (6, length - 6)
             ]]),
            ("tube-spacer", f"Model a cylindrical {width} mm OD spacer, {height+6} mm long, "
             f"with a centred Ø{2*bore:g} mm axial bore.",
             [cylinder(width / 2, height + 6), cylinder(bore, height + 8, operation="cut", z=-1)]),
            ("angle-bracket", f"Make an L bracket. The base is {length} × {width} × {height} mm. "
             f"Add a {height} mm thick upright at the rear, {width} mm across, rising "
             f"{height+12} mm above the bottom.",
             [box(length, width, height), box(height, width, height + 12, x=length-height)]),
            ("boss-plate", f"Create a {length} × {width} × {height} mm rectangular base "
             f"with a centred Ø{2*(bore+3):g} mm boss protruding 4 mm and a "
             f"coaxial Ø{2*bore:g} mm hole through both.",
             [box(length, width, height),
              cylinder(bore + 3, 5, x=length/2, y=width/2, z=height-1),
              cylinder(bore, height + 6, operation="cut", x=length/2, y=width/2, z=-1)]),
        ]:
            yield number, name, instruction, shapes


def verified(example):
    number, family, instruction, shapes = example
    output = f"models/{family}-{number:02}"
    arguments = {"output": output, "shapes": shapes}
    with TemporaryDirectory(prefix="freecad-example-") as directory:
        result = generate(Path(directory), arguments)
        if not all((Path(directory) / file).stat().st_size for file in result["files"]):
            raise RuntimeError(f"FreeCAD produced an empty file for {output}.")
    tool = schema()
    handoff = {
        "work_done": f"Built and validated the {family.replace('-', ' ')} in FreeCAD.",
        "files_produced": result["files"],
        "unresolved_issues": [],
        "next_agent_needs": "Inspect the native FreeCAD model and verify the requested dimensions.",
    }
    messages = [
        {"role": "system", "content": f"You are a FreeCAD agent. Build editable geometry with {NAME}. "
         "Report the tool's actual files and return a JSON handoff with work_done, files_produced, "
         "unresolved_issues and next_agent_needs."},
        {"role": "user", "content": instruction + f" Save the files with the stem {output}."},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "cad-1", "type": "function", "function": {"name": NAME, "arguments": encode(arguments)}},
        ]},
        {"role": "tool", "tool_call_id": "cad-1", "content": encode(result)},
        {"role": "assistant", "content": encode(handoff)},
    ]
    return number in {5, 10}, {"tools": [tool], "messages": messages}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--room", type=Path, required=True, help="Character Room folder containing tool_runtime.py.")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent / "datasets")
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    if not (args.room / "tool_runtime.py").is_file():
        parser.error("Choose a Character Room folder containing tool_runtime.py.")
    sys.path.insert(0, str(args.room.resolve()))
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        rows = list(executor.map(verified, examples()))
    args.output.mkdir(parents=True, exist_ok=True)
    version = uuid4().hex
    for holdout, name in [(False, f"cad_agent--{version}.jsonl"), (True, f"cad-holdout-{version}.jsonl")]:
        selected = [encode(row) for held, row in rows if held == holdout]
        with (args.output / name).open("x", encoding="utf-8", newline="\n") as file:
            file.write("\n".join(selected) + "\n")
        print(f"{len(selected)} FreeCAD-verified examples: {args.output / name}", flush=True)


if __name__ == "__main__":
    main()
