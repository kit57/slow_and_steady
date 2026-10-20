import json
import tkinter as tk
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk


APP_DIR = Path(__file__).resolve().parent
DEFAULT_FOLDER = APP_DIR / "downloads"
UNDO_FILE = ".dread_drawer_undo.json"
MODEL_CATEGORIES = (
    "Documents",
    "Images",
    "Audio",
    "Video",
    "Archives",
    "Code",
    "Other",
)
EXTENSION_CATEGORIES = {
    "Documents": {".doc", ".docx", ".md", ".odt", ".pdf", ".ppt", ".pptx", ".rtf", ".txt", ".xls", ".xlsx"},
    "Images": {".bmp", ".gif", ".heic", ".jpeg", ".jpg", ".png", ".svg", ".tif", ".tiff", ".webp"},
    "Audio": {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".wav", ".wma"},
    "Video": {".avi", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".webm", ".wmv"},
    "Archives": {".7z", ".bz2", ".gz", ".rar", ".tar", ".zip"},
    "Code": {".c", ".cpp", ".cs", ".css", ".go", ".html", ".java", ".js", ".json", ".py", ".rs", ".ts", ".xml", ".yaml", ".yml"},
}
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def category_for(filename):
    suffix = Path(filename).suffix.lower()
    for category, extensions in EXTENSION_CATEGORIES.items():
        if suffix in extensions:
            return category
    return "Other"


def valid_stem(stem):
    if not isinstance(stem, str) or not stem or stem in {".", ".."}:
        return False
    if stem[-1] in {".", " "} or any(char in stem for char in '<>:"/\\|?*'):
        return False
    if any(ord(char) < 32 for char in stem):
        return False
    if stem.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES:
        return False
    return len(stem) <= 180


def validate_destination(destination, original_filename):
    parts = Path(destination.replace("\\", "/")).parts
    if len(parts) != 2 or parts[0] not in MODEL_CATEGORIES:
        raise ValueError("Use a category folder and filename, such as Documents/receipt.pdf.")
    filename = parts[1]
    original_suffix = Path(original_filename).suffix
    if Path(filename).suffix.lower() != original_suffix.lower():
        raise ValueError(f"Keep the original file extension ({original_suffix or 'none'}).")
    if not valid_stem(Path(filename).stem):
        raise ValueError("Enter a valid filename without reserved characters or names.")
    return str(Path(parts[0]) / filename)


def request_suggestions(filenames, model, endpoint):
    parsed = urllib.parse.urlparse(endpoint)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Use a local Ollama URL (http://localhost:11434). No remote endpoint is allowed.")
    if not model.strip():
        raise ValueError("Enter the name of an Ollama model installed on this computer.")

    prompt = {
        "filenames": [
            {"id": index, "filename": filename, "extension_category_hint": category_for(filename)}
            for index, filename in enumerate(filenames)
        ],
        "allowed_categories": MODEL_CATEGORIES,
        "instructions": (
            "Suggest a clearer, short filename stem and a category for each file. "
            "Use the category hint when appropriate. Do not invent file contents. "
            "Preserve the original extension by returning only a stem. "
            "Return only JSON matching this shape: "
            '{"suggestions":[{"id":0,"category":"Documents","stem":"tax receipt"}]}.'
        ),
    }
    payload = json.dumps({
        "model": model.strip(),
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": "You organize files using only their filenames. Never include paths."},
            {"role": "user", "content": json.dumps(prompt)},
        ],
        "options": {"temperature": 0.1, "num_gpu": 0},
    }).encode("utf-8")
    request = urllib.request.Request(
        endpoint.rstrip("/") + "/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama returned HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Could not connect to local Ollama: {error.reason}") from error
    except (TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Could not read a valid response from local Ollama: {error}") from error

    content = result.get("message", {}).get("content")
    try:
        suggestions = json.loads(content)["suggestions"]
    except (TypeError, KeyError, json.JSONDecodeError) as error:
        raise RuntimeError("The model response did not contain the expected suggestions JSON.") from error

    if not isinstance(suggestions, list) or len(suggestions) != len(filenames):
        raise RuntimeError("The model returned the wrong number of file suggestions.")
    by_id = {}
    for item in suggestions:
        if not isinstance(item, dict) or not isinstance(item.get("id"), int):
            raise RuntimeError("A model suggestion had an invalid file ID.")
        suggestion_id = item["id"]
        category = item.get("category")
        stem = item.get("stem")
        if suggestion_id in by_id or not 0 <= suggestion_id < len(filenames):
            raise RuntimeError("The model returned duplicate or unknown file IDs.")
        if category not in MODEL_CATEGORIES or not valid_stem(stem):
            raise RuntimeError(f"The model returned an unsafe suggestion for {filenames[suggestion_id]!r}.")
        by_id[suggestion_id] = (category, stem)
    if set(by_id) != set(range(len(filenames))):
        raise RuntimeError("The model did not suggest a destination for every file.")
    return [by_id[index] for index in range(len(filenames))]


def resolved_child(root, relative_path):
    path = Path(relative_path)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"Unsafe path in operation: {relative_path!r}")
    candidate = (root / path).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(f"Path escapes the selected folder: {relative_path!r}")
    return candidate


def move_with_rollback(root, moves):
    completed = []
    try:
        for source, destination in moves:
            if destination.exists():
                raise FileExistsError(f"Destination already exists: {destination.name}")
            destination.parent.mkdir(exist_ok=True)
            if destination.parent.is_symlink():
                raise ValueError(f"Refusing to use a symbolic-link folder: {destination.parent.name}")
            if not destination.parent.resolve().is_relative_to(root):
                raise ValueError("A destination resolves outside the selected folder.")
            source.rename(destination)
            completed.append((source, destination))
    except OSError:
        rollback_errors = []
        for source, destination in reversed(completed):
            try:
                destination.rename(source)
            except OSError as error:
                rollback_errors.append(f"{destination.name}: {error}")
        if rollback_errors:
            raise RuntimeError(
                "A move failed, and some earlier moves could not be rolled back: "
                + "; ".join(rollback_errors)
            )
        raise
    except Exception:
        rollback_errors = []
        for source, destination in reversed(completed):
            try:
                destination.rename(source)
            except OSError as error:
                rollback_errors.append(f"{destination.name}: {error}")
        if rollback_errors:
            raise RuntimeError(
                "An operation failed, and some earlier moves could not be rolled back: "
                + "; ".join(rollback_errors)
            )
        raise


class DreadDrawer:
    def __init__(self, root):
        self.root = root
        self.root.title("Dread Drawer — local file tidy-up")
        self.root.geometry("920x600")
        self.items = []
        self.busy = False

        controls = ttk.Frame(root, padding=10)
        controls.pack(fill="x")
        ttk.Label(controls, text="Folder").grid(row=0, column=0, sticky="w")
        self.folder_var = tk.StringVar(value=str(DEFAULT_FOLDER))
        self.folder_entry = ttk.Entry(controls, textvariable=self.folder_var)
        self.folder_entry.grid(row=0, column=1, sticky="ew", padx=6)
        self.browse_button = ttk.Button(controls, text="Browse…", command=self.browse)
        self.browse_button.grid(row=0, column=2)

        ttk.Label(controls, text="Ollama model").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.model_var = tk.StringVar(value="gemma3:4b")
        self.model_entry = ttk.Entry(controls, textvariable=self.model_var)
        self.model_entry.grid(row=1, column=1, sticky="ew", padx=6, pady=(8, 0))
        self.scan_button = ttk.Button(controls, text="Scan and suggest", command=self.scan)
        self.scan_button.grid(row=1, column=2, pady=(8, 0))
        controls.columnconfigure(1, weight=1)

        self.tree = ttk.Treeview(root, columns=("include", "original", "destination"), show="headings")
        self.tree.heading("include", text="Move?")
        self.tree.heading("original", text="Original filename")
        self.tree.heading("destination", text="Suggested destination")
        self.tree.column("include", width=70, anchor="center", stretch=False)
        self.tree.column("original", width=350)
        self.tree.column("destination", width=470)
        self.tree.pack(fill="both", expand=True, padx=10)
        self.tree.bind("<Double-1>", self.edit_suggestion)

        footer = ttk.Frame(root, padding=10)
        footer.pack(fill="x")
        self.status_var = tk.StringVar(value="Only direct files in the selected folder are scanned. Nothing moves until you apply.")
        ttk.Label(footer, textvariable=self.status_var).pack(side="left", fill="x", expand=True)
        self.undo_button = ttk.Button(footer, text="Undo last tidy-up", command=self.undo, state="disabled")
        self.undo_button.pack(side="right", padx=(6, 0))
        self.apply_button = ttk.Button(footer, text="Apply selected moves", command=self.apply, state="disabled")
        self.apply_button.pack(side="right")

    def selected_root(self):
        root = Path(self.folder_var.get()).expanduser().resolve()
        if not root.is_dir():
            raise ValueError("Choose an existing folder.")
        return root

    def browse(self):
        selected = filedialog.askdirectory(initialdir=self.folder_var.get() or str(Path.home()))
        if selected:
            self.folder_var.set(selected)
            self.refresh_undo_state()

    def refresh_undo_state(self):
        try:
            manifest = self.selected_root() / UNDO_FILE
            enabled = manifest.is_file() and not manifest.is_symlink()
        except (OSError, ValueError):
            enabled = False
        self.undo_button.configure(state="normal" if enabled else "disabled")

    def scan(self):
        if self.busy:
            return
        try:
            root = self.selected_root()
            files = sorted(
                (
                    item for item in root.iterdir()
                    if item.is_file()
                    and not item.is_symlink()
                    and item.name != UNDO_FILE
                    and item.resolve().parent == root
                    and item.suffix.lower() not in {".pyc"}
                    and item.name not in {Path(__file__).name, "README.md", "test_dread_drawer.py"}
                ),
                key=lambda item: item.name.casefold(),
            )
        except (OSError, ValueError) as error:
            messagebox.showerror("Cannot scan folder", str(error))
            return
        if not files:
            self.items = []
            self.populate()
            self.status_var.set("No eligible direct files found in this folder.")
            return
        self.busy = True
        self.scan_button.configure(state="disabled")
        self.apply_button.configure(state="disabled")
        self.status_var.set(f"Asking local Ollama for suggestions for {len(files)} file(s)…")
        self.items = [{"source": item.name, "include": True, "destination": ""} for item in files]
        self.populate()

        def worker():
            try:
                suggestions = request_suggestions(
                    [item.name for item in files],
                    self.model_var.get(),
                    "http://localhost:11434",
                )
                self.root.after(0, lambda: self.show_suggestions(files, suggestions))
            except Exception as error:
                self.root.after(0, lambda error=error: self.scan_failed(error))

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def show_suggestions(self, files, suggestions):
        for item, file, (category, stem) in zip(self.items, files, suggestions):
            item["destination"] = str(Path(category) / f"{stem}{file.suffix}")
        self.busy = False
        self.scan_button.configure(state="normal")
        self.apply_button.configure(state="normal")
        self.status_var.set(f"Review the suggestions. Double-click a row to include or skip it. No files have moved.")
        self.populate()

    def scan_failed(self, error):
        self.busy = False
        self.scan_button.configure(state="normal")
        self.apply_button.configure(state="disabled")
        self.status_var.set("Suggestions failed; no files were changed.")
        messagebox.showerror("Could not generate suggestions", str(error))

    def populate(self):
        self.tree.delete(*self.tree.get_children())
        for index, item in enumerate(self.items):
            self.tree.insert(
                "", "end", iid=str(index),
                values=("Yes" if item["include"] else "No", item["source"], item["destination"]),
            )

    def toggle_item(self, event):
        row = self.tree.identify_row(event.y)
        if not row:
            return
        item = self.items[int(row)]
        item["include"] = not item["include"]
        self.populate()

    def edit_suggestion(self, event):
        row = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        if not row or self.busy:
            return
        item = self.items[int(row)]
        if column == "#1":
            self.toggle_item(event)
            return
        if column != "#3" or not item["destination"]:
            return

        suggestion = simpledialog.askstring(
            "Edit suggested destination",
            "Change the category or filename; keep the original extension:",
            initialvalue=item["destination"],
            parent=self.root,
        )
        if suggestion is None:
            return
        try:
            item["destination"] = validate_destination(suggestion.strip(), item["source"])
        except ValueError as error:
            messagebox.showerror("Invalid destination", str(error), parent=self.root)
            return
        self.populate()

    def apply(self):
        try:
            root = self.selected_root()
            selected = [item for item in self.items if item["include"]]
            if not selected:
                raise ValueError("Select at least one suggested move.")
            manifest_path = root / UNDO_FILE
            if manifest_path.exists() or manifest_path.is_symlink():
                raise ValueError("An undo record already exists. Undo the previous tidy-up before applying another.")
            moves = []
            planned = set()
            for item in selected:
                source = root / item["source"]
                if not source.is_file() or source.is_symlink() or source.resolve().parent != root:
                    raise ValueError(f"Source file is no longer available: {item['source']}")
                destination = resolved_child(root, item["destination"])
                if destination in planned:
                    raise ValueError(f"Two files have the same destination: {item['destination']}")
                if destination.exists() or destination.is_symlink():
                    raise FileExistsError(f"Destination already exists: {item['destination']}")
                planned.add(destination)
                moves.append((source, destination))
            if not messagebox.askyesno(
                "Confirm tidy-up",
                f"Move {len(moves)} selected file(s) into suggested folders? "
                "No files will be deleted. You can undo this operation.",
            ):
                return
            move_with_rollback(root, moves)
            manifest = {
                "moves": [
                    {"source": source.relative_to(root).as_posix(), "destination": destination.relative_to(root).as_posix()}
                    for source, destination in moves
                ],
            }
            try:
                with manifest_path.open("x", encoding="utf-8") as handle:
                    json.dump(manifest, handle, indent=2)
            except Exception:
                move_with_rollback(root, [(destination, source) for source, destination in reversed(moves)])
                raise
            self.status_var.set(f"Moved {len(moves)} file(s). Use Undo last tidy-up to reverse the operation.")
            self.apply_button.configure(state="disabled")
            self.refresh_undo_state()
        except Exception as error:
            messagebox.showerror("Could not apply tidy-up", str(error))

    def undo(self):
        try:
            root = self.selected_root()
            manifest_path = root / UNDO_FILE
            if manifest_path.is_symlink() or not manifest_path.is_file():
                raise FileNotFoundError("No valid undo record was found in this folder.")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            entries = manifest.get("moves")
            if not isinstance(entries, list) or not entries:
                raise ValueError("The undo record is empty or invalid.")
            moves = []
            for entry in entries:
                source = resolved_child(root, entry["source"])
                destination = resolved_child(root, entry["destination"])
                if not destination.is_file() or destination.is_symlink():
                    raise FileNotFoundError(f"Moved file is missing: {entry['destination']}")
                if source.exists() or source.is_symlink():
                    raise FileExistsError(f"Cannot restore because the original path is occupied: {entry['source']}")
                moves.append((destination, source))
            if not messagebox.askyesno("Undo tidy-up", f"Restore {len(moves)} file(s) to their original locations?"):
                return
            move_with_rollback(root, moves)
            manifest_path.unlink()
            self.status_var.set(f"Restored {len(moves)} file(s) to their original locations.")
            self.refresh_undo_state()
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, RuntimeError) as error:
            messagebox.showerror("Could not undo tidy-up", str(error))


def main():
    root = tk.Tk()
    DreadDrawer(root)
    root.mainloop()


if __name__ == "__main__":
    main()
