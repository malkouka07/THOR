#!/usr/bin/env python3

"""Wait for THOR work to finish, then run queued shell commands.

This is a local automation helper for long-running post-processing tasks.
It can wait for:

- one or more PIDs to exit
- one or more process regexes to disappear from `ps`
- one or more files to appear

After the wait conditions are satisfied, it runs queued shell commands in
order and writes a timestamped log.
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Wait for long-running THOR tasks, then run queued commands."
    )
    parser.add_argument(
        "--wait-pid",
        dest="wait_pids",
        action="append",
        type=int,
        default=[],
        help="PID to wait for. Can be given multiple times.",
    )
    parser.add_argument(
        "--wait-regex",
        dest="wait_regexes",
        action="append",
        default=[],
        help="Regex for processes that must disappear before queued commands start. Can be given multiple times.",
    )
    parser.add_argument(
        "--wait-file",
        dest="wait_files",
        action="append",
        type=Path,
        default=[],
        help="File that must exist before queued commands start. Can be given multiple times.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=60.0,
        help="Polling interval in seconds while waiting (default: 60).",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=None,
        help="Optional maximum wait time in seconds.",
    )
    parser.add_argument(
        "--cwd",
        type=Path,
        default=Path.cwd(),
        help="Working directory for queued commands (default: current directory).",
    )
    parser.add_argument(
        "--log-path",
        type=Path,
        default=None,
        help="Optional log file path. Default: ./wait_then_run_<timestamp>.log",
    )
    parser.add_argument(
        "--command",
        dest="commands",
        action="append",
        default=[],
        help="Shell command to run after waiting. Can be given multiple times.",
    )
    parser.add_argument(
        "--script",
        type=Path,
        default=None,
        help="Optional shell script to run after any --command entries.",
    )
    parser.add_argument(
        "--keep-going",
        action="store_true",
        help="Continue running later commands even if one command fails.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the plan and exit without waiting or running commands.",
    )
    args = parser.parse_args()

    if not args.commands and args.script is None:
        parser.error("provide at least one --command or a --script")

    if args.poll_seconds <= 0:
        parser.error("--poll-seconds must be > 0")

    if args.timeout_seconds is not None and args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be > 0")

    return args


def timestamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def build_log_path(requested: Path | None) -> Path:
    if requested is not None:
        return requested
    suffix = time.strftime("%Y%m%d_%H%M%S")
    return Path.cwd() / f"wait_then_run_{suffix}.log"


def ancestor_pids() -> set[int]:
    ancestors: set[int] = set()
    pid = os.getppid()

    while pid > 1 and pid not in ancestors:
        ancestors.add(pid)
        status_path = Path(f"/proc/{pid}/status")
        try:
            lines = status_path.read_text().splitlines()
        except OSError:
            break

        parent_pid = None
        for line in lines:
            if line.startswith("PPid:"):
                parent_pid = int(line.split()[1])
                break

        if parent_pid is None or parent_pid <= 1:
            break
        pid = parent_pid

    return ancestors


def pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def process_table(ignored_pids: set[int]) -> list[tuple[int, str]]:
    result = subprocess.run(
        ["ps", "-eo", "pid=,args="],
        capture_output=True,
        text=True,
        check=True,
    )
    rows: list[tuple[int, str]] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        pid_text, _, cmd = line.partition(" ")
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        if pid in ignored_pids:
            continue
        rows.append((pid, cmd))
    return rows


def wait_status(args: argparse.Namespace, ignored_pids: set[int]) -> tuple[bool, list[str]]:
    problems: list[str] = []

    living_pids = [pid for pid in args.wait_pids if pid_exists(pid)]
    if living_pids:
        problems.append("waiting for pid(s): " + ", ".join(map(str, living_pids)))

    if args.wait_regexes:
        rows = process_table(ignored_pids)
        for pattern in args.wait_regexes:
            regex = re.compile(pattern)
            matches = [f"{pid}:{cmd}" for pid, cmd in rows if regex.search(cmd)]
            if matches:
                preview = "; ".join(matches[:3])
                if len(matches) > 3:
                    preview += "; ..."
                problems.append(f'regex "{pattern}" still matches: {preview}')

    missing_files = [str(path) for path in args.wait_files if not path.exists()]
    if missing_files:
        problems.append("waiting for file(s): " + ", ".join(missing_files))

    return (len(problems) == 0, problems)


def log_line(handle, message: str) -> None:
    line = f"[{timestamp()}] {message}"
    print(line)
    handle.write(line + "\n")
    handle.flush()


def run_one_command(handle, command: str, cwd: Path) -> int:
    log_line(handle, f"RUN {command}")
    process = subprocess.Popen(
        ["/bin/bash", "-lc", command],
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    assert process.stdout is not None
    for line in process.stdout:
        handle.write(line)
        handle.flush()
        print(line, end="")

    return process.wait()


def main() -> int:
    args = parse_args()
    log_path = build_log_path(args.log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    args.cwd.mkdir(parents=True, exist_ok=True)

    command_queue = list(args.commands)
    if args.script is not None:
        command_queue.append(f"bash {shlex.quote(str(args.script))}")

    ignored_pids = {os.getpid(), *ancestor_pids()}

    with log_path.open("a", encoding="utf-8") as handle:
        log_line(handle, f"log path: {log_path}")
        log_line(handle, f"cwd: {args.cwd}")
        if args.wait_pids:
            log_line(handle, f"wait pids: {', '.join(map(str, args.wait_pids))}")
        if args.wait_regexes:
            log_line(handle, "wait regexes: " + " | ".join(args.wait_regexes))
        if args.wait_files:
            log_line(handle, "wait files: " + ", ".join(str(p) for p in args.wait_files))
        for index, command in enumerate(command_queue, start=1):
            log_line(handle, f"queued command {index}: {command}")

        if args.dry_run:
            log_line(handle, "dry-run requested; exiting without waiting or running commands")
            return 0

        start = time.monotonic()
        while True:
            ready, problems = wait_status(args, ignored_pids)
            if ready:
                log_line(handle, "all wait conditions satisfied; starting queued commands")
                break

            log_line(handle, "still waiting: " + " | ".join(problems))

            if args.timeout_seconds is not None:
                elapsed = time.monotonic() - start
                if elapsed >= args.timeout_seconds:
                    log_line(handle, "timeout reached before wait conditions were satisfied")
                    return 2

            time.sleep(args.poll_seconds)

        for index, command in enumerate(command_queue, start=1):
            exit_code = run_one_command(handle, command, args.cwd)
            log_line(handle, f"command {index} exit code: {exit_code}")
            if exit_code != 0 and not args.keep_going:
                log_line(handle, "stopping because a command failed")
                return exit_code

        log_line(handle, "queue finished successfully")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
