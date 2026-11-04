"""Loop types: todo-list, csv, glob, json/jsonl, and checkpoint management.

The agent is always mocked: ``executor.execute_single_task`` is patched where
``src/loops.py`` imports it (inside each ``execute``), so these tests assert loop
plumbing — parsing, variables, retries, checkpoints — and never spawn a process.

Parallel execution lives in ``test_loops_parallel.py``.
"""

import json
from unittest.mock import Mock, patch

import pytest

from src.executor import ExecutionError
from src.loops import (
    CheckpointManager,
    CheckpointValidationError,
    CSVLoop,
    FileItem,
    GlobLoop,
    JsonLoop,
    TodoListLoop,
)


@pytest.fixture
def run_task():
    """Patch execute_single_task; one recorded call per agent run."""
    with patch("src.executor.execute_single_task") as mock:
        mock.return_value = {"status": "success", "exit_code": 0}
        yield mock


@pytest.fixture
def adapter():
    return Mock()


def _todo(tmp_path, text, name="todos.md"):
    path = tmp_path / name
    path.write_text(text)
    return path


def _csv(tmp_path, text, name="data.csv"):
    path = tmp_path / name
    path.write_text(text)
    return path


def _json(tmp_path, data, name="items.json"):
    path = tmp_path / name
    path.write_text(json.dumps(data) if not isinstance(data, str) else data)
    return path


def _iteration_vars(call):
    """Iteration variables passed to execute_single_task in a recorded call."""
    return call.args[2]


# --------------------------------------------------------------------------- todo


@pytest.mark.parametrize(
    "content, expected",
    [
        pytest.param("", [], id="empty-file"),
        pytest.param("# Title\n\nno checkboxes here\n", [], id="no-checkboxes"),
        pytest.param("- [ ] one\n", [("one", 1, 1)], id="single-pending"),
        pytest.param("- [x] done\n- [ ] todo\n", [("todo", 2, 2)], id="skips-completed"),
        pytest.param("- [-] working\n- [ ] todo\n", [("todo", 2, 2)], id="skips-in-progress"),
        pytest.param("  - [ ] nested\n", [("nested", 1, 1)], id="indented"),
        pytest.param("- [ ] padded text   \n", [("padded text", 1, 1)], id="strips-text"),
        pytest.param("* [ ] star\n", [], id="star-bullets-ignored"),
    ],
)
def test_parse_todo_file(tmp_path, content, expected):
    todos = TodoListLoop({}, {})._parse_todo_file(str(_todo(tmp_path, content)))
    assert [(t["text"], t["number"], t["line"]) for t in todos] == expected


def test_parse_todo_file_numbers_all_items_and_keeps_line_numbers(fixtures_dir):
    todos = TodoListLoop({}, {})._parse_todo_file(str(fixtures_dir / "todos.md"))

    assert [t["text"] for t in todos] == [
        "First pending task",
        "Second pending task",
        "Third pending task",
        "Fourth pending task",
        "Fifth pending task",
        "Sixth pending task with special chars: $VAR and {{template}}",
        "Seventh pending task",
    ]
    # Numbers count every checkbox; lines count every file line.
    assert [t["number"] for t in todos] == [1, 2, 4, 6, 8, 9, 10]
    assert [t["line"] for t in todos] == [5, 6, 8, 10, 12, 16, 17]
    assert all(t["status"] == " " for t in todos)


def test_parse_todo_file_all_complete_and_empty(fixtures_dir):
    loop = TodoListLoop({}, {})
    assert loop._parse_todo_file(str(fixtures_dir / "todos-all-complete.md")) == []
    assert loop._parse_todo_file(str(fixtures_dir / "todos-empty.md")) == []


@pytest.mark.parametrize("new_status, expected", [("[-]", "- [-] Task one"), ("[x]", "- [x] Task one")])
def test_update_checkbox_status_rewrites_only_that_line(tmp_path, new_status, expected):
    path = _todo(tmp_path, "# T\n\n- [ ] Task one\n- [ ] Task two\n")
    TodoListLoop({}, {})._update_checkbox_status(str(path), 3, new_status)

    lines = path.read_text().splitlines()
    assert lines[1] == ""
    assert lines[2] == expected
    assert lines[3] == "- [ ] Task two"
    # Atomic write leaves no temp files behind.
    assert [p.name for p in tmp_path.iterdir()] == ["todos.md"]


def test_todo_execute_runs_only_pending_items(tmp_path, run_task, adapter):
    path = _todo(tmp_path, "# T\n\n- [ ] one\n- [x] done\n- [ ] two\n")

    result = TodoListLoop({}, {}).execute(
        {"prompt": "do {{loop.item.text}}"},
        {"source": str(path)},
        {},
        adapter,
        {"on-error": "fail"},
    )

    assert result == {"status": "success", "iterations": 2, "completed": ["one", "two"], "failed": []}
    assert run_task.call_count == 2
    texts = [_iteration_vars(c)["loop"]["item"]["text"] for c in run_task.call_args_list]
    assert texts == ["one", "two"]
    assert _iteration_vars(run_task.call_args_list[1])["loop"]["index"] == 1
    assert _iteration_vars(run_task.call_args_list[1])["loop"]["total"] == 2


def test_todo_execute_marks_progress_and_completion(tmp_path, run_task, adapter):
    path = _todo(tmp_path, "- [ ] one\n- [ ] two\n")

    result = TodoListLoop({}, {}).execute(
        {"prompt": "x"},
        {"source": str(path), "mark-in-progress": True, "mark-complete": True},
        {},
        adapter,
        {"on-error": "fail"},
    )

    assert result["status"] == "success"
    assert path.read_text() == "- [x] one\n- [x] two\n"


def test_todo_execute_empty_list_returns_success_without_running(tmp_path, run_task, adapter):
    result = TodoListLoop({}, {}).execute(
        {"prompt": "x"},
        {"source": str(_todo(tmp_path, "- [x] done\n"))},
        {},
        adapter,
        {"on-error": "fail"},
    )
    assert result == {"status": "success", "iterations": 0, "completed": [], "failed": []}
    run_task.assert_not_called()


def test_todo_execute_missing_source_raises(adapter):
    with pytest.raises(ExecutionError, match="TodoListLoop requires 'source'"):
        TodoListLoop({}, {}).execute({"prompt": "x"}, {}, {}, adapter, {})


def test_todo_execute_missing_file_raises(tmp_path, adapter):
    with pytest.raises(ExecutionError, match="Todo list file not found"):
        TodoListLoop({}, {}).execute(
            {"prompt": "x"}, {"source": str(tmp_path / "nope.md")}, {}, adapter, {}
        )


def test_todo_execute_interpolates_source(tmp_path, run_task, adapter):
    _todo(tmp_path, "- [ ] one\n")

    result = TodoListLoop({}, {}).execute(
        {"prompt": "x"},
        {"source": "{{dir}}/todos.md"},
        {"dir": str(tmp_path)},
        adapter,
        {"on-error": "fail"},
    )

    assert result["iterations"] == 1


def test_todo_execute_dry_run_reports_without_running(tmp_path, run_task, adapter):
    path = _todo(tmp_path, "- [ ] one\n- [ ] two\n")

    result = TodoListLoop({}, {}).execute(
        {"prompt": "x"}, {"source": str(path)}, {}, adapter, {}, dry_run=True
    )

    assert result == {"status": "success", "iterations": 2, "completed": [], "failed": []}
    run_task.assert_not_called()


def test_todo_execute_retries_until_success(tmp_path, adapter):
    path = _todo(tmp_path, "- [ ] one\n")
    with patch("src.executor.execute_single_task") as mock:
        mock.side_effect = [
            ExecutionError("first"),
            ExecutionError("second"),
            {"status": "success", "exit_code": 0},
        ]

        result = TodoListLoop({}, {}).execute(
            {"prompt": "x"},
            {"source": str(path), "retry": {"max-attempts": 3, "on-failure": "retry"}},
            {},
            adapter,
            {"on-error": "fail"},
        )

    assert result["status"] == "success"
    assert mock.call_count == 3


def test_todo_execute_abort_raises_after_attempts(tmp_path, adapter):
    path = _todo(tmp_path, "- [ ] one\n")
    with patch("src.executor.execute_single_task") as mock:
        mock.side_effect = ExecutionError("boom")

        with pytest.raises(ExecutionError, match="boom"):
            TodoListLoop({}, {}).execute(
                {"prompt": "x"},
                {"source": str(path), "retry": {"max-attempts": 2, "on-failure": "abort"}},
                {},
                adapter,
                {"on-error": "fail"},
            )

    assert mock.call_count == 2


def test_todo_execute_skip_records_failure_and_continues(tmp_path, adapter):
    path = _todo(tmp_path, "- [ ] one\n- [ ] two\n")
    with patch("src.executor.execute_single_task") as mock:
        mock.side_effect = [ExecutionError("boom"), {"status": "success", "exit_code": 0}]

        result = TodoListLoop({}, {}).execute(
            {"prompt": "x"},
            {"source": str(path), "retry": {"max-attempts": 3, "on-failure": "skip"}},
            {},
            adapter,
            {"on-error": "fail"},
        )

    assert result["status"] == "partial"
    assert result["completed"] == ["two"]
    assert result["failed"] == ["one"]
    assert mock.call_count == 2  # skip never retries


@pytest.mark.parametrize(
    "retry, message",
    [
        pytest.param({"max-attempts": 0}, "retry.max-attempts must be >= 1", id="attempts"),
        pytest.param({"on-failure": "bogus"}, "retry.on-failure must be", id="on-failure"),
    ],
)
def test_todo_execute_rejects_invalid_retry_config(tmp_path, adapter, retry, message):
    path = _todo(tmp_path, "- [ ] one\n")
    with pytest.raises(ExecutionError, match=message):
        TodoListLoop({}, {}).execute(
            {"prompt": "x"}, {"source": str(path), "retry": retry}, {}, adapter, {}
        )


# ------------------------------------------------------------------- checkpoints


def test_checkpoint_roundtrip(tmp_path):
    manager = CheckpointManager()
    path = tmp_path / "ckpt.json"
    data = {"type": "csv", "current_index": 2, "completed_items": ["row-1"], "failed_items": []}

    manager.save_checkpoint(str(path), data)

    assert json.loads(path.read_text()) == data
    assert manager.load_checkpoint(str(path)) == data


def test_checkpoint_missing_file_returns_none(tmp_path):
    assert CheckpointManager().load_checkpoint(str(tmp_path / "nope.json")) is None


def test_checkpoint_creates_parent_directories(tmp_path):
    path = tmp_path / "a" / "b" / "ckpt.json"
    CheckpointManager().save_checkpoint(
        str(path), {"type": "csv", "current_index": 1, "completed_items": [], "failed_items": []}
    )
    assert path.exists()


def test_checkpoint_save_is_atomic_and_leaves_no_temp_files(tmp_path):
    manager = CheckpointManager()
    manager.save_checkpoint(
        str(tmp_path / "ckpt.json"),
        {"type": "csv", "current_index": 1, "completed_items": [], "failed_items": []},
    )
    assert [p.name for p in tmp_path.iterdir()] == ["ckpt.json"]


@pytest.mark.parametrize(
    "payload, message",
    [
        pytest.param("{not json", "invalid JSON", id="bad-json"),
        pytest.param([], "must be a JSON object", id="array"),
        pytest.param('"text"', "must be a JSON object", id="string"),
        pytest.param({"type": "csv"}, "missing required fields", id="missing-fields"),
        pytest.param(
            {"type": "bogus", "current_index": 0, "completed_items": [], "failed_items": []},
            "Invalid checkpoint type",
            id="bad-type",
        ),
        pytest.param(
            {"type": "csv", "current_index": "1", "completed_items": [], "failed_items": []},
            "current_index' must be an integer",
            id="bad-index",
        ),
        pytest.param(
            {"type": "csv", "current_index": 0, "completed_items": "x", "failed_items": []},
            "completed_items' must be a list",
            id="bad-completed",
        ),
        pytest.param(
            {"type": "csv", "current_index": 0, "completed_items": [], "failed_items": {}},
            "failed_items' must be a list",
            id="bad-failed",
        ),
    ],
)
def test_checkpoint_validation_errors(tmp_path, payload, message):
    path = tmp_path / "ckpt.json"
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload))

    with pytest.raises(CheckpointValidationError, match=message):
        CheckpointManager().load_checkpoint(str(path))


# ------------------------------------------------------------------------- csv


@pytest.mark.parametrize(
    "content, loop_config, expected",
    [
        pytest.param(
            "name,status\nalpha,active\nbeta,inactive\n",
            {},
            [("alpha", "active", 1), ("beta", "inactive", 2)],
            id="header-as-fieldnames",
        ),
        # Documented quirk: skip-header without columns makes the first data row the fieldnames.
        pytest.param(
            "name,status\nalpha,active\nbeta,inactive\n",
            {"skip-header": True},
            [(None, None, 2)],
            id="skip-header-without-columns-eats-first-data-row",
        ),
        # The documented combination: header skipped, explicit names, every data row kept.
        pytest.param(
            "name,status\nalpha,active\nbeta,inactive\n",
            {"skip-header": True, "columns": ["name", "status"]},
            [("alpha", "active", 2), ("beta", "inactive", 3)],
            id="skip-header-with-columns",
        ),
        # Documented quirk: columns alone keeps the header line as a data row.
        pytest.param(
            "name,status\nalpha,active\n",
            {"columns": ["name", "status"]},
            [("name", "status", 1), ("alpha", "active", 2)],
            id="columns-without-skip-header-keeps-header-as-data",
        ),
        pytest.param(
            "name,status\nalpha,active\nbeta,inactive\ngamma,active\n",
            {"filter": {"column": "status", "value": "active"}},
            [("alpha", "active", 1), ("gamma", "active", 3)],
            id="filter-keeps-data-row-numbers",
        ),
        pytest.param("", {}, [], id="empty-file"),
        pytest.param("name\n\nvalue\n", {}, [("value", None, 1)], id="blank-line-skipped"),
    ],
)
def test_parse_csv(tmp_path, content, loop_config, expected):
    rows = CSVLoop({}, {})._parse_csv_file(str(_csv(tmp_path, content)), loop_config)

    assert [(r.get("name"), r.get("status"), r["_row_number"]) for r in rows] == expected


@pytest.mark.parametrize(
    "filter_config, message",
    [
        pytest.param({"value": "x"}, "filter.column is required", id="no-column"),
        pytest.param({"column": "status"}, "filter.value is required", id="no-value"),
        pytest.param({"column": "nope", "value": "x"}, "not found in CSV", id="unknown-column"),
    ],
)
def test_parse_csv_rejects_bad_filter(tmp_path, filter_config, message):
    path = _csv(tmp_path, "name,status\nalpha,active\n")
    with pytest.raises(ExecutionError, match=message):
        CSVLoop({}, {})._parse_csv_file(str(path), {"filter": filter_config})


def test_parse_csv_rejects_non_utf8(tmp_path):
    path = tmp_path / "latin1.csv"
    path.write_bytes("name\ncaf\xe9\n".encode("latin-1"))
    with pytest.raises(ExecutionError, match="encoding error"):
        CSVLoop({}, {})._parse_csv_file(str(path), {})


def test_csv_execute_uses_named_columns_and_row_variables(tmp_path, run_task, adapter):
    path = _csv(tmp_path, "name,role\nAlice,Engineer\nBob,Designer\n")

    result = CSVLoop({}, {}).execute(
        {"prompt": "{{loop.item.name}}"}, {"source": str(path)}, {}, adapter, {"on-error": "fail"}
    )

    assert result == {
        "status": "success",
        "iterations": 2,
        "completed": ["row-1", "row-2"],
        "failed": [],
    }
    first = _iteration_vars(run_task.call_args_list[0])
    assert first["loop"]["item"] == {"name": "Alice", "role": "Engineer", "row": 1}
    assert first["loop"]["remaining"] == 2


def test_csv_execute_empty_and_missing_source(tmp_path, run_task, adapter):
    empty = _csv(tmp_path, "name\n", "empty.csv")
    result = CSVLoop({}, {}).execute(
        {"prompt": "x"}, {"source": str(empty)}, {}, adapter, {"on-error": "fail"}
    )
    assert result["iterations"] == 0
    run_task.assert_not_called()

    with pytest.raises(ExecutionError, match="CSV file not found"):
        CSVLoop({}, {}).execute(
            {"prompt": "x"}, {"source": str(tmp_path / "nope.csv")}, {}, adapter, {}
        )
    with pytest.raises(ExecutionError, match="CSVLoop requires 'source'"):
        CSVLoop({}, {}).execute({"prompt": "x"}, {}, {}, adapter, {})


def test_csv_execute_dry_run(tmp_path, run_task, adapter, capsys):
    path = _csv(tmp_path, "name\na\nb\n")

    result = CSVLoop({}, {}).execute(
        {"prompt": "x"}, {"source": str(path)}, {}, adapter, {}, dry_run=True
    )

    assert result["iterations"] == 2
    assert "Rows to process: 2" in capsys.readouterr().err
    run_task.assert_not_called()


def test_csv_execute_resumes_from_expanded_checkpoint(tmp_path, run_task, adapter):
    path = _csv(tmp_path, "name\nfirst\nsecond\nthird\n")
    manager = CheckpointManager()
    ckpt = tmp_path / "state" / "ckpt.json"
    manager.save_checkpoint(
        str(ckpt),
        {"type": "csv", "current_index": 1, "completed_items": ["row-1"], "failed_items": []},
    )

    result = CSVLoop({}, {}).execute(
        {"prompt": "x"},
        {"source": str(path), "resume": True, "checkpoint-file": "{{out}}/state/ckpt.json"},
        {"out": str(tmp_path)},
        adapter,
        {"on-error": "fail"},
    )

    assert result["completed"] == ["row-1", "row-2", "row-3"]
    assert run_task.call_count == 2
    saved = manager.load_checkpoint(str(ckpt))
    assert saved["current_index"] == 3
    # The raw template path was never used.
    assert not (tmp_path / "{{out}}").exists()


def test_csv_execute_checkpoint_written_after_each_row(tmp_path, run_task, adapter):
    path = _csv(tmp_path, "name\na\nb\n")
    ckpt = tmp_path / "deep" / "nested" / "ckpt.json"

    CSVLoop({}, {}).execute(
        {"prompt": "x"},
        {"source": str(path), "checkpoint-file": str(ckpt)},
        {},
        adapter,
        {"on-error": "fail"},
    )

    saved = CheckpointManager().load_checkpoint(str(ckpt))
    assert saved == {
        "type": "csv",
        "current_index": 2,
        "completed_items": ["row-1", "row-2"],
        "failed_items": [],
    }


def test_csv_execute_retry_then_partial(tmp_path, adapter):
    path = _csv(tmp_path, "name\na\nb\n")
    with patch("src.executor.execute_single_task") as mock:
        mock.side_effect = [
            ExecutionError("boom"),
            ExecutionError("boom"),
            {"status": "success", "exit_code": 0},
        ]

        result = CSVLoop({}, {}).execute(
            {"prompt": "x"},
            {"source": str(path), "retry": {"max-attempts": 2, "on-failure": "retry"}},
            {},
            adapter,
            {"on-error": "fail"},
        )

    # Row 1 fails twice (retry exhausted) and row 2 succeeds.
    assert mock.call_count == 3
    assert result["completed"] == ["row-2"]
    assert result["failed"] == ["row-1"]
    assert result["status"] == "partial"


# ------------------------------------------------------------------------ glob


def test_glob_execute_builds_file_items(tmp_path, run_task, adapter):
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.py").write_text("b")

    result = GlobLoop({}, {}).execute(
        {"prompt": "x"},
        {"pattern": str(tmp_path / "*.txt")},
        {},
        adapter,
        {"on-error": "fail"},
    )

    assert result["completed"] == [str(tmp_path / "a.txt")]
    item = _iteration_vars(run_task.call_args_list[0])["loop"]["item"]
    assert item == {"path": str(tmp_path / "a.txt"), "filename": "a.txt", "extension": ".txt"}
    assert str(item) == str(tmp_path / "a.txt")


def test_glob_no_matches_is_success(tmp_path, run_task, adapter):
    result = GlobLoop({}, {}).execute(
        {"prompt": "x"}, {"pattern": str(tmp_path / "*.nope")}, {}, adapter, {"on-error": "fail"}
    )
    assert result == {"status": "success", "iterations": 0, "completed": [], "failed": []}
    run_task.assert_not_called()


def test_glob_requires_pattern(adapter):
    with pytest.raises(ExecutionError, match="GlobLoop requires 'pattern'"):
        GlobLoop({}, {}).execute({"prompt": "x"}, {}, {}, adapter, {})


def test_glob_interpolates_pattern_and_excludes(tmp_path, run_task, adapter):
    for name in ("keep.log", "skip.log", "other.txt"):
        (tmp_path / name).write_text(name)

    result = GlobLoop({}, {}).execute(
        {"prompt": "x"},
        {"pattern": "{{dir}}/*.log", "exclude": ["*skip*"]},
        {"dir": str(tmp_path)},
        adapter,
        {"on-error": "fail"},
    )

    assert result["completed"] == [str(tmp_path / "keep.log")]


@pytest.mark.parametrize("sort_by", ["name", "modified", "size", "created"])
def test_glob_sort_returns_all_files(tmp_path, adapter, sort_by):
    for name in ("b.txt", "a.txt"):
        (tmp_path / name).write_text(name)

    files = GlobLoop({}, {})._get_matching_files(str(tmp_path / "*.txt"))
    ordered = GlobLoop({}, {})._sort_files(files, sort_by)

    assert sorted(ordered) == sorted(files)


def test_glob_sort_by_name_ascending_and_size_descending(tmp_path):
    (tmp_path / "b.txt").write_text("bb")
    (tmp_path / "a.txt").write_text("aaaa")
    files = GlobLoop({}, {})._get_matching_files(str(tmp_path / "*.txt"))

    assert GlobLoop({}, {})._sort_files(files, "name") == sorted(files)
    assert GlobLoop({}, {})._sort_files(files, "size")[0] == str(tmp_path / "a.txt")


def test_glob_invalid_sort_raises(tmp_path):
    files = GlobLoop({}, {})._get_matching_files(str(tmp_path / "*.txt"))
    with pytest.raises(ExecutionError, match="Invalid sort value"):
        GlobLoop({}, {})._sort_files(files, "bogus")


def test_glob_dry_run(tmp_path, run_task, adapter, capsys):
    (tmp_path / "a.txt").write_text("a")

    result = GlobLoop({}, {}).execute(
        {"prompt": "x"}, {"pattern": str(tmp_path / "*.txt")}, {}, adapter, {}, dry_run=True
    )

    assert result["iterations"] == 1
    assert "Matching files: 1" in capsys.readouterr().err
    run_task.assert_not_called()


def test_glob_checkpoint_expansion(tmp_path, run_task, adapter):
    (tmp_path / "a.txt").write_text("a")

    GlobLoop({}, {}).execute(
        {"prompt": "x"},
        {"pattern": str(tmp_path / "*.txt"), "checkpoint-file": "{{out}}/ckpt.json"},
        {"out": str(tmp_path)},
        adapter,
        {"on-error": "fail"},
    )

    saved = CheckpointManager().load_checkpoint(str(tmp_path / "ckpt.json"))
    assert saved["type"] == "glob"
    assert saved["current_index"] == 1


# ------------------------------------------------------------------------ json


def test_parse_json_array_adds_indexes(tmp_path):
    path = _json(tmp_path, [{"id": 1}, {"id": 2}])
    items = JsonLoop({}, {})._parse_json_file(str(path), {})
    assert items == [{"id": 1, "_index": 0}, {"id": 2, "_index": 1}]


def test_parse_json_nested_path(tmp_path):
    path = _json(tmp_path, {"users": {"active": [{"id": 1}]}})
    items = JsonLoop({}, {})._parse_json_file(str(path), {"path": "users.active"})
    assert items == [{"id": 1, "_index": 0}]


def test_parse_json_primitives_kept_raw_until_execute(tmp_path):
    path = _json(tmp_path, ["a", 1, True, None])
    assert JsonLoop({}, {})._parse_json_file(str(path), {}) == ["a", 1, True, None]


def test_parse_jsonl(tmp_path):
    path = _json(tmp_path, '{"id": 1}\n{"id": 2}\n', "data.jsonl")
    assert JsonLoop({}, {})._parse_jsonl_file(str(path)) == [
        {"id": 1, "_index": 0},
        {"id": 2, "_index": 1},
    ]


@pytest.mark.parametrize(
    "content, loop_config, message",
    [
        pytest.param("{bad", {}, "Invalid JSON", id="bad-json"),
        pytest.param('{"a": 1}', {}, "must contain an array at root", id="root-not-array"),
        pytest.param('{"a": {"b": 1}}', {"path": "a.b"}, "does not point to an array", id="path-not-array"),
        pytest.param('{"a": 1}', {"path": "missing"}, "not found", id="path-missing"),
        pytest.param('[1]', {"path": "a.b"}, "invalid", id="path-through-primitive"),
    ],
)
def test_parse_json_errors(tmp_path, content, loop_config, message):
    path = _json(tmp_path, content)
    with pytest.raises(ExecutionError, match=message):
        JsonLoop({}, {})._parse_json_file(str(path), loop_config)


def test_parse_jsonl_invalid_line_raises(tmp_path):
    path = _json(tmp_path, '{"id": 1}\nnot json\n', "data.jsonl")
    with pytest.raises(ExecutionError, match="Invalid JSON on line 2"):
        JsonLoop({}, {})._parse_jsonl_file(str(path))


@pytest.mark.parametrize(
    "items, filter_config, expected_ids",
    [
        pytest.param(
            [{"id": 1, "s": "a"}, {"id": 2, "s": "b"}],
            {"key": "s", "value": "a"},
            [1],
            id="simple",
        ),
        pytest.param(
            [{"id": 1, "s": "a", "n": 1}, {"id": 2, "s": "b", "n": 1}, {"id": 3, "s": "a", "n": 2}],
            {"conditions": [{"key": "s", "value": "a"}, {"key": "n", "value": 1}], "operator": "AND"},
            [1],
            id="and",
        ),
        pytest.param(
            [{"id": 1, "s": "a"}, {"id": 2, "s": "b"}],
            {"conditions": [{"key": "s", "value": "a"}, {"key": "s", "value": "b"}], "operator": "OR"},
            [1, 2],
            id="or",
        ),
        pytest.param(
            [{"id": 1, "address": {"city": "NY"}}, {"id": 2, "address": {"city": "LA"}}],
            {"key": "address.city", "value": "LA"},
            [2],
            id="nested-key",
        ),
        pytest.param(
            [{"id": 1}, {"id": 2}],
            {"key": "missing", "value": "x"},
            [],
            id="missing-key-matches-nothing",
        ),
    ],
)
def test_json_filters(items, filter_config, expected_ids):
    filtered = JsonLoop({}, {})._apply_filter(items, filter_config)
    assert [item["id"] for item in filtered] == expected_ids


@pytest.mark.parametrize(
    "filter_config, message",
    [
        pytest.param({"conditions": []}, "cannot be empty", id="empty-conditions"),
        pytest.param(
            {"conditions": [{"key": "a", "value": 1}], "operator": "XOR"},
            "must be 'AND' or 'OR'",
            id="bad-operator",
        ),
    ],
)
def test_json_filter_errors(filter_config, message):
    with pytest.raises(ExecutionError, match=message):
        JsonLoop({}, {})._apply_filter([], filter_config)


def test_json_execute_wraps_primitives_and_filters(tmp_path, run_task, adapter):
    path = _json(tmp_path, [{"id": 1, "keep": True}, {"id": 2, "keep": False}, 7])

    result = JsonLoop({}, {}).execute(
        {"prompt": "x"}, {"source": str(path)}, {}, adapter, {"on-error": "fail"}
    )

    # No filter => all items, including the primitive.
    assert result["completed"] == ["item-0", "item-1", "item-2"]
    assert _iteration_vars(run_task.call_args_list[2])["loop"]["item"] == {
        "value": 7,
        "type": "number",
        "_index": 2,
    }

    run_task.reset_mock()
    result = JsonLoop({}, {}).execute(
        {"prompt": "x"},
        {"source": str(path), "filter": {"key": "keep", "value": True}},
        {},
        adapter,
        {"on-error": "fail"},
    )
    assert result["completed"] == ["item-0"]


def test_json_execute_jsonl_and_checkpoint_expansion(tmp_path, run_task, adapter):
    path = _json(tmp_path, '{"id": 1}\n{"id": 2}\n', "data.jsonl")

    result = JsonLoop({}, {}).execute(
        {"prompt": "x"},
        {"type": "jsonl", "source": str(path), "checkpoint-file": "{{out}}/ckpt.json"},
        {"out": str(tmp_path)},
        adapter,
        {"on-error": "fail"},
    )

    assert result["completed"] == ["item-0", "item-1"]
    saved = CheckpointManager().load_checkpoint(str(tmp_path / "ckpt.json"))
    assert saved["type"] == "jsonl"
    assert saved["current_index"] == 2


def test_json_execute_requires_source_and_existing_file(tmp_path, adapter):
    with pytest.raises(ExecutionError, match="JsonLoop requires 'source'"):
        JsonLoop({}, {}).execute({"prompt": "x"}, {}, {}, adapter, {})
    with pytest.raises(ExecutionError, match="JSON file not found"):
        JsonLoop({}, {}).execute(
            {"prompt": "x"}, {"source": str(tmp_path / "nope.json")}, {}, adapter, {}
        )


def test_json_execute_dry_run(tmp_path, run_task, adapter, capsys):
    path = _json(tmp_path, [{"id": 1}, {"id": 2}])

    result = JsonLoop({}, {}).execute(
        {"prompt": "x"}, {"source": str(path)}, {}, adapter, {}, dry_run=True
    )

    assert result["iterations"] == 2
    assert "Items to process: 2" in capsys.readouterr().err
    run_task.assert_not_called()


# --------------------------------------------------------------------- FileItem


def test_file_item_renders_as_path():
    item = FileItem({"path": "/tmp/x.txt", "filename": "x.txt", "extension": ".txt"})
    assert str(item) == "/tmp/x.txt"
    assert "x.txt" in repr(item)
    assert str(FileItem({"path": ""})) == ""


# ----------------------------------------------------------------- loop callbacks


def test_csv_loop_emits_item_callbacks(tmp_path, run_task, adapter):
    path = _csv(tmp_path, "name\na\nb\n")
    events = []
    workflow_config = {
        "on-error": "fail",
        "_event_sink": events.append,
        "_current_node_id": "0.process",
    }

    CSVLoop({}, {}).execute({"prompt": "x"}, {"source": str(path)}, {}, adapter, workflow_config)

    assert [e["type"] for e in events] == [
        "loop_item_started",
        "loop_item_completed",
        "loop_item_started",
        "loop_item_completed",
    ]
    assert all(e["node_id"] == "0.process" for e in events)
    assert all(e["loop_type"] == "csv" and e["total"] == 2 for e in events)
    assert [e["item_id"] for e in events if e["type"] == "loop_item_started"] == ["row-1", "row-2"]


def test_csv_parallel_loop_emits_item_callbacks(tmp_path, run_task, adapter):
    path = _csv(tmp_path, "name\na\nb\n")
    events = []

    CSVLoop({}, {}).execute(
        {"prompt": "x"},
        {"source": str(path), "workers": 2},
        {},
        adapter,
        {"_event_sink": events.append},
    )

    started = [e for e in events if e["type"] == "loop_item_started"]
    completed = [e for e in events if e["type"] == "loop_item_completed"]
    assert sorted(e["item_id"] for e in started) == ["row-1", "row-2"]
    assert sorted(e["item_id"] for e in completed) == ["row-1", "row-2"]


def test_loop_emits_failed_callback(tmp_path, adapter):
    path = _csv(tmp_path, "name\na\n")
    events = []
    with patch("src.executor.execute_single_task") as mock:
        mock.side_effect = ExecutionError("boom")

        CSVLoop({}, {}).execute(
            {"prompt": "x"},
            {"source": str(path), "retry": {"max-attempts": 1, "on-failure": "skip"}},
            {},
            adapter,
            {"_event_sink": events.append},
        )

    assert [e["type"] for e in events] == ["loop_item_started", "loop_item_failed"]
    assert events[-1]["status"] == "failed"


def test_json_loop_emits_item_callbacks(tmp_path, run_task, adapter):
    path = _json(tmp_path, [{"id": 1}, {"id": 2}])
    events = []

    JsonLoop({}, {}).execute(
        {"prompt": "x"}, {"source": str(path)}, {}, adapter, {"_event_sink": events.append}
    )

    assert [e["item_id"] for e in events if e["type"] == "loop_item_started"] == ["item-0", "item-1"]
    assert all(e["loop_type"] == "json" for e in events)


def test_loop_callbacks_are_noop_without_sink(tmp_path, run_task, adapter):
    """The CLI path attaches no sink; loops must not fail or emit anything."""
    path = _csv(tmp_path, "name\na\n")
    result = CSVLoop({}, {}).execute({"prompt": "x"}, {"source": str(path)}, {}, adapter, {})
    assert result["status"] == "success"
