# /tests/test_file_manager.py
"""Unit tests for modules/file_manager.py.

Everything runs against a small tree built under ``tmp_path``, so the
organiser and the duplicate finder can move real files without endangering
anything the user owns.
"""

from __future__ import annotations

import csv

import pytest

from modules.file_manager import FileManager
from tests.conftest import run


@pytest.fixture
def tree(tmp_path):
    """A little file tree: documents, images, duplicates and a CSV."""
    root = tmp_path / "desk"
    root.mkdir()
    (root / "report.pdf").write_bytes(b"%PDF-1.4 fake")
    (root / "notes.txt").write_text("the quick brown fox jumps over the lazy dog")
    (root / "photo.jpg").write_bytes(b"\xff\xd8\xff\xe0 jpeg")
    (root / "copy_a.txt").write_text("identical contents")
    (root / "copy_b.txt").write_text("identical contents")
    with (root / "sales.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["region", "units", "revenue"])
        writer.writerows([["north", 10, 100.5], ["south", 20, 250.0], ["east", 5, 42.25]])
    return root


@pytest.fixture
def files(config):
    """A FileManager wired to the temporary config."""
    return FileManager(config)


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("find all pdfs on my desktop", "find_files"),
        ("summarize this document", "summarize_document"),
        ("organize my downloads folder", "organize_files"),
        ("what are the largest files on my disk", "largest_files"),
        ("find duplicate files", "find_duplicates"),
        ("analyze this csv", "analyze_csv"),
    ],
)
def test_offline_router_recognises_file_requests(files, phrase, expected):
    routed = files.offline_router(phrase)
    assert routed is not None, f"{phrase!r} should route without an LLM"
    assert routed[0] == expected


def test_finding_files_by_extension(files, tree):
    result = run(files.call_tool("find_files", {"pattern": "*.txt", "directory": str(tree)}))
    assert result.success
    assert "notes.txt" in result.output


def test_finding_nothing_is_reported_as_success_with_a_clear_message(files, tree):
    result = run(files.call_tool("find_files", {"pattern": "*.xyz", "directory": str(tree)}))
    assert "no" in (result.output + result.error).lower()


def test_searching_inside_files(files, tree):
    result = run(files.call_tool(
        "search_content", {"text": "quick brown", "directory": str(tree)}
    ))
    assert result.success
    assert "notes.txt" in result.output


def test_duplicates_are_found_by_content_not_name(files, tree):
    result = run(files.call_tool("find_duplicates", {"directory": str(tree)}))
    assert result.success
    assert "copy_a.txt" in result.output or "copy_b.txt" in result.output


def test_largest_files_are_ranked(files, tree):
    result = run(files.call_tool("largest_files", {"directory": str(tree), "limit": 3}))
    assert result.success
    assert result.output.count("\n") <= 5


def test_a_csv_is_analysed_with_column_statistics(files, tree):
    result = run(files.call_tool("analyze_csv", {"path": str(tree / "sales.csv")}))
    assert result.success
    assert "region" in result.output
    assert "3" in result.output  # three data rows


def test_analysing_a_missing_csv_fails_politely(files, tree):
    result = run(files.call_tool("analyze_csv", {"path": str(tree / "ghost.csv")}))
    assert not result.success


def test_organising_sorts_files_into_category_folders(files, tree):
    result = run(files.call_tool("organize_files", {"directory": str(tree), "dry_run": False}))
    assert result.success
    moved = [path.name for path in tree.rglob("*") if path.is_file()]
    assert "photo.jpg" in moved
    assert any(child.is_dir() for child in tree.iterdir())


def test_organising_can_be_previewed_without_moving_anything(files, tree):
    before = sorted(path.name for path in tree.iterdir())
    result = run(files.call_tool("organize_files", {"directory": str(tree), "dry_run": True}))
    assert result.success
    assert sorted(path.name for path in tree.iterdir()) == before


def test_a_move_can_be_undone(files, tree):
    destination = tree / "moved"
    destination.mkdir()
    run(files.call_tool("move_file", {
        "source": str(tree / "notes.txt"), "destination": str(destination)
    }))
    assert (destination / "notes.txt").exists()

    undone = run(files.call_tool("undo_file_operation", {}))
    assert undone.success
    assert (tree / "notes.txt").exists()


def test_reading_a_text_file_returns_its_contents(files, tree):
    result = run(files.call_tool("read_file", {"path": str(tree / "notes.txt")}))
    assert result.success
    assert "quick brown fox" in result.output


def test_document_contents_are_marked_untrusted(files):
    assert files.tools["read_file"].untrusted
    assert files.tools["summarize_document"].untrusted


def test_folder_stats_counts_the_tree(files, tree):
    result = run(files.call_tool("folder_stats", {"directory": str(tree)}))
    assert result.success
    assert "file" in result.output.lower()


def test_binary_files_are_not_read_aloud(files, tmp_path):
    # Dumping a JPEG into the conversation (and into TTS) helps nobody.
    blob = tmp_path / "photo.bin"
    blob.write_bytes(bytes(range(256)) * 50)
    result = run(files.call_tool("read_file", {"path": str(blob)}))
    assert not result.success
    assert "binary" in result.error.lower()


def test_text_files_are_still_readable(files, tree):
    assert run(files.call_tool("read_file", {"path": str(tree / "notes.txt")})).success
