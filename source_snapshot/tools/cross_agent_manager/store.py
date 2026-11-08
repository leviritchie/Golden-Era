"""Durable, repository-local state for the cross-agent work manager.

The database coordinates cooperating tools in one checkout. It is not a
filesystem permission boundary: consumers must still honor task scopes. Its
workload is serialized transactional I/O, not a GPU-parallel computation.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import time
import uuid
from functools import lru_cache
from pathlib import Path, PureWindowsPath
from typing import Any


_SCHEMA_VERSION = 1
_MAX_SQLITE_INT = 9223372036854775807
_PROOF_TIERS = {
    "source_static",
    "generated_artifact",
    "build_target",
    "installed_payload",
    "startup_smoke",
    "runtime_behavior",
    "user_visible_gameplay",
}
_MUTATIONS = {
    "agent.heartbeat",
    "project.create",
    "task.create",
    "task.claim",
    "task.block",
    "task.resume",
    "task.release",
    "task.complete",
    "task.recover",
    "message.send",
    "doc.put",
}
_SCHEMA_DDL = (
    "CREATE TABLE manager_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE TABLE agents(id TEXT PRIMARY KEY, name TEXT NOT NULL, tool TEXT NOT NULL, external_id TEXT NOT NULL, session_hash TEXT NOT NULL UNIQUE, joined_at REAL NOT NULL, last_seen REAL NOT NULL, UNIQUE(tool, external_id))",
    "CREATE TABLE projects(id TEXT PRIMARY KEY, title TEXT NOT NULL, objective TEXT NOT NULL, acceptance TEXT NOT NULL, authorization TEXT NOT NULL, created_by_agent_id TEXT NOT NULL REFERENCES agents(id), created_at REAL NOT NULL)",
    "CREATE TABLE docs(id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), key TEXT NOT NULL, title TEXT NOT NULL, latest_version INTEGER NOT NULL CHECK(latest_version >= 1), created_at REAL NOT NULL, updated_at REAL NOT NULL, UNIQUE(project_id, key))",
    "CREATE TABLE doc_versions(doc_id TEXT NOT NULL REFERENCES docs(id), version INTEGER NOT NULL CHECK(version >= 1), title TEXT NOT NULL, body TEXT NOT NULL, author_agent_id TEXT NOT NULL REFERENCES agents(id), created_at REAL NOT NULL, PRIMARY KEY(doc_id, version))",
    "CREATE TABLE tasks(id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), title TEXT NOT NULL, acceptance TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('todo', 'doing', 'blocked', 'done')), owner_agent_id TEXT REFERENCES agents(id), revision INTEGER NOT NULL CHECK(revision >= 1), created_by_agent_id TEXT NOT NULL REFERENCES agents(id), created_at REAL NOT NULL, updated_at REAL NOT NULL, handoff_doc_id TEXT REFERENCES docs(id), handoff_doc_version INTEGER, completion_summary TEXT, evidence_json TEXT, proof_tier TEXT)",
    "CREATE TABLE task_scopes(task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE, ordinal INTEGER NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('path', 'resource')), value TEXT NOT NULL, raw_value TEXT NOT NULL, PRIMARY KEY(task_id, ordinal))",
    "CREATE TABLE task_dependencies(task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE, depends_on_task_id TEXT NOT NULL REFERENCES tasks(id), ordinal INTEGER NOT NULL, PRIMARY KEY(task_id, depends_on_task_id), UNIQUE(task_id, ordinal), CHECK(task_id <> depends_on_task_id))",
    "CREATE TABLE messages(id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL REFERENCES projects(id), from_agent_id TEXT NOT NULL REFERENCES agents(id), to_agent_id TEXT REFERENCES agents(id), task_id TEXT REFERENCES tasks(id), body TEXT NOT NULL, created_at REAL NOT NULL)",
    "CREATE INDEX messages_project_id_idx ON messages(project_id, id)",
    "CREATE TABLE task_history(id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL REFERENCES tasks(id), revision INTEGER NOT NULL, actor_agent_id TEXT NOT NULL REFERENCES agents(id), from_status TEXT, to_status TEXT NOT NULL, action TEXT NOT NULL, details_json TEXT NOT NULL, created_at REAL NOT NULL, handoff_doc_id TEXT REFERENCES docs(id), handoff_doc_version INTEGER)",
    "CREATE TABLE audit_events(id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT REFERENCES projects(id), actor_agent_id TEXT NOT NULL REFERENCES agents(id), entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, action TEXT NOT NULL, details_json TEXT NOT NULL, created_at REAL NOT NULL)",
    "CREATE TABLE mutation_requests(actor_agent_id TEXT NOT NULL REFERENCES agents(id), request_id TEXT NOT NULL, operation TEXT NOT NULL, request_hash TEXT NOT NULL, response_json TEXT NOT NULL, created_at REAL NOT NULL, PRIMARY KEY(actor_agent_id, request_id))",
)


@lru_cache(maxsize=1)
def _expected_schema_objects() -> tuple[tuple[str, str, str, str | None], ...]:
    conn = sqlite3.connect(":memory:")
    try:
        for statement in _SCHEMA_DDL:
            conn.execute(statement)
        rows = conn.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return tuple(sorted((str(row[0]), str(row[1]), str(row[2]), row[3]) for row in rows))
    finally:
        conn.close()


class ManagerError(Exception):
    """A stable, caller-readable manager failure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class Store:
    def __init__(self, repo_root: Path, database: Path | None = None):
        try:
            root = Path(repo_root).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ManagerError("invalid_input", "Repository root cannot be resolved") from exc
        if not root.is_dir():
            raise ManagerError("invalid_input", "Repository root must be a directory")
        self.repo_root = root

        if database is None:
            db_path = root / ".cross-agent" / "state.sqlite3"
        else:
            db_path = Path(database).expanduser()
            if not db_path.is_absolute():
                db_path = root / db_path
        try:
            self.database = db_path.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise ManagerError("invalid_input", "Database path cannot be resolved") from exc
        if database is None:
            try:
                self.database.relative_to(self.repo_root)
            except ValueError as exc:
                raise ManagerError("invalid_input", "Default manager database must remain inside the repository") from exc

    def initialize(self) -> dict[str, Any]:
        """Create a fresh v1 database or verify an existing compatible one."""
        try:
            self.database.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.database), timeout=3.0, isolation_level=None)
            try:
                self._configure(conn)
                conn.execute("BEGIN IMMEDIATE")
                if not self._user_objects(conn):
                    self._create_schema(conn)
                    conn.executemany(
                        "INSERT INTO manager_meta(key, value) VALUES(?, ?)",
                        (
                            ("schema_version", str(_SCHEMA_VERSION)),
                            ("repo_root", str(self.repo_root)),
                        ),
                    )
                    self._verify_schema(conn, allow_uninitialized=False)
                else:
                    self._verify_schema(conn, allow_uninitialized=False)
                conn.commit()
            except Exception:
                if conn.in_transaction:
                    conn.rollback()
                raise
            finally:
                conn.close()
        except ManagerError:
            raise
        except sqlite3.IntegrityError as exc:
            raise ManagerError("incompatible_schema", "Existing manager database is inconsistent") from exc
        except sqlite3.DatabaseError as exc:
            raise ManagerError("database_error", "Could not initialize manager database") from exc
        except OSError as exc:
            raise ManagerError("database_error", "Could not create manager database directory") from exc
        return {
            "initialized": True,
            "schema_version": _SCHEMA_VERSION,
            "repo_root": str(self.repo_root),
            "database": str(self.database),
        }

    def call(self, operation: str, payload: dict, session: str | None = None) -> dict:
        if not isinstance(operation, str) or not operation:
            raise ManagerError("invalid_input", "operation must be a nonempty string")
        if not isinstance(payload, dict):
            raise ManagerError("invalid_input", "payload must be an object")
        if operation == "agent.join":
            self._keys(payload, {"name", "tool", "external_id"})
            return self._join(payload)

        if operation not in self._operations():
            raise ManagerError("invalid_input", f"Unknown operation: {operation}")
        if not isinstance(session, str) or not session:
            raise ManagerError("unauthorized", "A joined agent session is required")

        request_id = None
        request_hash = None
        call_payload = payload
        if operation in _MUTATIONS and "request_id" in payload:
            call_payload = dict(payload)
            request_id = self._text(call_payload.pop("request_id"), "request_id", 128)
            request_hash = hashlib.sha256(
                (operation + "\0" + self._canonical_json(call_payload)).encode("utf-8")
            ).hexdigest()

        conn = self._open_existing()
        try:
            self._verify_schema(conn, allow_uninitialized=True)
            if operation in _MUTATIONS:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    actor = self._authenticate(conn, session)
                    if request_id is not None:
                        cached = conn.execute(
                            "SELECT operation, request_hash, response_json FROM mutation_requests "
                            "WHERE actor_agent_id = ? AND request_id = ?",
                            (actor["id"], request_id),
                        ).fetchone()
                        if cached is not None:
                            if cached["operation"] != operation or cached["request_hash"] != request_hash:
                                raise ManagerError("conflict", "request_id was already used for a different request")
                            result = json.loads(cached["response_json"])
                            conn.commit()
                            return result

                    result = self._dispatch(conn, operation, call_payload, actor)
                    if request_id is not None:
                        conn.execute(
                            "INSERT INTO mutation_requests(actor_agent_id, request_id, operation, request_hash, response_json, created_at) "
                            "VALUES(?, ?, ?, ?, ?, ?)",
                            (
                                actor["id"],
                                request_id,
                                operation,
                                request_hash,
                                self._canonical_json(result),
                                time.time(),
                            ),
                        )
                    conn.commit()
                    return result
                except Exception:
                    if conn.in_transaction:
                        conn.rollback()
                    raise

            conn.execute("BEGIN")
            try:
                actor = self._authenticate(conn, session)
                result = self._dispatch(conn, operation, call_payload, actor)
                conn.commit()
                return result
            except Exception:
                if conn.in_transaction:
                    conn.rollback()
                raise
        except ManagerError:
            raise
        except sqlite3.IntegrityError as exc:
            raise ManagerError("conflict", "The requested change conflicts with stored state") from exc
        except sqlite3.OperationalError as exc:
            raise ManagerError("database_error", "The manager database is busy or unavailable") from exc
        except sqlite3.DatabaseError as exc:
            raise ManagerError("database_error", "Could not access manager database") from exc
        finally:
            conn.close()

    @staticmethod
    def _operations() -> set[str]:
        return {
            "agent.heartbeat",
            "agent.list",
            "project.create",
            "project.list",
            "project.get",
            "task.create",
            "task.get",
            "task.history",
            "board",
            "task.claim",
            "task.block",
            "task.resume",
            "task.release",
            "task.complete",
            "task.recover",
            "message.send",
            "message.poll",
            "doc.put",
            "doc.get",
            "doc.list",
            "status",
        }

    def _join(self, payload: dict) -> dict:
        name = self._text(payload["name"], "name", 128)
        tool = self._text(payload["tool"], "tool", 64)
        external_id = self._text(payload["external_id"], "external_id", 256)
        conn = self._open_existing()
        try:
            self._verify_schema(conn, allow_uninitialized=True)
            conn.execute("BEGIN IMMEDIATE")
            try:
                if conn.execute(
                    "SELECT 1 FROM agents WHERE tool = ? AND external_id = ?",
                    (tool, external_id),
                ).fetchone():
                    raise ManagerError("conflict", "This tool/external_id pair has already joined")
                agent_id = uuid.uuid4().hex
                secret = secrets.token_urlsafe(32)
                now = time.time()
                conn.execute(
                    "INSERT INTO agents(id, name, tool, external_id, session_hash, joined_at, last_seen) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?)",
                    (agent_id, name, tool, external_id, self._session_hash(secret), now, now),
                )
                self._audit(conn, None, agent_id, "agent", agent_id, "join", {"name": name, "tool": tool, "external_id": external_id})
                conn.commit()
                return {
                    "agent": self._agent_row(
                        conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
                    ),
                    "session": secret,
                }
            except Exception:
                if conn.in_transaction:
                    conn.rollback()
                raise
        except ManagerError:
            raise
        except sqlite3.IntegrityError as exc:
            raise ManagerError("conflict", "This tool/external_id pair has already joined") from exc
        except sqlite3.DatabaseError as exc:
            raise ManagerError("database_error", "Could not join agent") from exc
        finally:
            conn.close()

    def _dispatch(self, conn: sqlite3.Connection, operation: str, payload: dict, actor: dict) -> dict:
        if operation == "agent.heartbeat":
            self._keys(payload, set())
            now = time.time()
            conn.execute("UPDATE agents SET last_seen = ? WHERE id = ?", (now, actor["id"]))
            self._audit(conn, None, actor["id"], "agent", actor["id"], "heartbeat", {})
            return {"agent": self._agent(conn, actor["id"])}

        if operation == "agent.list":
            self._keys(payload, set())
            rows = conn.execute("SELECT * FROM agents ORDER BY joined_at, id").fetchall()
            return {"agents": [self._agent_row(row) for row in rows]}

        if operation == "project.create":
            self._keys(payload, {"title", "objective", "acceptance", "authorization"})
            title = self._text(payload["title"], "title", 256)
            objective = self._text(payload["objective"], "objective", 16000)
            acceptance = self._text(payload["acceptance"], "acceptance", 16000)
            authorization = self._text(payload["authorization"], "authorization", 4096)
            project_id = uuid.uuid4().hex
            now = time.time()
            conn.execute(
                "INSERT INTO projects(id, title, objective, acceptance, authorization, created_by_agent_id, created_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                (project_id, title, objective, acceptance, authorization, actor["id"], now),
            )
            project = self._project(conn, project_id)
            self._audit(conn, project_id, actor["id"], "project", project_id, "create", {"title": title})
            return {"project": project}

        if operation == "project.list":
            self._keys(payload, set())
            rows = conn.execute("SELECT id FROM projects ORDER BY created_at, id").fetchall()
            return {"projects": [self._project(conn, row["id"]) for row in rows]}

        if operation == "project.get":
            self._keys(payload, {"project_id"})
            return {"project": self._project(conn, self._id(payload["project_id"], "project_id"))}

        if operation == "task.create":
            self._keys(payload, {"project_id", "title", "acceptance", "scopes", "depends_on"})
            project_id = self._id(payload["project_id"], "project_id")
            self._require_project(conn, project_id)
            title = self._text(payload["title"], "title", 256)
            acceptance = self._text(payload["acceptance"], "acceptance", 16000)
            scopes = self._normalize_scopes(payload["scopes"])
            depends_on = self._id_list(payload["depends_on"], "depends_on", 100)
            if len(set(depends_on)) != len(depends_on):
                raise ManagerError("invalid_input", "depends_on cannot contain duplicate task ids")
            for dependency_id in depends_on:
                dependency = conn.execute(
                    "SELECT project_id FROM tasks WHERE id = ?", (dependency_id,)
                ).fetchone()
                if dependency is None:
                    raise ManagerError("not_found", f"Dependency task not found: {dependency_id}")
                if dependency["project_id"] != project_id:
                    raise ManagerError("invalid_input", "Dependencies must belong to the same project")

            task_id = uuid.uuid4().hex
            now = time.time()
            conn.execute(
                "INSERT INTO tasks(id, project_id, title, acceptance, status, owner_agent_id, revision, created_by_agent_id, created_at, updated_at) "
                "VALUES(?, ?, ?, ?, 'todo', NULL, 1, ?, ?, ?)",
                (task_id, project_id, title, acceptance, actor["id"], now, now),
            )
            conn.executemany(
                "INSERT INTO task_scopes(task_id, ordinal, kind, value, raw_value) VALUES(?, ?, ?, ?, ?)",
                [(task_id, index, scope["kind"], scope["value"], scope["raw_value"]) for index, scope in enumerate(scopes)],
            )
            conn.executemany(
                "INSERT INTO task_dependencies(task_id, depends_on_task_id, ordinal) VALUES(?, ?, ?)",
                [(task_id, dependency_id, index) for index, dependency_id in enumerate(depends_on)],
            )
            task = self._task(conn, task_id)
            self._task_history(conn, task, actor["id"], None, "todo", "create", {"title": title})
            self._audit(conn, project_id, actor["id"], "task", task_id, "create", {"title": title})
            return {"task": task}

        if operation == "task.get":
            self._keys(payload, {"task_id"})
            return {"task": self._task(conn, self._id(payload["task_id"], "task_id"))}

        if operation == "task.history":
            self._keys(payload, {"task_id"})
            task_id = self._id(payload["task_id"], "task_id")
            self._task(conn, task_id)
            rows = conn.execute("SELECT * FROM task_history WHERE task_id = ? ORDER BY id", (task_id,)).fetchall()
            return {
                "task_id": task_id,
                "history": [
                    {
                        "id": row["id"],
                        "revision": row["revision"],
                        "actor_agent_id": row["actor_agent_id"],
                        "from_status": row["from_status"],
                        "to_status": row["to_status"],
                        "action": row["action"],
                        "details": json.loads(row["details_json"]),
                        "created_at": row["created_at"],
                        "handoff_doc_id": row["handoff_doc_id"],
                        "handoff_doc_version": row["handoff_doc_version"],
                    }
                    for row in rows
                ],
            }

        if operation == "board":
            self._keys(payload, {"project_id"})
            project_id = self._id(payload["project_id"], "project_id")
            project = self._project(conn, project_id)
            rows = conn.execute("SELECT id FROM tasks WHERE project_id = ? ORDER BY created_at, id", (project_id,)).fetchall()
            return {"project": project, "tasks": [self._task(conn, row["id"]) for row in rows]}

        if operation in {"task.claim", "task.block", "task.resume", "task.release", "task.complete", "task.recover"}:
            return self._task_transition(conn, operation, payload, actor)

        if operation == "message.send":
            self._keys(payload, {"project_id", "body"}, {"to_agent_id", "task_id"})
            project_id = self._id(payload["project_id"], "project_id")
            self._require_project(conn, project_id)
            body = self._body(payload["body"], "body", 65536)
            recipient = self._optional_id(payload.get("to_agent_id"), "to_agent_id")
            task_id = self._optional_id(payload.get("task_id"), "task_id")
            if recipient is not None and conn.execute("SELECT 1 FROM agents WHERE id = ?", (recipient,)).fetchone() is None:
                raise ManagerError("not_found", "Recipient agent does not exist")
            if task_id is not None:
                task = conn.execute("SELECT project_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
                if task is None:
                    raise ManagerError("not_found", "Message task does not exist")
                if task["project_id"] != project_id:
                    raise ManagerError("invalid_input", "Message task must belong to the message project")
            cursor = conn.execute(
                "INSERT INTO messages(project_id, from_agent_id, to_agent_id, task_id, body, created_at) VALUES(?, ?, ?, ?, ?, ?)",
                (project_id, actor["id"], recipient, task_id, body, time.time()),
            )
            message = self._message(conn, cursor.lastrowid)
            self._audit(conn, project_id, actor["id"], "message", str(cursor.lastrowid), "send", {"to_agent_id": recipient, "task_id": task_id})
            return {"message": message}

        if operation == "message.poll":
            self._keys(payload, {"project_id"}, {"after", "limit"})
            project_id = self._id(payload["project_id"], "project_id")
            self._require_project(conn, project_id)
            after = self._integer(payload.get("after", 0), "after", 0, _MAX_SQLITE_INT)
            limit = self._integer(payload.get("limit", 100), "limit", 1, 500)
            rows = conn.execute(
                "SELECT id FROM messages WHERE project_id = ? AND id > ? "
                "AND (to_agent_id IS NULL OR to_agent_id = ? OR from_agent_id = ?) ORDER BY id LIMIT ?",
                (project_id, after, actor["id"], actor["id"], limit + 1),
            ).fetchall()
            has_more = len(rows) > limit
            selected = rows[:limit]
            messages = [self._message(conn, row["id"]) for row in selected]
            next_cursor = selected[-1]["id"] if selected else after
            return {"messages": messages, "next_cursor": next_cursor, "has_more": has_more}

        if operation == "doc.put":
            self._keys(payload, {"project_id", "key", "title", "body", "expected_version"})
            project_id = self._id(payload["project_id"], "project_id")
            self._require_project(conn, project_id)
            key = self._text(payload["key"], "key", 256)
            title = self._text(payload["title"], "title", 256)
            body = self._body(payload["body"], "body", 1048576)
            expected = self._integer(payload["expected_version"], "expected_version", 0, _MAX_SQLITE_INT)
            doc = conn.execute("SELECT * FROM docs WHERE project_id = ? AND key = ?", (project_id, key)).fetchone()
            now = time.time()
            if doc is None:
                if expected != 0:
                    raise ManagerError("conflict", "Document does not exist at expected_version")
                doc_id = uuid.uuid4().hex
                version = 1
                conn.execute(
                    "INSERT INTO docs(id, project_id, key, title, latest_version, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?)",
                    (doc_id, project_id, key, title, version, now, now),
                )
            else:
                if expected != doc["latest_version"]:
                    raise ManagerError("conflict", "Document version changed; read latest before updating")
                if expected == _MAX_SQLITE_INT:
                    raise ManagerError("conflict", "Document version reached the SQLite integer limit")
                doc_id = doc["id"]
                version = expected + 1
                conn.execute(
                    "UPDATE docs SET title = ?, latest_version = ?, updated_at = ? WHERE id = ?",
                    (title, version, now, doc_id),
                )
            conn.execute(
                "INSERT INTO doc_versions(doc_id, version, title, body, author_agent_id, created_at) VALUES(?, ?, ?, ?, ?, ?)",
                (doc_id, version, title, body, actor["id"], now),
            )
            result = self._doc_version(conn, doc_id, version)
            self._audit(conn, project_id, actor["id"], "doc", doc_id, "put", {"key": key, "version": version})
            return {"doc": result}

        if operation == "doc.get":
            self._keys(payload, {"project_id", "key"}, {"version"})
            project_id = self._id(payload["project_id"], "project_id")
            self._require_project(conn, project_id)
            key = self._text(payload["key"], "key", 256)
            doc = conn.execute("SELECT * FROM docs WHERE project_id = ? AND key = ?", (project_id, key)).fetchone()
            if doc is None:
                raise ManagerError("not_found", "Document not found")
            version = self._integer(payload["version"], "version", 1, _MAX_SQLITE_INT) if "version" in payload else doc["latest_version"]
            return {"doc": self._doc_version(conn, doc["id"], version)}

        if operation == "doc.list":
            self._keys(payload, {"project_id"})
            project_id = self._id(payload["project_id"], "project_id")
            self._require_project(conn, project_id)
            rows = conn.execute("SELECT * FROM docs WHERE project_id = ? ORDER BY key, id", (project_id,)).fetchall()
            return {
                "docs": [
                    {
                        "id": row["id"],
                        "project_id": row["project_id"],
                        "key": row["key"],
                        "title": row["title"],
                        "version": row["latest_version"],
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"],
                    }
                    for row in rows
                ]
            }

        if operation == "status":
            self._keys(payload, set())
            grouped = conn.execute("SELECT status, COUNT(*) AS count FROM tasks GROUP BY status").fetchall()
            counts = {key: 0 for key in ("todo", "doing", "blocked", "done")}
            counts.update({row["status"]: row["count"] for row in grouped})
            counts["projects"] = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
            now = time.time()
            agents = []
            for row in conn.execute("SELECT * FROM agents ORDER BY name, id").fetchall():
                agent = self._agent_row(row)
                agent["stale"] = now - row["last_seen"] > 900.0
                agents.append(agent)
            rows = conn.execute(
                "SELECT id FROM tasks WHERE status IN ('doing', 'blocked') ORDER BY project_id, created_at, id"
            ).fetchall()
            return {
                "counts": counts,
                "agents": agents,
                "active_claims": [self._task(conn, row["id"]) for row in rows],
            }

        raise ManagerError("invalid_input", f"Unknown operation: {operation}")

    def _task_transition(self, conn: sqlite3.Connection, operation: str, payload: dict, actor: dict) -> dict:
        task_id = self._id(payload.get("task_id"), "task_id")
        task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if task is None:
            raise ManagerError("not_found", "Task not found")

        if operation == "task.claim":
            self._keys(payload, {"task_id", "expected_revision"})
            expected = self._expected_revision(payload["expected_revision"])
            self._check_revision(task, expected)
            if task["status"] != "todo":
                raise ManagerError("conflict", "Only todo tasks can be claimed")
            dependencies = conn.execute(
                "SELECT t.id, t.status FROM task_dependencies d JOIN tasks t ON t.id = d.depends_on_task_id WHERE d.task_id = ?",
                (task_id,),
            ).fetchall()
            unfinished = [row["id"] for row in dependencies if row["status"] != "done"]
            if unfinished:
                raise ManagerError("conflict", "Task dependencies must be done before claim")
            candidate_scopes = self._live_scopes(conn, task_id, is_active=False)
            active = conn.execute("SELECT id FROM tasks WHERE status IN ('doing', 'blocked') AND id <> ?", (task_id,)).fetchall()
            for active_row in active:
                for other in self._live_scopes(conn, active_row["id"], is_active=True):
                    if any(self._scopes_conflict(candidate, other) for candidate in candidate_scopes):
                        raise ManagerError("conflict", f"Scope conflicts with active task {active_row['id']}")
            self._write_task_state(conn, task, actor["id"], "doing", "claim", {}, actor["id"])
            result = self._task(conn, task_id)
            self._audit(conn, task["project_id"], actor["id"], "task", task_id, "claim", {})
            return {"task": result}

        if operation in {"task.block", "task.resume"}:
            self._keys(payload, {"task_id", "expected_revision", "reason"})
            expected = self._expected_revision(payload["expected_revision"])
            reason = self._text(payload["reason"], "reason", 4096)
            self._check_revision(task, expected)
            self._require_owner(task, actor)
            required, target = ("doing", "blocked") if operation == "task.block" else ("blocked", "doing")
            if task["status"] != required:
                raise ManagerError("conflict", f"Only {required} tasks can {operation.rsplit('.', 1)[1]}")
            self._write_task_state(conn, task, actor["id"], target, operation.rsplit(".", 1)[1], {"reason": reason}, task["owner_agent_id"])
            result = self._task(conn, task_id)
            self._audit(conn, task["project_id"], actor["id"], "task", task_id, operation.rsplit(".", 1)[1], {"reason": reason})
            return {"task": result}

        if operation == "task.release":
            self._keys(payload, {"task_id", "expected_revision", "reason", "handoff_doc_id"})
            expected = self._expected_revision(payload["expected_revision"])
            reason = self._text(payload["reason"], "reason", 4096)
            self._check_revision(task, expected)
            self._require_owner(task, actor)
            if task["status"] not in {"doing", "blocked"}:
                raise ManagerError("conflict", "Only doing or blocked tasks can be released")
            handoff_id, handoff_version = self._handoff_version(conn, task["project_id"], payload["handoff_doc_id"])
            details = {"reason": reason, "handoff_doc_id": handoff_id, "handoff_doc_version": handoff_version}
            self._write_task_state(conn, task, actor["id"], "todo", "release", details, None, handoff_id, handoff_version)
            result = self._task(conn, task_id)
            self._audit(conn, task["project_id"], actor["id"], "task", task_id, "release", details)
            return {"task": result}

        if operation == "task.complete":
            self._keys(payload, {"task_id", "expected_revision", "summary", "evidence", "proof_tier", "handoff_doc_id"})
            expected = self._expected_revision(payload["expected_revision"])
            summary = self._text(payload["summary"], "summary", 16000)
            evidence = self._string_list(payload["evidence"], "evidence", 100, 4096)
            if not evidence:
                raise ManagerError("invalid_input", "evidence must contain at least one nonempty string")
            proof_tier = self._text(payload["proof_tier"], "proof_tier", 64)
            if proof_tier not in _PROOF_TIERS:
                raise ManagerError("invalid_input", "proof_tier is not a supported proof classification")
            self._check_revision(task, expected)
            self._require_owner(task, actor)
            if task["status"] != "doing":
                raise ManagerError("conflict", "Only doing tasks can be completed")
            handoff_id, handoff_version = self._handoff_version(conn, task["project_id"], payload["handoff_doc_id"])
            details = {
                "summary": summary,
                "evidence": evidence,
                "proof_tier": proof_tier,
                "handoff_doc_id": handoff_id,
                "handoff_doc_version": handoff_version,
            }
            self._write_task_state(
                conn,
                task,
                actor["id"],
                "done",
                "complete",
                details,
                task["owner_agent_id"],
                handoff_id,
                handoff_version,
                summary,
                evidence,
                proof_tier,
            )
            result = self._task(conn, task_id)
            self._audit(conn, task["project_id"], actor["id"], "task", task_id, "complete", details)
            return {"task": result}

        if operation == "task.recover":
            self._keys(payload, {"task_id", "expected_revision", "reason", "authorization", "owner_stopped", "handoff_doc_id"})
            expected = self._expected_revision(payload["expected_revision"])
            reason = self._text(payload["reason"], "reason", 4096)
            authorization = self._text(payload["authorization"], "authorization", 4096)
            owner_stopped = payload["owner_stopped"]
            if not isinstance(owner_stopped, bool) or not owner_stopped:
                raise ManagerError("invalid_input", "Recovery requires owner_stopped=true")
            self._check_revision(task, expected)
            if task["status"] not in {"doing", "blocked"}:
                raise ManagerError("conflict", "Only doing or blocked tasks can be recovered")
            handoff_id, handoff_version = self._handoff_version(conn, task["project_id"], payload["handoff_doc_id"])
            details = {
                "reason": reason,
                "authorization": authorization,
                "owner_stopped": True,
                "handoff_doc_id": handoff_id,
                "handoff_doc_version": handoff_version,
            }
            self._write_task_state(conn, task, actor["id"], "todo", "recover", details, None, handoff_id, handoff_version)
            result = self._task(conn, task_id)
            self._audit(conn, task["project_id"], actor["id"], "task", task_id, "recover", details)
            return {"task": result}

        raise ManagerError("invalid_input", f"Unknown task transition: {operation}")

    def _write_task_state(
        self,
        conn: sqlite3.Connection,
        task: sqlite3.Row,
        actor_id: str,
        new_status: str,
        action: str,
        details: dict,
        owner_agent_id: str | None,
        handoff_doc_id: str | None = None,
        handoff_doc_version: int | None = None,
        summary: str | None = None,
        evidence: list[str] | None = None,
        proof_tier: str | None = None,
    ) -> None:
        if task["revision"] >= _MAX_SQLITE_INT:
            raise ManagerError("conflict", "Task revision reached the SQLite integer limit")
        now = time.time()
        revision = task["revision"] + 1
        conn.execute(
            "UPDATE tasks SET status = ?, owner_agent_id = ?, revision = ?, updated_at = ?, "
            "handoff_doc_id = ?, handoff_doc_version = ?, completion_summary = ?, evidence_json = ?, proof_tier = ? "
            "WHERE id = ?",
            (
                new_status,
                owner_agent_id,
                revision,
                now,
                handoff_doc_id,
                handoff_doc_version,
                summary,
                self._canonical_json(evidence) if evidence is not None else None,
                proof_tier,
                task["id"],
            ),
        )
        self._task_history(conn, self._task(conn, task["id"]), actor_id, task["status"], new_status, action, details)

    def _task_history(
        self,
        conn: sqlite3.Connection,
        task: dict,
        actor_id: str,
        from_status: str | None,
        to_status: str,
        action: str,
        details: dict,
    ) -> None:
        conn.execute(
            "INSERT INTO task_history(task_id, revision, actor_agent_id, from_status, to_status, action, details_json, created_at, handoff_doc_id, handoff_doc_version) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task["id"],
                task["revision"],
                actor_id,
                from_status,
                to_status,
                action,
                self._canonical_json(details),
                task["updated_at"],
                details.get("handoff_doc_id"),
                details.get("handoff_doc_version"),
            ),
        )

    def _live_scopes(self, conn: sqlite3.Connection, task_id: str, is_active: bool) -> list[dict]:
        rows = conn.execute(
            "SELECT kind, value, raw_value FROM task_scopes WHERE task_id = ? ORDER BY ordinal", (task_id,)
        ).fetchall()
        result = []
        for row in rows:
            if row["kind"] == "path":
                try:
                    value = self._canonical_path(row["raw_value"])["value"]
                except ManagerError as exc:
                    label = "active task" if is_active else "task"
                    raise ManagerError("conflict", f"{label} scope no longer resolves safely: {task_id}") from exc
                if value != row["value"]:
                    label = "active task" if is_active else "task"
                    raise ManagerError("conflict", f"{label} scope alias changed after creation: {task_id}")
            else:
                value = row["value"]
            result.append({"kind": row["kind"], "value": value})
        return result

    def _normalize_scopes(self, value: Any) -> list[dict]:
        if not isinstance(value, list):
            raise ManagerError("invalid_input", "scopes must be a list")
        if len(value) > 100:
            raise ManagerError("invalid_input", "scopes cannot contain more than 100 entries")
        result = []
        seen = set()
        for index, item in enumerate(value):
            if not isinstance(item, dict) or len(item) != 1:
                raise ManagerError("invalid_input", f"scopes[{index}] must contain exactly one path or resource key")
            if set(item) == {"path"}:
                normalized = self._canonical_path(item["path"])
                scope = {"kind": "path", **normalized}
            elif set(item) == {"resource"}:
                raw = self._text(item["resource"], f"scopes[{index}].resource", 1024)
                if any(char in raw for char in ("*", "?", "[", "]")):
                    raise ManagerError("invalid_input", "Resource names cannot contain wildcard characters")
                resource = raw.casefold()
                scope = {"kind": "resource", "value": resource, "raw_value": resource}
            else:
                raise ManagerError("invalid_input", f"scopes[{index}] must be exactly {{path}} or {{resource}}")
            identity = (scope["kind"], scope["value"])
            if identity in seen:
                raise ManagerError("invalid_input", "scopes cannot contain duplicate canonical entries")
            seen.add(identity)
            result.append(scope)
        return result

    def _canonical_path(self, value: Any) -> dict[str, str]:
        raw = self._text(value, "path scope", 2048)
        windows = PureWindowsPath(raw)
        if windows.drive or windows.root or windows.is_absolute():
            raise ManagerError("invalid_input", "Path scopes must be relative to the repository")
        slash = raw.replace("\\", "/")
        if slash.startswith("/") or "\x00" in slash:
            raise ManagerError("invalid_input", "Path scopes must be relative to the repository")
        parts = slash.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ManagerError("invalid_input", "Path scopes cannot contain empty, current, or traversal components")
        if any(any(char in part for char in ("*", "?", "[", "]", ":")) for part in parts):
            raise ManagerError("invalid_input", "Path scopes cannot contain wildcard or drive syntax")
        if any(part.endswith((" ", ".")) for part in parts):
            raise ManagerError("invalid_input", "Path scopes cannot use Windows trailing-dot or trailing-space aliases")
        if any(part.casefold() in {".git", ".cross-agent"} for part in parts):
            raise ManagerError("invalid_input", "Path scopes cannot include manager or Git state")
        try:
            target = self.repo_root.joinpath(*parts).resolve(strict=False)
            relative = target.relative_to(self.repo_root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ManagerError("invalid_input", "Path scope resolves outside the repository") from exc
        canonical_parts = relative.parts
        if not canonical_parts or any(part.casefold() in {".git", ".cross-agent"} for part in canonical_parts):
            raise ManagerError("invalid_input", "Path scopes cannot include manager or Git state")
        canonical = "/".join(canonical_parts).casefold()
        raw_value = "/".join(parts)
        return {"value": canonical, "raw_value": raw_value}

    @staticmethod
    def _scopes_conflict(left: dict, right: dict) -> bool:
        if left["kind"] != right["kind"]:
            return False
        if left["kind"] == "resource":
            return left["value"].casefold() == right["value"].casefold()
        a = left["value"].casefold().strip("/")
        b = right["value"].casefold().strip("/")
        return a == b or a.startswith(b + "/") or b.startswith(a + "/")

    def _handoff_version(self, conn: sqlite3.Connection, project_id: str, value: Any) -> tuple[str, int]:
        doc_id = self._id(value, "handoff_doc_id")
        row = conn.execute("SELECT project_id, latest_version FROM docs WHERE id = ?", (doc_id,)).fetchone()
        if row is None:
            raise ManagerError("not_found", "Handoff document does not exist")
        if row["project_id"] != project_id:
            raise ManagerError("invalid_input", "Handoff document must belong to the task project")
        return doc_id, row["latest_version"]

    def _doc_version(self, conn: sqlite3.Connection, doc_id: str, version: int) -> dict:
        row = conn.execute(
            "SELECT d.id, d.project_id, d.key, v.title, d.latest_version, v.version, v.body, v.author_agent_id, v.created_at "
            "FROM docs d JOIN doc_versions v ON v.doc_id = d.id WHERE d.id = ? AND v.version = ?",
            (doc_id, version),
        ).fetchone()
        if row is None:
            raise ManagerError("not_found", "Document version not found")
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "key": row["key"],
            "title": row["title"],
            "version": row["version"],
            "latest_version": row["latest_version"],
            "body": row["body"],
            "author_agent_id": row["author_agent_id"],
            "created_at": row["created_at"],
        }

    def _message(self, conn: sqlite3.Connection, message_id: int) -> dict:
        row = conn.execute(
            "SELECT m.*, a.name AS from_name FROM messages m JOIN agents a ON a.id = m.from_agent_id WHERE m.id = ?",
            (message_id,),
        ).fetchone()
        if row is None:
            raise ManagerError("not_found", "Message not found")
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "from_agent_id": row["from_agent_id"],
            "from_name": row["from_name"],
            "to_agent_id": row["to_agent_id"],
            "task_id": row["task_id"],
            "body": row["body"],
            "created_at": row["created_at"],
        }

    def _task(self, conn: sqlite3.Connection, task_id: str) -> dict:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise ManagerError("not_found", "Task not found")
        scopes = conn.execute(
            "SELECT kind, value FROM task_scopes WHERE task_id = ? ORDER BY ordinal", (task_id,)
        ).fetchall()
        dependencies = conn.execute(
            "SELECT depends_on_task_id FROM task_dependencies WHERE task_id = ? ORDER BY ordinal", (task_id,)
        ).fetchall()
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "title": row["title"],
            "acceptance": row["acceptance"],
            "status": row["status"],
            "owner_agent_id": row["owner_agent_id"],
            "revision": row["revision"],
            "scopes": [{"kind": scope["kind"], "value": scope["value"]} for scope in scopes],
            "depends_on": [dep["depends_on_task_id"] for dep in dependencies],
            "created_by_agent_id": row["created_by_agent_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "handoff_doc_id": row["handoff_doc_id"],
            "handoff_doc_version": row["handoff_doc_version"],
            "summary": row["completion_summary"],
            "evidence": json.loads(row["evidence_json"]) if row["evidence_json"] is not None else None,
            "proof_tier": row["proof_tier"],
        }

    def _project(self, conn: sqlite3.Connection, project_id: str) -> dict:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            raise ManagerError("not_found", "Project not found")
        return {
            "id": row["id"],
            "title": row["title"],
            "objective": row["objective"],
            "acceptance": row["acceptance"],
            "authorization": row["authorization"],
            "created_by_agent_id": row["created_by_agent_id"],
            "created_at": row["created_at"],
        }

    @staticmethod
    def _agent_row(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "name": row["name"],
            "tool": row["tool"],
            "external_id": row["external_id"],
            "joined_at": row["joined_at"],
            "last_seen": row["last_seen"],
        }

    def _agent(self, conn: sqlite3.Connection, agent_id: str) -> dict:
        row = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
        if row is None:
            raise ManagerError("not_found", "Agent not found")
        return self._agent_row(row)

    def _authenticate(self, conn: sqlite3.Connection, session: str) -> dict:
        if len(session) > 512:
            raise ManagerError("unauthorized", "Invalid agent session")
        try:
            session_hash = self._session_hash(session)
        except UnicodeEncodeError as exc:
            raise ManagerError("unauthorized", "Invalid agent session") from exc
        row = conn.execute("SELECT * FROM agents WHERE session_hash = ?", (session_hash,)).fetchone()
        if row is None:
            raise ManagerError("unauthorized", "Invalid agent session")
        return self._agent_row(row)

    @staticmethod
    def _session_hash(session: str) -> str:
        return hashlib.sha256(session.encode("utf-8")).hexdigest()

    def _require_project(self, conn: sqlite3.Connection, project_id: str) -> None:
        if conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone() is None:
            raise ManagerError("not_found", "Project not found")

    @staticmethod
    def _require_owner(task: sqlite3.Row, actor: dict) -> None:
        if task["owner_agent_id"] != actor["id"]:
            raise ManagerError("unauthorized", "Only the current task owner can change this task")

    @staticmethod
    def _check_revision(task: sqlite3.Row, expected: int) -> None:
        if task["revision"] != expected:
            raise ManagerError("conflict", "Task revision changed; read the latest task before updating")

    @staticmethod
    def _expected_revision(value: Any) -> int:
        return Store._integer(value, "expected_revision", 1, _MAX_SQLITE_INT)

    @staticmethod
    def _id(value: Any, field: str) -> str:
        if not isinstance(value, str) or len(value) != 32 or any(char not in "0123456789abcdef" for char in value):
            raise ManagerError("invalid_input", f"{field} must be a lowercase UUID hex id")
        return value

    def _optional_id(self, value: Any, field: str) -> str | None:
        return None if value is None else self._id(value, field)

    @staticmethod
    def _integer(value: Any, field: str, minimum: int, maximum: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum or value > maximum:
            raise ManagerError("invalid_input", f"{field} must be an integer from {minimum} through {maximum}")
        return value

    @staticmethod
    def _text(value: Any, field: str, max_length: int) -> str:
        if not isinstance(value, str):
            raise ManagerError("invalid_input", f"{field} must be a string")
        normalized = value.strip()
        if not normalized:
            raise ManagerError("invalid_input", f"{field} must not be empty")
        if len(normalized) > max_length:
            raise ManagerError("invalid_input", f"{field} exceeds {max_length} characters")
        if "\x00" in normalized:
            raise ManagerError("invalid_input", f"{field} cannot contain NUL")
        try:
            normalized.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ManagerError("invalid_input", f"{field} must contain valid Unicode text") from exc
        return normalized

    @staticmethod
    def _body(value: Any, field: str, max_length: int) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ManagerError("invalid_input", f"{field} must be a nonempty string")
        if len(value) > max_length:
            raise ManagerError("invalid_input", f"{field} exceeds {max_length} characters")
        if "\x00" in value:
            raise ManagerError("invalid_input", f"{field} cannot contain NUL")
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ManagerError("invalid_input", f"{field} must contain valid Unicode text") from exc
        return value

    def _string_list(self, value: Any, field: str, max_items: int, max_length: int) -> list[str]:
        if not isinstance(value, list) or len(value) > max_items:
            raise ManagerError("invalid_input", f"{field} must be a list of at most {max_items} strings")
        return [self._text(item, f"{field}[{index}]", max_length) for index, item in enumerate(value)]

    def _id_list(self, value: Any, field: str, max_items: int) -> list[str]:
        if not isinstance(value, list) or len(value) > max_items:
            raise ManagerError("invalid_input", f"{field} must be a list of at most {max_items} ids")
        return [self._id(item, f"{field}[{index}]") for index, item in enumerate(value)]

    @staticmethod
    def _keys(payload: dict, required: set[str], optional: set[str] | None = None) -> None:
        optional = optional or set()
        if any(not isinstance(key, str) for key in payload):
            raise ManagerError("invalid_input", "Payload keys must be strings")
        try:
            for key in payload:
                key.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ManagerError("invalid_input", "Payload keys must contain valid Unicode text") from exc
        unknown = set(payload) - required - optional
        missing = required - set(payload)
        if unknown:
            raise ManagerError("invalid_input", f"Unknown payload field(s): {', '.join(sorted(unknown))}")
        if missing:
            raise ManagerError("invalid_input", f"Missing payload field(s): {', '.join(sorted(missing))}")

    @staticmethod
    def _canonical_json(value: Any) -> str:
        try:
            return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
        except (TypeError, ValueError, RecursionError) as exc:
            raise ManagerError("invalid_input", "Payload must contain JSON-compatible values") from exc

    def _open_existing(self) -> sqlite3.Connection:
        if not self.database.is_file():
            raise ManagerError("uninitialized", "Run initialize() before using the manager")
        try:
            uri = self.database.as_uri() + "?mode=rw"
            conn = sqlite3.connect(uri, uri=True, timeout=3.0, isolation_level=None)
            self._configure(conn)
            return conn
        except ManagerError:
            raise
        except (OSError, sqlite3.DatabaseError, ValueError) as exc:
            raise ManagerError("database_error", "Could not open existing manager database") from exc

    @staticmethod
    def _configure(conn: sqlite3.Connection) -> None:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 3000")

    @staticmethod
    def _user_objects(conn: sqlite3.Connection) -> tuple[tuple[str, str, str, str | None], ...]:
        rows = conn.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return tuple(sorted((row["type"], row["name"], row["tbl_name"], row["sql"]) for row in rows))

    def _verify_schema(self, conn: sqlite3.Connection, allow_uninitialized: bool) -> None:
        objects = self._user_objects(conn)
        if not objects:
            if allow_uninitialized:
                raise ManagerError("uninitialized", "Run initialize() before using the manager")
            raise ManagerError("incompatible_schema", "Database has no manager schema")
        if not any(obj[0] == "table" and obj[1] == "manager_meta" for obj in objects):
            raise ManagerError("incompatible_schema", "Database contains objects but no manager schema")
        if objects != _expected_schema_objects():
            raise ManagerError("incompatible_schema", "Manager database has a partial or unknown schema")
        try:
            metadata = {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM manager_meta").fetchall()}
        except sqlite3.DatabaseError as exc:
            raise ManagerError("incompatible_schema", "Manager metadata is unreadable") from exc
        if set(metadata) != {"schema_version", "repo_root"}:
            raise ManagerError("incompatible_schema", "Manager metadata contains unknown or missing entries")
        if metadata.get("schema_version") != str(_SCHEMA_VERSION):
            raise ManagerError("incompatible_schema", "Manager database schema version is not supported")
        if metadata.get("repo_root") != str(self.repo_root):
            raise ManagerError("wrong_repo", "Manager database belongs to a different canonical repository root")

    def _create_schema(self, conn: sqlite3.Connection) -> None:
        for statement in _SCHEMA_DDL:
            conn.execute(statement)

    def _audit(
        self,
        conn: sqlite3.Connection,
        project_id: str | None,
        actor_agent_id: str,
        entity_type: str,
        entity_id: str,
        action: str,
        details: dict,
    ) -> None:
        conn.execute(
            "INSERT INTO audit_events(project_id, actor_agent_id, entity_type, entity_id, action, details_json, created_at) VALUES(?, ?, ?, ?, ?, ?, ?)",
            (project_id, actor_agent_id, entity_type, entity_id, action, self._canonical_json(details), time.time()),
        )
