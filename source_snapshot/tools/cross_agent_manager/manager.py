"""JSON command-line interface for the cross-agent work manager."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Sequence

if __package__:
    from .store import ManagerError, Store
else:
    from store import ManagerError, Store


MAX_REQUEST_BYTES = 256 * 1024
DEFAULT_LIMIT = 50
MAX_MESSAGE_LIMIT = 500
MAX_SQLITE_INTEGER = (1 << 63) - 1


class InputError(Exception):
    """Expected input failure suitable for a machine-readable response."""


class UsageError(Exception):
    """Invalid command-line syntax without argparse's human-only output."""


class ProtocolError(Exception):
    """The store returned a result that violates the documented operation shape."""


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise UsageError(message)


def _positive_int(value: str) -> int:
    try:
        parsed = int(value, 10)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _nonnegative_int(value: str) -> int:
    try:
        parsed = int(value, 10)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    if parsed > MAX_SQLITE_INTEGER:
        raise argparse.ArgumentTypeError("must fit a signed 64-bit SQLite integer")
    return parsed


def _message_limit(value: str) -> int:
    parsed = _positive_int(value)
    if parsed > MAX_MESSAGE_LIMIT:
        raise argparse.ArgumentTypeError(f"must be between 1 and {MAX_MESSAGE_LIMIT}")
    return parsed


def _timeout_seconds(value: str) -> int:
    parsed = _positive_int(value)
    if parsed > 300:
        raise argparse.ArgumentTypeError("must be between 1 and 300 seconds")
    return parsed


def _nonblank(value: str) -> str:
    if not value.strip():
        raise argparse.ArgumentTypeError("must not be blank")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(
        description=(
            "Read and update the repository's shared cross-agent work board. "
            "Commands exchange JSON on stdout and never launch agents."
        )
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="repository root (default: this manager's containing repository)",
    )
    parser.add_argument(
        "--session",
        default=os.environ.get("CROSS_AGENT_SESSION"),
        help="agent session secret (defaults to CROSS_AGENT_SESSION)",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("init", help="initialize or verify the shared store")

    join = commands.add_parser("join", help="register this tool agent and issue a session")
    join.add_argument("--tool", required=True, type=_nonblank, help="agent tool, for example codex or claude")
    join.add_argument("--name", required=True, type=_nonblank, help="agent display name")
    join.add_argument("--external-id", required=True, type=_nonblank, help="stable id from the agent's host tool")

    commands.add_parser("status", help="show agent and active-claim status")

    board = commands.add_parser("board", help="show tasks for a project")
    board.add_argument("project", type=_nonblank)

    send = commands.add_parser("send", help="send a message to a project")
    send.add_argument("project", type=_nonblank)
    send.add_argument("--body", required=True, type=_nonblank)
    send.add_argument("--to", dest="to_agent", type=_nonblank, help="optional recipient agent id")
    send.add_argument("--task", type=_nonblank, help="optional task id for message context")
    send.add_argument("--request-id", type=_nonblank, help="optional idempotency key for this mutation")

    poll = commands.add_parser("poll", help="read project messages after a cursor")
    poll.add_argument("project", type=_nonblank)
    poll.add_argument("--after", type=_nonnegative_int, default=0)
    poll.add_argument("--limit", type=_message_limit, default=DEFAULT_LIMIT)

    wait = commands.add_parser("wait", help="wait for a project message")
    wait.add_argument("project", type=_nonblank)
    wait.add_argument("--after", type=_nonnegative_int, default=0)
    wait.add_argument("--timeout-seconds", type=_timeout_seconds, required=True)
    wait.add_argument("--limit", type=_message_limit, default=DEFAULT_LIMIT)

    call = commands.add_parser("call", help="invoke a store operation with a JSON object payload")
    call.add_argument("operation", type=_nonblank, help="store operation name, such as task.claim")
    source = call.add_mutually_exclusive_group(required=True)
    source.add_argument("--data", help="JSON object supplied directly on the command line")
    source.add_argument("--request", metavar="FILE", help="UTF-8 JSON request file")
    source.add_argument("--stdin", action="store_true", help="read a UTF-8 JSON request from stdin")

    return parser


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant {value}")


def _parse_payload(raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_REQUEST_BYTES:
        raise InputError(f"request exceeds the {MAX_REQUEST_BYTES}-byte limit")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InputError("request must be valid UTF-8") from exc
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise InputError(f"invalid JSON request: {exc}") from exc
    if not isinstance(payload, dict):
        raise InputError("request JSON must be an object")
    return payload


def _read_payload(args: argparse.Namespace) -> dict[str, Any]:
    if args.data is not None:
        try:
            raw = args.data.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise InputError("request must be valid UTF-8") from exc
    elif args.request is not None:
        try:
            with Path(args.request).open("rb") as request_file:
                raw = request_file.read(MAX_REQUEST_BYTES + 1)
        except OSError as exc:
            raise InputError("could not read request file") from exc
    else:
        try:
            raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        except (OSError, AttributeError) as exc:
            raise InputError("could not read request from stdin") from exc
        if not raw:
            raise InputError("stdin request is empty")
    return _parse_payload(raw)


def _call(store: Store, operation: str, payload: dict[str, Any], session: str | None) -> dict[str, Any]:
    call_session = None if operation == "agent.join" else session
    return store.call(operation, payload, session=call_session)


def _wait_for_messages(
    store: Store,
    project: str,
    after: int,
    timeout_seconds: int,
    limit: int,
    session: str | None,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        result = _call(
            store,
            "message.poll",
            {"project_id": project, "after": after, "limit": limit},
            session,
        )
        if not isinstance(result, dict):
            raise ProtocolError("message.poll returned a non-object result")
        try:
            messages = result["messages"]
            result["next_cursor"]
            result["has_more"]
        except KeyError as exc:
            raise ProtocolError("message.poll result is missing a required field") from exc
        if messages:
            return {**result, "timed_out": False}

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {**result, "next_cursor": after, "timed_out": True}
        time.sleep(min(1.0, remaining))


def _dispatch(args: argparse.Namespace) -> dict[str, Any]:
    store = Store(args.repo_root)
    if args.command == "init":
        return store.initialize()
    if args.command == "join":
        return _call(
            store,
            "agent.join",
            {"tool": args.tool, "name": args.name, "external_id": args.external_id},
            args.session,
        )
    if args.command == "status":
        return _call(store, "status", {}, args.session)
    if args.command == "board":
        return _call(store, "board", {"project_id": args.project}, args.session)
    if args.command == "send":
        payload: dict[str, Any] = {"project_id": args.project, "body": args.body}
        if args.to_agent is not None:
            payload["to_agent_id"] = args.to_agent
        if args.task is not None:
            payload["task_id"] = args.task
        if args.request_id is not None:
            payload["request_id"] = args.request_id
        return _call(store, "message.send", payload, args.session)
    if args.command == "poll":
        return _call(
            store,
            "message.poll",
            {"project_id": args.project, "after": args.after, "limit": args.limit},
            args.session,
        )
    if args.command == "wait":
        return _wait_for_messages(
            store,
            args.project,
            args.after,
            args.timeout_seconds,
            args.limit,
            args.session,
        )
    if args.command == "call":
        return _call(store, args.operation, _read_payload(args), args.session)
    raise InputError("unknown command")


def _emit(value: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=True, separators=(",", ":")) + "\n")


def run_cli(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        result = _dispatch(args)
    except UsageError as exc:
        _emit({"ok": False, "error": {"code": "invalid_arguments", "message": str(exc)}})
        return 2
    except InputError as exc:
        _emit({"ok": False, "error": {"code": "invalid_input", "message": str(exc)}})
        return 2
    except ProtocolError as exc:
        _emit({"ok": False, "error": {"code": "protocol_error", "message": str(exc)}})
        return 1
    except ManagerError as exc:
        _emit(
            {
                "ok": False,
                "error": {"code": str(exc.code), "message": str(exc.message)},
            }
        )
        return 1
    except KeyboardInterrupt:
        _emit({"ok": False, "error": {"code": "interrupted", "message": "operation interrupted"}})
        return 130
    _emit({"ok": True, "result": result})
    return 0


def main() -> None:
    raise SystemExit(run_cli())


if __name__ == "__main__":
    main()
