#!/usr/bin/env python3
"""Generate line-level Git attribution reports with Python symbol locations."""

from __future__ import annotations

import argparse
import ast
import functools
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: (.*))?$")


@dataclass
class LineChange:
    action: str
    old_line: int | None
    new_line: int | None
    code: str
    old_symbol: str = ""
    new_symbol: str = ""


@dataclass
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    git_context: str
    changes: list[LineChange] = field(default_factory=list)
    no_newline_markers: int = 0


@dataclass
class FileDiff:
    old_path: str
    new_path: str
    old_header_path: str = ""
    new_header_path: str = ""
    metadata: list[str] = field(default_factory=list)
    hunks: list[Hunk] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.old_header_path == "/dev/null" or any(
            item.startswith("new file mode ") for item in self.metadata
        ):
            return "added"
        if self.new_header_path == "/dev/null" or any(
            item.startswith("deleted file mode ") for item in self.metadata
        ):
            return "deleted"
        if any(item.startswith("rename from ") for item in self.metadata):
            return "renamed/modified"
        return "modified"


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, text=True, stdout=subprocess.PIPE
    ).stdout


def parse_diff(old_rev: str, new_rev: str) -> list[FileDiff]:
    raw = git(
        "diff",
        "--no-ext-diff",
        "--no-color",
        "--find-renames",
        "--unified=0",
        old_rev,
        new_rev,
        "--",
    )
    files: list[FileDiff] = []
    current_file: FileDiff | None = None
    current_hunk: Hunk | None = None
    old_line = new_line = 0

    for raw_line in raw.splitlines():
        if raw_line.startswith("diff --git "):
            match = re.match(r"^diff --git a/(.*?) b/(.*)$", raw_line)
            if not match:
                raise ValueError(f"Cannot parse diff header: {raw_line}")
            current_file = FileDiff(match.group(1), match.group(2))
            files.append(current_file)
            current_hunk = None
            continue

        if current_file is None:
            continue

        if raw_line.startswith("--- "):
            current_file.old_header_path = raw_line[4:].removeprefix("a/")
            continue
        if raw_line.startswith("+++ "):
            current_file.new_header_path = raw_line[4:].removeprefix("b/")
            continue

        hunk_match = HUNK_RE.match(raw_line)
        if hunk_match:
            old_start = int(hunk_match.group(1))
            old_count = int(hunk_match.group(2) or "1")
            new_start = int(hunk_match.group(3))
            new_count = int(hunk_match.group(4) or "1")
            current_hunk = Hunk(
                old_start,
                old_count,
                new_start,
                new_count,
                hunk_match.group(5) or "",
            )
            current_file.hunks.append(current_hunk)
            old_line = old_start
            new_line = new_start
            continue

        if current_hunk is None:
            if raw_line and not raw_line.startswith(("index ", "similarity index ")):
                current_file.metadata.append(raw_line)
            continue

        if raw_line.startswith("\\ No newline at end of file"):
            current_hunk.no_newline_markers += 1
        elif raw_line.startswith("-"):
            current_hunk.changes.append(LineChange("DEL", old_line, None, raw_line[1:]))
            old_line += 1
        elif raw_line.startswith("+"):
            current_hunk.changes.append(LineChange("ADD", None, new_line, raw_line[1:]))
            new_line += 1
        elif raw_line.startswith(" "):
            old_line += 1
            new_line += 1

    return files


@functools.lru_cache(maxsize=None)
def source_at(rev: str, path: str) -> str:
    if path == "/dev/null":
        return ""
    result = subprocess.run(
        ["git", "show", f"{rev}:{path}"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    return result.stdout if result.returncode == 0 else ""


@functools.lru_cache(maxsize=None)
def scopes_at(rev: str, path: str) -> tuple[tuple[int, int, str], ...]:
    if not path.endswith(".py"):
        return ()
    source = source_at(rev, path)
    if not source:
        return ()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ()

    scopes: list[tuple[int, int, str]] = []

    def walk(node: ast.AST, parents: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                start = min(
                    [child.lineno]
                    + [decorator.lineno for decorator in child.decorator_list]
                )
                end = child.end_lineno or child.lineno
                qualified = ".".join([*parents, child.name])
                scopes.append((start, end, f"class {qualified}"))
                walk(child, [*parents, child.name])
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                start = min(
                    [child.lineno]
                    + [decorator.lineno for decorator in child.decorator_list]
                )
                end = child.end_lineno or child.lineno
                qualified = ".".join([*parents, child.name])
                prefix = (
                    "async function"
                    if isinstance(child, ast.AsyncFunctionDef)
                    else "function"
                )
                if parents and any(
                    label.startswith("class ") and label.endswith(parents[0])
                    for _, _, label in scopes
                ):
                    prefix = "method"
                scopes.append((start, end, f"{prefix} {qualified}"))
                walk(child, [*parents, child.name])
            else:
                walk(child, parents)

    walk(tree, [])
    return tuple(scopes)


def symbol_for(rev: str, path: str, line: int | None) -> str:
    if line is None:
        return ""
    matches = [scope for scope in scopes_at(rev, path) if scope[0] <= line <= scope[1]]
    if not matches:
        return "<module/file>"
    matches.sort(key=lambda item: (item[1] - item[0], -item[0]))
    return matches[0][2]


def annotate(files: list[FileDiff], old_rev: str, new_rev: str) -> None:
    for file_diff in files:
        old_path = file_diff.old_header_path or file_diff.old_path
        new_path = file_diff.new_header_path or file_diff.new_path
        for hunk in file_diff.hunks:
            for change in hunk.changes:
                if change.action == "DEL":
                    change.old_symbol = symbol_for(old_rev, old_path, change.old_line)
                else:
                    change.new_symbol = symbol_for(new_rev, new_path, change.new_line)


def validate_line_locations(files: list[FileDiff], old_rev: str, new_rev: str) -> None:
    """Assert that every reported line number resolves to its exact source text."""
    for file_diff in files:
        old_path = file_diff.old_header_path or file_diff.old_path
        new_path = file_diff.new_header_path or file_diff.new_path
        old_lines = source_at(old_rev, old_path).splitlines()
        new_lines = source_at(new_rev, new_path).splitlines()
        for hunk in file_diff.hunks:
            for change in hunk.changes:
                if change.action == "DEL":
                    assert change.old_line is not None
                    actual = old_lines[change.old_line - 1]
                    location = f"{old_rev}:{old_path}:{change.old_line}"
                else:
                    assert change.new_line is not None
                    actual = new_lines[change.new_line - 1]
                    location = f"{new_rev}:{new_path}:{change.new_line}"
                if actual != change.code:
                    raise AssertionError(
                        f"Line verification failed at {location}: "
                        f"expected {change.code!r}, found {actual!r}"
                    )


def rev_label(rev: str) -> str:
    return git("rev-parse", "--short=12", rev).strip()


def link(repo_url: str, rev: str, path: str, line: int | None) -> str:
    if path == "/dev/null" or line is None:
        return ""
    return f"{repo_url}/blob/{rev}/{quote(path)}#L{line}"


def format_range(start: int, count: int) -> str:
    if count == 0:
        return f"{start} (zero-length insertion/deletion point)"
    if count == 1:
        return str(start)
    return f"{start}-{start + count - 1}"


def render_diff_section(
    files: list[FileDiff],
    old_rev: str,
    new_rev: str,
    old_name: str,
    new_name: str,
    repo_url: str,
) -> tuple[str, int, int]:
    output: list[str] = []
    additions = deletions = 0

    for file_number, file_diff in enumerate(files, 1):
        old_path = file_diff.old_header_path or file_diff.old_path
        new_path = file_diff.new_header_path or file_diff.new_path
        file_additions = sum(
            change.action == "ADD"
            for hunk in file_diff.hunks
            for change in hunk.changes
        )
        file_deletions = sum(
            change.action == "DEL"
            for hunk in file_diff.hunks
            for change in hunk.changes
        )
        additions += file_additions
        deletions += file_deletions

        display_path = f"{old_path} → {new_path}" if old_path != new_path else new_path
        output.extend(
            [
                f"## {file_number}. `{display_path}`",
                "",
                f"Status: **{file_diff.status}**. Exact changed lines: "
                f"**+{file_additions} / -{file_deletions}**.",
                "",
            ]
        )
        if file_diff.metadata:
            output.append("Git metadata: `" + "`; `".join(file_diff.metadata) + "`.")
            output.append("")
        if not file_diff.hunks:
            output.extend(
                [
                    "This is an empty-file or metadata-only change; "
                    "there are no code lines to list.",
                    "",
                ]
            )
            continue

        for hunk_number, hunk in enumerate(file_diff.hunks, 1):
            symbols = sorted(
                {
                    change.old_symbol or change.new_symbol
                    for change in hunk.changes
                    if change.old_symbol or change.new_symbol
                }
            )
            output.extend(
                [
                    f"### Hunk {file_number}.{hunk_number}",
                    "",
                    f"- {old_name}: `{old_path}:"
                    f"{format_range(hunk.old_start, hunk.old_count)}`",
                    f"- {new_name}: `{new_path}:"
                    f"{format_range(hunk.new_start, hunk.new_count)}`",
                    "- Enclosing symbol(s): "
                    f"{', '.join(f'`{item}`' for item in symbols)}",
                ]
            )
            if hunk.git_context:
                output.append(f"- Git function context: `{hunk.git_context}`")
            output.extend(["", "```text"])
            for change in hunk.changes:
                if change.action == "DEL":
                    path = old_path
                    line_number = change.old_line
                    symbol = change.old_symbol
                    revision_name = old_name
                else:
                    path = new_path
                    line_number = change.new_line
                    symbol = change.new_symbol
                    revision_name = new_name
                location = f"{path}:{line_number}"
                output.append(
                    f"{change.action} {revision_name} {location} "
                    f"[{symbol}] │{change.code}"
                )
            if hunk.no_newline_markers:
                output.append(
                    "META [Git] │No newline at end of file marker "
                    f"x{hunk.no_newline_markers}"
                )
            output.extend(["```", ""])

            old_first = next(
                (
                    change.old_line
                    for change in hunk.changes
                    if change.old_line is not None
                ),
                None,
            )
            new_first = next(
                (
                    change.new_line
                    for change in hunk.changes
                    if change.new_line is not None
                ),
                None,
            )
            links: list[str] = []
            if old_first is not None and old_path != "/dev/null":
                links.append(
                    f"[{old_name} source]"
                    f"({link(repo_url, old_rev, old_path, old_first)})"
                )
            if new_first is not None and new_path != "/dev/null":
                links.append(
                    f"[{new_name} source]"
                    f"({link(repo_url, new_rev, new_path, new_first)})"
                )
            if links:
                output.extend(["Source links: " + " · ".join(links), ""])

    return "\n".join(output), additions, deletions


def commit_metadata(commit: str) -> dict[str, str]:
    fields = (
        git(
            "show",
            "-s",
            "--format=%H%x00%P%x00%aI%x00%an <%ae>%x00%s",
            commit,
        )
        .rstrip("\n")
        .split("\x00")
    )
    return {
        "hash": fields[0],
        "parents": fields[1],
        "date": fields[2],
        "author": fields[3],
        "subject": fields[4],
    }


def generate_net_report(base: str, tip: str, repo_url: str) -> str:
    base_full = git("rev-parse", base).strip()
    tip_full = git("rev-parse", tip).strip()
    files = parse_diff(base_full, tip_full)
    annotate(files, base_full, tip_full)
    validate_line_locations(files, base_full, tip_full)
    body, additions, deletions = render_diff_section(
        files,
        base_full,
        tip_full,
        "v2.7.5/base",
        "baeniv/main",
        repo_url,
    )
    return "\n".join(
        [
            "# Baeniv `main`: exhaustive net line-attribution report",
            "",
            "This is the exact zero-context line diff between the branch point "
            "and the current branch tip.",
            "It contains every line present in the net Git comparison, "
            "including blank lines.",
            "",
            f"- Base: ZEN-garden v2.7.5 `{base_full}`",
            f"- Branch tip: `baeniv/main` `{tip_full}`",
            f"- Exact line totals: **{additions} added, {deletions} removed**",
            "- `ADD` locations and symbols are resolved in the branch tip.",
            "- `DEL` locations and symbols are resolved in v2.7.5 "
            "because those lines do not exist in the branch tip.",
            "- A replacement is represented exactly as its Git deletion line(s) "
            "followed by its Git addition line(s).",
            "- Text after `│` is the exact line content; "
            "an empty value denotes a blank line.",
            "",
            body,
            "",
        ]
    )


def generate_history_report(base: str, tip: str, repo_url: str) -> str:
    commits = git(
        "rev-list", "--reverse", "--topo-order", f"{base}..{tip}"
    ).splitlines()
    output: list[str] = [
        "# Baeniv `main`: exhaustive commit-by-commit line ledger",
        "",
        "This companion report records every line changed by every non-merge "
        "commit after the branch point,",
        "including temporary work that was later changed or removed. "
        "Merge commits are inspected separately",
        "and are not expanded when they introduce no tree content beyond "
        "an existing parent, avoiding double-counting.",
        "",
    ]
    total_additions = total_deletions = 0

    for commit_number, commit in enumerate(commits, 1):
        metadata = commit_metadata(commit)
        parents = metadata["parents"].split()
        output.extend(
            [
                f"# Commit {commit_number}: `{commit[:12]}` — {metadata['subject']}",
                "",
                f"- Author: {metadata['author']}",
                f"- Date: {metadata['date']}",
                f"- Parent(s): `{metadata['parents']}`",
                "",
            ]
        )

        if len(parents) > 1:
            identical_parent = next(
                (
                    parent
                    for parent in parents
                    if git("rev-parse", f"{parent}^{{tree}}").strip()
                    == git("rev-parse", f"{commit}^{{tree}}").strip()
                ),
                None,
            )
            if identical_parent:
                output.extend(
                    [
                        f"Merge tree is identical to parent `{identical_parent}`; "
                        "it contributes no novel lines beyond that "
                        "already-listed parent commit.",
                        "",
                    ]
                )
                continue
            output.extend(
                [
                    "Merge has a novel tree result. The ledger below compares "
                    "it with its first parent.",
                    "",
                ]
            )

        parent = parents[0]
        files = parse_diff(parent, commit)
        annotate(files, parent, commit)
        validate_line_locations(files, parent, commit)
        body, additions, deletions = render_diff_section(
            files,
            parent,
            commit,
            f"parent {parent[:12]}",
            f"commit {commit[:12]}",
            repo_url,
        )
        total_additions += additions
        total_deletions += deletions
        output.extend(
            [
                f"Commit line totals: **{additions} added, {deletions} removed**.",
                "",
                body,
                "",
            ]
        )

    output[5:5] = [
        f"Non-merge line-event totals: **{total_additions} additions, "
        f"{total_deletions} deletions**.",
        "These are historical events and intentionally include lines "
        "later replaced or removed.",
        "",
    ]
    return "\n".join(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--tip", required=True)
    parser.add_argument("--net-output", type=Path, required=True)
    parser.add_argument("--history-output", type=Path, required=True)
    parser.add_argument("--repo-url", default="https://github.com/baeniv/ZEN-garden")
    args = parser.parse_args()

    args.net_output.parent.mkdir(parents=True, exist_ok=True)
    args.history_output.parent.mkdir(parents=True, exist_ok=True)
    args.net_output.write_text(
        generate_net_report(args.base, args.tip, args.repo_url), encoding="utf-8"
    )
    args.history_output.write_text(
        generate_history_report(args.base, args.tip, args.repo_url), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
