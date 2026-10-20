# Dread Drawer

A small, local-first Downloads folder organizer. Dread Drawer scans direct files in a folder you choose, sends **filenames only** to a local Ollama model for sorting and clearer names, and waits for you to review and approve all moves.

## Requirements

- Python 3.10 or newer with Tkinter
- [Ollama](https://ollama.com/) running locally
- An Ollama model, for example `gemma3:4b`

Install a model in Ollama before starting the app:

```powershell
ollama pull gemma3:4b
```

Then run the app from this folder:

```powershell
python .\dread_drawer.py
```

## Safety and privacy

- Only direct files in the selected folder are considered; subfolders are not scanned.
- The initial folder is the `downloads` subfolder next to `dread_drawer.py`; use **Browse…** to choose another folder.
- File contents are never read. The app sends filenames and file-extension hints only to `http://localhost:11434`.
- Inference is configured for CPU mode so it works with Ollama installations whose CUDA/PTX runtime is incompatible; this can be slower than GPU inference.
- The app refuses non-local model endpoints and unsafe names or paths.
- Nothing moves until you review the suggestions and confirm. Double-click the first column to skip or include a row; double-click a suggested destination to edit its category or filename.
- Edited destinations must use one of the listed category folders and keep the original file extension.
- Existing destinations are never intentionally overwritten; files are never deleted.
- The last successful tidy-up can be undone with **Undo last tidy-up**.
- An undo record named `.dread_drawer_undo.json` is kept in the selected folder after a successful tidy-up and removed when you undo it.

## Prototype limits

This first version handles ordinary files in one folder and offers broad file categories. It does not inspect document contents, recurse through folders, or rename files in place. It uses extension-based hints to keep suggestions grounded, but review the model's output before approving moves.
