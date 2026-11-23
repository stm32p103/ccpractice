"""パスの検査と作業フォルダ(T014。US2-3、SC-004)。文字列の網羅と Hypothesis。"""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from job_runner_agent.guard.workpath import PathRejected, WorkFolder, WorkPath, check_relative


@pytest.fixture
def folder(tmp_path: Path) -> WorkFolder:
    return WorkFolder.create(tmp_path / "work-root", "job-1")


@pytest.mark.parametrize(
    ("value", "kind"),
    [
        ("..\\x", "parent"),
        ("a\\..\\b", "parent"),
        ("../x", "parent"),
        ("C:\\Windows", "drive"),
        ("c:foo", "drive"),
        ("\\\\server\\share\\f", "unc"),
        ("//server/share/f", "unc"),
        ("\\\\?\\C:\\x", "device"),
        ("\\\\.\\PhysicalDrive0", "device"),
        ("\\rooted", "absolute"),
        ("file.txt:stream", "stream"),
        ("a\\b:c", "stream"),
        ("CON", "reserved"),
        ("nul.txt", "reserved"),
        ("a\\COM1", "reserved"),
        ("trailing.", "trailing"),
        ("trailing ", "trailing"),
        ("a<b", "invalid_char"),
        ("a|b", "invalid_char"),
        ("a*b", "invalid_char"),
        ("a\x00b", "invalid_char"),
        ("", "empty"),
        ("   ", "empty"),
        (".", "empty"),
    ],
)
def test_string_rejections(value: str, kind: str) -> None:
    with pytest.raises(PathRejected) as info:
        check_relative(value)
    assert info.value.kind == kind
    assert str(info.value) == kind  # メッセージに入力値を含めない


@pytest.mark.parametrize("value", ["a", "a\\b.txt", "a/b/c", ".\\a", "work\\out\\r.json", "ａ\\日本語.txt"])
def test_accepts_plain_relative_paths(value: str, folder: WorkFolder) -> None:
    resolved = folder.resolve(value)
    assert resolved.path.is_relative_to(folder.root)


def test_workpath_cannot_be_forged(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        WorkPath(tmp_path, "x", object())


def test_create_makes_fresh_subfolders_and_refuses_existing(tmp_path: Path) -> None:
    a = WorkFolder.create(tmp_path, "job-1")
    b = WorkFolder.create(tmp_path, "job-1")
    assert a.root != b.root
    assert {p.name for p in a.root.iterdir()} == {"work", "src", "tmp", "signal"}


def test_job_id_cannot_escape_base(tmp_path: Path) -> None:
    folder = WorkFolder.create(tmp_path / "base", "..\\..\\evil")
    assert folder.root.resolve().is_relative_to((tmp_path / "base").resolve())


def test_delete_removes_everything(folder: WorkFolder) -> None:
    (folder.root / "work" / "f.txt").write_text("x")
    (folder.root / "work" / "ro.txt").write_text("x")
    (folder.root / "work" / "ro.txt").chmod(0o444)
    assert folder.delete()
    assert not folder.root.exists()
    assert folder.delete()  # 冪等


@pytest.mark.windows
def test_symlink_and_junction_are_rejected_and_not_followed(folder: WorkFolder, tmp_path: Path) -> None:
    import os
    import subprocess

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("SECRET")
    link = folder.root / "work" / "link"
    junction = folder.root / "work" / "junc"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(outside)], check=True, capture_output=True)
    names = ["junc"]
    try:
        os.symlink(outside, link, target_is_directory=True)
        names.append("link")
    except OSError:
        pass  # シンボリックリンクを作る権限がない環境では、ジャンクションだけを検査する
    for name in names:
        with pytest.raises(PathRejected) as info:
            folder.resolve(f"work\\{name}\\secret.txt")
        assert info.value.kind == "reparse_point"
        assert not folder.verify_existing(folder.root / "work" / name / "secret.txt")
    assert folder.delete()  # リンク先を辿らず削除する
    assert (outside / "secret.txt").read_text() == "SECRET"


@given(st.text(max_size=40))
def test_accepted_paths_never_escape(value: str) -> None:
    try:
        parts = check_relative(value)
    except PathRejected:
        return
    assert ".." not in parts
    assert all(":" not in p and "\\" not in p and "/" not in p for p in parts)
    joined = Path("C:\\root").joinpath(*parts)
    assert joined.resolve().is_relative_to(Path("C:\\root").resolve())
