# FreeCAD Designer

The **FreeCAD Designer** character creates original, editable models in the **FreeCAD Workbench** conversation. Tickets can assign geometry work to `cad_agent`. Both surfaces use the same declarative FreeCAD tool and request shape. The tool generates native `.FCStd`, STEP, STL and a small JSON record of the primitive operations. It verifies that FreeCAD produced valid geometry before reporting success.

## Set up and try the base model

Start Character Room and install FreeCAD. If Ollama does not already have the base model, run `ollama pull qwen3-coder:30b`. Then use the Python environment you installed with Tickets.

```powershell
.venv\Scripts\python.exe configure_freecad.py
.venv\Scripts\python.exe configure_freecad.py --smoke
```

The smoke test asks the actual character to make a spacer with a through-hole and checks for the produced FreeCAD file. Open the preconfigured **FreeCAD Workbench** conversation for future requests. Its project directory defaults to a folder beside the checkout. Use `--project` to choose a different location outside the app directory. Ticket jobs use their own `freecad-project/<ticket-id>/` folders. With `TICKETS_DISPATCH=true` and `cad_agent` enabled, assign a design ticket and move it to Ready.

## Prepare and validate training

Use [Qwen3-Coder 30B in Ollama](https://ollama.com/library/qwen3-coder:30b) for inference and the matching [Qwen training checkpoint](https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct) for fine-tuning. The checkpoint contains about 61 GB of files. Keep model-cache and deployment space available in addition to checkpoint storage.

Generate the starter dataset with the command below. It executes FreeCAD on every example and verifies the shape and the four output files. This produces 40 tool-calling training records and 8 separate holdout records spanning four geometry families. The corpus is intentionally small and measures basic tool use. The holdout examples and the racecar task are outside the training dataset.

```powershell
.venv\Scripts\python.exe freecad_training.py --room "C:\path\to\CharacterRoom"
```

In **Tickets → Training**, select `cad_agent`, the generated `cad_agent--….jsonl` dataset and the prefilled base checkpoint. **Validate setup** runs the real Soup validator and training dry run, then records the outcome in Training jobs. **Start training** runs Soup with the editable 4-bit LoRA and layer-streaming settings in `training-profiles/cad_agent.yaml`. The runtime needs the Soup training extra and a working GPU training backend. `SOUP_EXECUTABLE` can point to a compatible local Soup environment.

Native Windows ROCm does not support ML training on the documented Radeon stack. Ollama inference on Windows can still use the installed Radeon GPU. Use a supported Linux or WSL ROCm stack, or a CUDA training machine, and verify that the chosen backend and Soup version can perform a training step with this checkpoint. [AMD Radeon limitations](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/limitations/limitationsrad.html) · [Soup layer streaming](https://github.com/MakazhanAlpamys/Soup/blob/main/docs/performance-and-quantization.md#layer-streaming-beta-v0720-nf4-v0722-disk--wider-archs-v0723-preference-losses-v0724)

To run Soup from WSL, use Ubuntu 24.04 in WSL 2 and set up the AMD GPU runtime and ROCm PyTorch in that distribution. Verify the GPU with `rocminfo` and a PyTorch GPU backward pass, then install Soup in the same Linux environment. Set `SOUP_WSL_DISTRO=Ubuntu-24.04` and set `SOUP_EXECUTABLE` to the absolute Linux path of that environment's `soup` executable. Restart Character Room. Training logs, datasets and adapters remain accessible from Windows through the Tickets project folder. [AMD WSL setup](https://rocm.docs.amd.com/projects/rocm-cli/en/latest/install/wsl.html)

## Deploy a completed model

Use Soup’s GGUF export and Ollama deployment workflow after an actual training job saves a checkpoint. Preserve a Qwen3-Coder-compatible chat/tool template and verify the imported model can make a native tool call before switching the character. Then run `configure_freecad.py --model <installed-ollama-model> --smoke`, update `cad_agent.model` in `agents.yaml`, and restart Character Room. Compare holdout tool-call and geometry checks with the base model before assigning the final demo. [Soup serving and export documentation](https://github.com/MakazhanAlpamys/Soup/blob/main/docs/serving-and-export.md)

## Racecar ticket brief

After deploying the trained agent, create and assign a design ticket for an original miniature toy racecar, about 75 mm long, with a low body, cockpit, four visible wheels and a rear wing. Ask the agent to choose the geometry and generate the model autonomously. Acceptance criteria should require an editable FreeCAD model, STEP and STL exports, confirmed file paths and a valid solid with no disconnected pieces for the one-piece version. Keep the embedded tool log as evidence.
