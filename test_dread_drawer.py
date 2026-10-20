import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from dread_drawer import (
    APP_DIR,
    DEFAULT_FOLDER,
    category_for,
    move_with_rollback,
    resolved_child,
    valid_stem,
    validate_destination,
)


class DreadDrawerTests(unittest.TestCase):
    def test_default_folder_is_project_downloads(self):
        self.assertEqual(DEFAULT_FOLDER, APP_DIR / "downloads")

    def test_category_uses_extension_hint(self):
        self.assertEqual(category_for("report.PDF"), "Documents")
        self.assertEqual(category_for("photo.webp"), "Images")
        self.assertEqual(category_for("unknown.xyz"), "Other")

    def test_destination_can_change_category_and_name(self):
        self.assertEqual(
            validate_destination("Images\\vacation photo.png", "capture.png"),
            str(Path("Images") / "vacation photo.png"),
        )

    def test_destination_rejects_unsafe_paths_and_extension_changes(self):
        for destination in (
            "../outside.txt",
            "Unknown/file.pdf",
            "Documents/subfolder/file.pdf",
            "Documents/CON.pdf",
            "Documents/report.txt",
        ):
            with self.subTest(destination=destination):
                with self.assertRaises(ValueError):
                    validate_destination(destination, "report.pdf")

    def test_rejects_unsafe_stems(self):
        for stem in ("", "..", "bad/name", "bad:name", "CON", "trailing."):
            with self.subTest(stem=stem):
                self.assertFalse(valid_stem(stem))
        self.assertTrue(valid_stem("meeting notes 2026"))

    def test_resolved_child_rejects_traversal(self):
        with TemporaryDirectory(dir=APP_DIR) as temp:
            root = Path(temp).resolve()
            with self.assertRaises(ValueError):
                resolved_child(root, "../outside.txt")
            self.assertEqual(resolved_child(root, "Documents/a.pdf"), root / "Documents" / "a.pdf")

    def test_move_can_be_rolled_back(self):
        with TemporaryDirectory(dir=APP_DIR) as temp:
            root = Path(temp)
            source = root / "notes.txt"
            destination = root / "Documents" / "notes.txt"
            source.write_text("contents", encoding="utf-8")
            move_with_rollback(root, [(source, destination)])
            self.assertFalse(source.exists())
            self.assertEqual(destination.read_text(encoding="utf-8"), "contents")
            move_with_rollback(root, [(destination, source)])
            self.assertTrue(source.exists())
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
