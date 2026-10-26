"""src/jsonfile.py: the add-on's JSON files, written safely."""

import json

from src import jsonfile


def test_saved_and_read_back(tmp_path):
    path = str(tmp_path / "x.json")
    assert jsonfile.save(path, {"a": 1}, "x", indent=1)
    got = {}
    assert jsonfile.load(path, "x", got.update) and got == {"a": 1}


def test_the_previous_version_is_kept_and_used_if_the_file_breaks(tmp_path):
    path = str(tmp_path / "x.json")
    jsonfile.save(path, {"v": 1}, "x")
    jsonfile.save(path, {"v": 2}, "x")
    assert json.load(open(path + ".bak")) == {"v": 1}
    open(path, "w").write("{broken")
    got = {}
    assert jsonfile.load(path, "x", got.update) and got == {"v": 1}
    # a broken file never replaces a good backup
    jsonfile.save(path, {"v": 3}, "x")
    assert json.load(open(path + ".bak")) == {"v": 1} and json.load(open(path)) == {"v": 3}


def test_contents_that_cant_be_used_fall_back_too(tmp_path):
    path = str(tmp_path / "x.json")
    jsonfile.save(path, {"n": 1}, "x")
    jsonfile.save(path, {"n": "not a number"}, "x")
    got = []
    assert jsonfile.load(path, "x", lambda d: got.append(int(d["n"]))) and got == [1]
    open(path, "w").write("[1, 2]")  # not an object
    got.clear()
    assert jsonfile.load(path, "x", lambda d: got.append(d)) and got == [{"n": 1}]


def test_missing_or_no_path(tmp_path):
    assert not jsonfile.load(str(tmp_path / "none.json"), "x", lambda d: None)
    assert not jsonfile.load(None, "x", lambda d: None)
    assert not jsonfile.save(None, {}, "x")
    assert not jsonfile.save(str(tmp_path / "no" / "dir" / "x.json"), {}, "x", quiet=True)  # logged, not raised


def test_without_a_backup(tmp_path):
    path = str(tmp_path / "x.json")
    jsonfile.save(path, {"v": 1}, "x", backup=False)
    jsonfile.save(path, {"v": 2}, "x", backup=False)
    import os
    assert not os.path.exists(path + ".bak")
