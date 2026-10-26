"""Lightweight regression tests that can run without the ESTEC Windows GUI."""
from pathlib import Path
import ast
import zipfile

from Modules.file_copy_batch import batch_copy, batch_copy_from_lists


def test_copy_directory_recursively(tmp_path):
    source = tmp_path / "source"
    (source / "nested").mkdir(parents=True)
    (source / "a.txt").write_text("alpha", encoding="utf-8")
    (source / "nested" / "b.txt").write_text("beta", encoding="utf-8")
    target = tmp_path / "target"

    results = batch_copy([(source, target)], verbose=False)

    assert len(results) == 1 and results[0].success
    assert (target / "a.txt").read_text(encoding="utf-8") == "alpha"
    assert (target / "nested" / "b.txt").read_text(encoding="utf-8") == "beta"


def test_copy_from_lists_rejects_mismatched_lengths(tmp_path):
    try:
        batch_copy_from_lists([tmp_path / "a"], [], verbose=False)
    except ValueError as exc:
        assert "数量不一致" in str(exc)
    else:
        raise AssertionError("应当拒绝长度不一致的 sources/targets")


def test_python_sources_compile():
    root = Path(__file__).resolve().parent
    source_files = list(root.glob("*.py")) + list((root / "Modules").glob("*.py"))
    assert source_files
    for source in source_files:
        ast.parse(source.read_text(encoding="utf-8-sig"), filename=str(source))


def test_ui_workflow_has_main_guard():
    root = Path(__file__).resolve().parent
    scripts = list(root.glob("ESTEC_software_workflow.py"))
    assert scripts
    tree = ast.parse(scripts[0].read_text(encoding="utf-8-sig"))
    assert any(
        isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Name)
        and node.test.left.id == "__name__"
        for node in tree.body
    ), "GUI 自动化脚本应通过 __main__ 入口运行，避免被导入时执行"
