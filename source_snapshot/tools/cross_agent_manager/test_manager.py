"""Focused contract tests for the cross-agent SQLite work manager."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from typing import Any


PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parents[1]
TEST_SANDBOX = REPO_ROOT / ".cross-agent" / "tests"
CLI_PATH = PACKAGE_DIR / "manager.py"

if str(PACKAGE_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGE_DIR))

from store import ManagerError, Store  # noqa: E402


# The build contract runner may execute this tuple directly for a bounded suite.
QUICK_CONTRACT_TESTS = (
    "test_schema_identity_and_no_implicit_initialization",
    "test_scope_hierarchy_namespace_and_independent_projects",
    "test_junction_aliases_are_canonical_and_outside_aliases_rejected",
    "test_dependencies_revision_owner_and_blocked_scope_lock",
    "test_release_and_complete_require_versioned_handoff_evidence",
    "test_stale_owner_requires_explicit_authorized_recovery",
    "test_document_compare_and_swap_history_and_reopen",
    "test_message_visibility_pagination_idempotency_and_reopen",
    "test_independent_processes_serialize_overlapping_scope_claims",
    "test_cli_init_join_send_poll_credentials_and_structured_errors",
)


class ManagerContractTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_SANDBOX.mkdir(parents=True, exist_ok=True)
        self._scratch = tempfile.TemporaryDirectory(
            prefix="manager-", dir=str(TEST_SANDBOX)
        )
        self.scratch = Path(self._scratch.name)
        self.repo = self.scratch / "repo"
        self.repo.mkdir()
        self.database = self.repo / ".cross-agent" / "manager.sqlite3"
        self.database.parent.mkdir(parents=True)
        self.store = Store(self.repo, database=self.database)
        self.store.initialize()
        self.owner, self.owner_session = self._join("codex", "owner")
        self.other, self.other_session = self._join("claude", "other")
        self.project_id = self._project("Primary project")

    def tearDown(self) -> None:
        self._scratch.cleanup()

    def _join(self, tool: str, external_id: str) -> tuple[str, str]:
        result = self.store.call(
            "agent.join",
            {
                "name": external_id,
                "tool": tool,
                "external_id": external_id,
            },
        )
        return result["agent"]["id"], result["session"]

    def _project(self, title: str) -> str:
        result = self.store.call(
            "project.create",
            {
                "title": title,
                "objective": "Coordinate changes across tool agents.",
                "acceptance": "Shared state is durable and conflicts are explicit.",
                "authorization": "human-approved test fixture",
            },
            session=self.owner_session,
        )
        return result["project"]["id"]

    def _task(
        self,
        title: str,
        scopes: list[dict[str, str]] | None = None,
        depends_on: list[str] | None = None,
        project_id: str | None = None,
        session: str | None = None,
    ) -> dict[str, Any]:
        result = self.store.call(
            "task.create",
            {
                "project_id": project_id or self.project_id,
                "title": title,
                "acceptance": "The task has a durable, reviewable handoff.",
                "scopes": [] if scopes is None else scopes,
                "depends_on": [] if depends_on is None else depends_on,
            },
            session=session or self.owner_session,
        )
        return result["task"]

    def _doc(
        self, key: str, body: str, version: int = 0, title: str | None = None
    ) -> dict[str, Any]:
        result = self.store.call(
            "doc.put",
            {
                "project_id": self.project_id,
                "key": key,
                "title": title or key,
                "body": body,
                "expected_version": version,
            },
            session=self.owner_session,
        )
        return result["doc"]

    def _task_get(self, task_id: str, session: str | None = None) -> dict[str, Any]:
        result = self.store.call(
            "task.get", {"task_id": task_id}, session=session or self.owner_session
        )
        return result["task"]

    def _claim(
        self, task: dict[str, Any], session: str | None = None, revision: int | None = None
    ) -> dict[str, Any]:
        return self.store.call(
            "task.claim",
            {
                "task_id": task["id"],
                "expected_revision": task["revision"] if revision is None else revision,
            },
            session=session or self.owner_session,
        )["task"]

    def _complete(
        self, task: dict[str, Any], doc_id: str, session: str | None = None
    ) -> dict[str, Any]:
        return self.store.call(
            "task.complete",
            {
                "task_id": task["id"],
                "expected_revision": task["revision"],
                "summary": "Implementation and verification are complete.",
                "evidence": ["isolated contract test evidence"],
                "proof_tier": "source_static",
                "handoff_doc_id": doc_id,
            },
            session=session or self.owner_session,
        )["task"]

    def _expect_error(
        self, code: str, operation: str, payload: dict[str, Any], session: str | None
    ) -> ManagerError:
        with self.assertRaises(ManagerError) as caught:
            self.store.call(operation, payload, session=session)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    @staticmethod
    def _cli(
        repo: Path, *args: str, env: dict[str, str] | None = None, input_text: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, str(CLI_PATH), "--repo-root", str(repo), *args]
        return subprocess.run(
            command,
            cwd=str(REPO_ROOT),
            env=env,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    def _cli_json(
        self, repo: Path, *args: str, env: dict[str, str] | None = None
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
        process = self._cli(repo, *args, env=env)
        try:
            payload = json.loads(process.stdout)
        except json.JSONDecodeError as exc:
            self.fail(f"CLI returned non-JSON stdout: {process.stdout!r}; stderr={process.stderr!r}")
            raise exc
        return process, payload

    def _create_junction(self, link: Path, target: Path) -> None:
        if os.name != "nt":
            self.skipTest("Windows junction contract is only exercised on Windows")
        result = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"Could not create junction {link} -> {target}: {result.stdout}\n{result.stderr}",
        )

    def test_schema_identity_and_no_implicit_initialization(self) -> None:
        fresh_repo = self.scratch / "fresh"
        fresh_repo.mkdir()
        fresh_db = fresh_repo / ".cross-agent" / "manager.sqlite3"
        fresh_db.parent.mkdir()
        fresh_store = Store(fresh_repo, database=fresh_db)
        with self.assertRaises(ManagerError) as caught:
            fresh_store.call(
                "agent.join",
                {"name": "fresh", "tool": "codex", "external_id": "fresh"},
            )
        self.assertEqual(caught.exception.code, "uninitialized")
        self.assertFalse(fresh_db.exists(), "call() must not create or initialize the database")
        with self.assertRaises(ManagerError) as duplicate_error:
            self.store.call(
                "agent.join",
                {"name": "owner", "tool": "codex", "external_id": "owner"},
            )
        self.assertEqual(duplicate_error.exception.code, "conflict")

        wrong_repo = self.scratch / "wrong-repo"
        wrong_repo.mkdir()
        with self.assertRaises(ManagerError) as wrong_repo_error:
            Store(wrong_repo, database=self.database).call(
                "status", {}, session=self.owner_session
            )
        self.assertEqual(wrong_repo_error.exception.code, "wrong_repo")

        unknown_db = self.scratch / "unknown.sqlite3"
        with closing(sqlite3.connect(unknown_db)) as connection:
            connection.execute("CREATE TABLE unrelated (value TEXT)")
            connection.commit()
        with self.assertRaises(ManagerError) as schema_error:
            Store(self.repo, database=unknown_db).call(
                "status", {}, session=self.owner_session
            )
        self.assertEqual(schema_error.exception.code, "incompatible_schema")

        metadata_db = self.scratch / "metadata.sqlite3"
        with closing(sqlite3.connect(self.database)) as source:
            with closing(sqlite3.connect(metadata_db)) as destination:
                source.backup(destination)
                destination.execute("INSERT INTO manager_meta(key,value) VALUES('unexpected','value')")
                destination.commit()
        metadata_store = Store(self.repo, database=metadata_db)
        for action in (metadata_store.initialize, lambda: metadata_store.call("status", {}, session=self.owner_session)):
            with self.assertRaises(ManagerError) as metadata_error:
                action()
            self.assertEqual(metadata_error.exception.code, "incompatible_schema")

        mutated_db = self.scratch / "mutated.sqlite3"
        with closing(sqlite3.connect(self.database)) as source:
            with closing(sqlite3.connect(mutated_db)) as destination:
                source.backup(destination)
                destination.execute("ALTER TABLE projects ADD COLUMN unexpected TEXT")
                destination.commit()
        mutated_store = Store(self.repo, database=mutated_db)
        with self.assertRaises(ManagerError) as mutated_call:
            mutated_store.call("status", {}, session=self.owner_session)
        self.assertEqual(mutated_call.exception.code, "incompatible_schema")
        with self.assertRaises(ManagerError) as mutated_init:
            mutated_store.initialize()
        self.assertEqual(mutated_init.exception.code, "incompatible_schema")
        with closing(sqlite3.connect(mutated_db)) as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(projects)")}
        self.assertIn("unexpected", columns, "initialize() must not reset an unknown schema")

        trigger_db = self.scratch / "trigger.sqlite3"
        with closing(sqlite3.connect(self.database)) as source:
            with closing(sqlite3.connect(trigger_db)) as destination:
                source.backup(destination)
                destination.execute(
                    "CREATE TRIGGER unexpected_message_trigger AFTER INSERT ON messages "
                    "BEGIN SELECT 1; END"
                )
                destination.commit()
        with self.assertRaises(ManagerError) as trigger_call:
            Store(self.repo, database=trigger_db).call(
                "status", {}, session=self.owner_session
            )
        self.assertEqual(trigger_call.exception.code, "incompatible_schema")

    def test_scope_hierarchy_namespace_and_independent_projects(self) -> None:
        ancestor = self._task("ancestor", [{"path": r"src\Actors"}])
        descendant = self._task("descendant", [{"path": "SRC/actors/Attack.cs"}])
        unrelated = self._task("unrelated", [{"path": "src/audio"}])

        self._claim(ancestor)
        self._claim(unrelated)
        self._expect_error(
            "conflict",
            "task.claim",
            {"task_id": descendant["id"], "expected_revision": descendant["revision"]},
            self.other_session,
        )

        second_project = self._project("Independent project")
        same_repo_path = self._task(
            "same path in another project",
            [{"path": "src/actors/Attack.cs"}],
            project_id=second_project,
        )
        self._expect_error(
            "conflict",
            "task.claim",
            {"task_id": same_repo_path["id"], "expected_revision": same_repo_path["revision"]},
            self.other_session,
        )

        # Named resource keys use a namespace distinct from filesystem paths.
        resource = self._task("named resource", [{"resource": "src/Actors"}])
        self._claim(resource, self.other_session)
        deploy = self._task("deploy owner", [{"resource": "golden-era-deploy"}])
        self._claim(deploy)
        second_deploy = self._task(
            "other project deploy", [{"resource": "GOLDEN-ERA-DEPLOY"}], project_id=second_project
        )
        self._expect_error(
            "conflict",
            "task.claim",
            {"task_id": second_deploy["id"], "expected_revision": second_deploy["revision"]},
            self.other_session,
        )
        with self.assertRaises(ManagerError) as legacy_scope:
            self._task("legacy untyped scope", ["path:src/legacy"])
        self.assertEqual(legacy_scope.exception.code, "invalid_input")

    def test_junction_aliases_are_canonical_and_outside_aliases_rejected(self) -> None:
        source = self.repo / "src" / "canonical"
        source.mkdir(parents=True)
        alias = self.repo / "src" / "alias"
        self._create_junction(alias, source)

        target_task = self._task("canonical path", [{"path": "src/canonical/mesh"}])
        alias_task = self._task("junction alias", [{"path": "src/ALIAS/MESH/part.glb"}])
        self._claim(target_task)
        self._expect_error(
            "conflict",
            "task.claim",
            {"task_id": alias_task["id"], "expected_revision": alias_task["revision"]},
            self.other_session,
        )

        outside = self.scratch / "outside-repo"
        outside.mkdir()
        escape = self.repo / "external"
        self._create_junction(escape, outside)
        with self.assertRaises(ManagerError) as rejected:
            self._task("outside alias", [{"path": "external/file.txt"}])
        self.assertEqual(rejected.exception.code, "invalid_input")

        manager_alias = self.repo / "src" / "manager-state"
        self._create_junction(manager_alias, self.repo / ".cross-agent")
        with self.assertRaises(ManagerError) as reserved:
            self._task("manager alias", [{"path": "src/manager-state/state.sqlite3"}])
        self.assertEqual(reserved.exception.code, "invalid_input")

        drift_task = self._task("alias reservation", [{"path": "src/alias/drift"}])
        self._claim(drift_task)
        alias.rmdir()
        replacement = self.repo / "src" / "replacement"
        replacement.mkdir()
        self._create_junction(alias, replacement)
        unrelated = self._task("unrelated after alias drift", [{"path": "src/unrelated"}])
        self._expect_error(
            "conflict",
            "task.claim",
            {"task_id": unrelated["id"], "expected_revision": unrelated["revision"]},
            self.other_session,
        )

    def test_dependencies_revision_owner_and_blocked_scope_lock(self) -> None:
        prerequisite = self._task("prerequisite", [{"path": "src/shared"}])
        dependent = self._task(
            "dependent", [{"path": "src/shared/consumer.cs"}], [prerequisite["id"]]
        )
        blocked_competitor = self._task("competitor", [{"path": "src/shared/other.cs"}])

        self._expect_error(
            "conflict",
            "task.claim",
            {"task_id": dependent["id"], "expected_revision": dependent["revision"]},
            self.owner_session,
        )
        claimed = self._claim(prerequisite)
        self._expect_error(
            "conflict",
            "task.block",
            {
                "task_id": prerequisite["id"],
                "expected_revision": prerequisite["revision"],
                "reason": "stale revision",
            },
            self.owner_session,
        )
        self._expect_error(
            "unauthorized",
            "task.block",
            {
                "task_id": prerequisite["id"],
                "expected_revision": claimed["revision"],
                "reason": "not the owner",
            },
            self.other_session,
        )

        blocked = self.store.call(
            "task.block",
            {
                "task_id": prerequisite["id"],
                "expected_revision": claimed["revision"],
                "reason": "waiting on external input",
            },
            session=self.owner_session,
        )["task"]
        self.assertEqual(blocked["status"], "blocked")
        self._expect_error(
            "conflict",
            "task.claim",
            {
                "task_id": blocked_competitor["id"],
                "expected_revision": blocked_competitor["revision"],
            },
            self.other_session,
        )

        resumed = self.store.call(
            "task.resume",
            {
                "task_id": prerequisite["id"],
                "expected_revision": blocked["revision"],
                "reason": "external input received",
            },
            session=self.owner_session,
        )["task"]
        handoff = self._doc("prerequisite-handoff", "Prerequisite evidence")
        completed = self._complete(resumed, handoff["id"])
        self.assertEqual(completed["status"], "done")
        self._claim(dependent, self.other_session)

    def test_release_and_complete_require_versioned_handoff_evidence(self) -> None:
        released = self._task("release flow", [{"path": "src/release"}])
        contender = self._task("release contender", [{"path": "src/release/child.cs"}])
        doing = self._claim(released)
        missing_doc = {
            "task_id": doing["id"],
            "expected_revision": doing["revision"],
            "reason": "handing off",
        }
        self._expect_error("invalid_input", "task.release", missing_doc, self.owner_session)
        release_doc = self._doc(
            "release-handoff", "Released work and next steps", title="Initial handoff title"
        )
        freed = self.store.call(
            "task.release",
            {**missing_doc, "handoff_doc_id": release_doc["id"]},
            session=self.owner_session,
        )["task"]
        self.assertEqual(freed["status"], "todo")
        self.assertEqual(freed["handoff_doc_version"], release_doc["version"])
        self._doc(
            "release-handoff",
            "Edited after release",
            version=1,
            title="Updated handoff title",
        )
        self._claim(contender, self.other_session)
        competitor_doc = self._doc("contender-handoff", "Overlapping work is finished")
        completed_contender = self._complete(
            self._task_get(contender["id"], self.other_session),
            competitor_doc["id"],
            self.other_session,
        )
        self.assertEqual(completed_contender["status"], "done")
        self._claim(freed)
        history = self.store.call(
            "task.history", {"task_id": released["id"]}, session=self.owner_session
        )["history"]
        release_history = next(entry for entry in history if entry["action"] == "release")
        self.assertEqual(release_history["handoff_doc_id"], release_doc["id"])
        self.assertEqual(release_history["handoff_doc_version"], 1)
        historical_handoff = self.store.call(
            "doc.get",
            {"project_id": self.project_id, "key": "release-handoff", "version": 1},
            session=self.owner_session,
        )["doc"]
        self.assertEqual(historical_handoff["title"], "Initial handoff title")

        task = self._task("complete flow", [{"path": "src/complete"}])
        doing = self._claim(task)
        handoff = self._doc("complete-handoff", "Completion evidence at version one")
        base = {
            "task_id": doing["id"],
            "expected_revision": doing["revision"],
            "summary": "done",
        }
        self._expect_error(
            "invalid_input",
            "task.complete",
            {**base, "proof_tier": "source_static", "handoff_doc_id": handoff["id"]},
            self.owner_session,
        )
        self._expect_error(
            "invalid_input",
            "task.complete",
            {**base, "evidence": ["artifact"], "handoff_doc_id": handoff["id"]},
            self.owner_session,
        )
        self._expect_error(
            "invalid_input",
            "task.complete",
            {**base, "evidence": ["artifact"], "proof_tier": "invented", "handoff_doc_id": handoff["id"]},
            self.owner_session,
        )
        self._expect_error(
            "invalid_input",
            "task.complete",
            {**base, "evidence": ["artifact"], "proof_tier": "source_static"},
            self.owner_session,
        )
        completed = self.store.call(
            "task.complete",
            {
                **base,
                "evidence": ["isolated test evidence"],
                "proof_tier": "source_static",
                "handoff_doc_id": handoff["id"],
            },
            session=self.owner_session,
        )["task"]
        self.assertEqual(completed["status"], "done")
        self.assertEqual(completed["handoff_doc_version"], 1)
        self._doc("complete-handoff", "Later update after completion", version=1)
        latest = self._task_get(task["id"])
        self.assertEqual(latest["handoff_doc_version"], 1)

    def test_stale_owner_requires_explicit_authorized_recovery(self) -> None:
        task = self._task("recoverable", [{"path": "src/recover"}])
        competitor = self._task("recovery contender", [{"path": "src/recover/child.cs"}])
        doing = self._claim(task)
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("UPDATE agents SET last_seen=0 WHERE id=?", (self.owner,))
            connection.commit()

        # A stale heartbeat changes status reporting only; it cannot steal a scope.
        self._expect_error(
            "conflict",
            "task.claim",
            {"task_id": competitor["id"], "expected_revision": competitor["revision"]},
            self.other_session,
        )
        handoff = self._doc("recovery-handoff", "Owner stopped; work is recoverable")
        base = {
            "task_id": task["id"],
            "expected_revision": doing["revision"],
            "reason": "recover from stopped agent",
            "handoff_doc_id": handoff["id"],
        }
        self._expect_error(
            "invalid_input",
            "task.recover",
            {**base, "owner_stopped": False, "authorization": "human approved"},
            self.other_session,
        )
        self._expect_error(
            "invalid_input",
            "task.recover",
            {**base, "owner_stopped": True, "authorization": "  "},
            self.other_session,
        )
        recovered = self.store.call(
            "task.recover",
            {**base, "owner_stopped": True, "authorization": "human-approved recovery"},
            session=self.other_session,
        )["task"]
        self.assertEqual(recovered["status"], "todo")
        self.assertEqual(recovered["handoff_doc_version"], 1)
        status = self.store.call("status", {}, session=self.other_session)
        owner_status = next(agent for agent in status["agents"] if agent["id"] == self.owner)
        self.assertTrue(owner_status["stale"])
        self._claim(competitor, self.other_session)

    def test_document_compare_and_swap_history_and_reopen(self) -> None:
        first = self._doc("design", "Decision at version one")
        self.assertEqual(first["version"], 1)
        second = self._doc(
            "design", "Decision updated: café / 建物", version=1, title="Design revision"
        )
        self.assertEqual(second["version"], 2)
        self._expect_error(
            "conflict",
            "doc.put",
            {
                "project_id": self.project_id,
                "key": "design",
                "title": "design",
                "body": "stale write",
                "expected_version": 1,
            },
            self.owner_session,
        )

        latest = self.store.call(
            "doc.get", {"project_id": self.project_id, "key": "design"}, session=self.owner_session
        )["doc"]
        historical = self.store.call(
            "doc.get",
            {"project_id": self.project_id, "key": "design", "version": 1},
            session=self.owner_session,
        )["doc"]
        self.assertEqual(
            (latest["version"], latest["body"]),
            (2, "Decision updated: café / 建物"),
        )
        self.assertEqual((historical["version"], historical["body"]), (1, "Decision at version one"))
        self.assertEqual(latest["title"], "Design revision")
        self.assertEqual(historical["title"], "design")

        reopened = Store(self.repo, database=self.database)
        persisted = reopened.call(
            "doc.get", {"project_id": self.project_id, "key": "design"}, session=self.owner_session
        )["doc"]
        self.assertEqual(persisted["body"], "Decision updated: café / 建物")

    def test_message_visibility_pagination_idempotency_and_reopen(self) -> None:
        def send(session: str, body: str, to_agent_id: str | None = None, request_id: str | None = None) -> dict[str, Any]:
            payload: dict[str, Any] = {"project_id": self.project_id, "body": body}
            if to_agent_id is not None:
                payload["to_agent_id"] = to_agent_id
            if request_id is not None:
                payload["request_id"] = request_id
            return self.store.call("message.send", payload, session=session)["message"]

        hidden = send(self.other_session, "only for other", self.other)
        first = send(self.other_session, "to owner", self.owner)
        second = send(self.owner_session, "owner outgoing", self.other)
        third = send(self.owner_session, "self note", self.owner)
        broadcast = send(self.other_session, "broadcast")
        unicode_message = send(self.other_session, "Résumé shared with everyone\nsecond line")
        self.assertEqual(hidden["id"], 1)

        cursor = 0
        seen: list[int] = []
        while True:
            page = self.store.call(
                "message.poll",
                {"project_id": self.project_id, "after": cursor, "limit": 2},
                session=self.owner_session,
            )
            ids = [message["id"] for message in page["messages"]]
            seen.extend(ids)
            if not page["has_more"]:
                break
            self.assertGreater(page["next_cursor"], cursor)
            cursor = page["next_cursor"]
        self.assertEqual(
            seen,
            [
                first["id"],
                second["id"],
                third["id"],
                broadcast["id"],
                unicode_message["id"],
            ],
        )
        self.assertNotIn(hidden["id"], seen)
        all_messages = self.store.call(
            "message.poll",
            {"project_id": self.project_id, "after": 0, "limit": 20},
            session=self.owner_session,
        )["messages"]
        unicode_record = next(message for message in all_messages if message["id"] == unicode_message["id"])
        self.assertEqual(unicode_record["body"], "Résumé shared with everyone\nsecond line")

        retry_payload = {
            "project_id": self.project_id,
            "body": "retry once",
            "to_agent_id": self.other,
            "request_id": "send-retry-1",
        }
        retry_result = self.store.call(
            "message.send", retry_payload, session=self.owner_session
        )
        retry_again_result = self.store.call(
            "message.send", retry_payload, session=self.owner_session
        )
        self.assertEqual(retry_result, retry_again_result)
        with self.assertRaises(ManagerError) as reused:
            self.store.call(
                "message.send",
                {**retry_payload, "body": "changed payload"},
                session=self.owner_session,
            )
        self.assertEqual(reused.exception.code, "conflict")

        message_doc = self._doc("message-persistence", "Messages persist across store handles")
        reopened = Store(self.repo, database=self.database)
        persisted_doc = reopened.call(
            "doc.get",
            {"project_id": self.project_id, "key": "message-persistence"},
            session=self.owner_session,
        )["doc"]
        self.assertEqual(persisted_doc["id"], message_doc["id"])
        persisted_messages = reopened.call(
            "message.poll",
            {"project_id": self.project_id, "after": 0, "limit": 20},
            session=self.owner_session,
        )["messages"]
        self.assertEqual(sum(m["body"] == "retry once" for m in persisted_messages), 1)

    def test_independent_processes_serialize_overlapping_scope_claims(self) -> None:
        first = self._task("process one", [{"path": r"src\units"}])
        second = self._task("process two", [{"path": "SRC/UNITS/child.cs"}])
        ready_one = self.scratch / "ready-one"
        ready_two = self.scratch / "ready-two"
        gate = self.scratch / "start"
        worker = r'''
import json, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from store import ManagerError, Store
repo, database, task_id, revision, session, ready, gate = sys.argv[2:]
Path(ready).write_text("ready", encoding="utf-8")
deadline = time.monotonic() + 8
while not Path(gate).exists():
    if time.monotonic() >= deadline:
        raise SystemExit("start gate timeout")
    time.sleep(0.005)
try:
    result = Store(Path(repo), database=Path(database)).call(
        "task.claim", {"task_id": task_id, "expected_revision": int(revision)}, session=session
    )
    print(json.dumps({"ok": True, "task": result["task"]["id"]}))
except ManagerError as exc:
    print(json.dumps({"ok": False, "code": str(exc.code)}))
'''

        def launch(task: dict[str, Any], session: str, ready: Path) -> subprocess.Popen[str]:
            return subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    worker,
                    str(PACKAGE_DIR),
                    str(self.repo),
                    str(self.database),
                    task["id"],
                    str(task["revision"]),
                    session,
                    str(ready),
                    str(gate),
                ],
                cwd=str(REPO_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

        processes = [
            launch(first, self.owner_session, ready_one),
            launch(second, self.other_session, ready_two),
        ]
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not (ready_one.exists() and ready_two.exists()):
                if any(process.poll() is not None for process in processes):
                    break
                time.sleep(0.01)
            self.assertTrue(ready_one.exists() and ready_two.exists(), "workers did not reach the race gate")
            gate.touch()
            outputs = [process.communicate(timeout=8) for process in processes]
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=2)

        outcomes = []
        for process, (stdout, stderr) in zip(processes, outputs):
            self.assertEqual(process.returncode, 0, stderr)
            outcomes.append(json.loads(stdout))
        self.assertEqual(sum(outcome["ok"] for outcome in outcomes), 1, outcomes)
        self.assertEqual(
            sorted(outcome.get("code", "") for outcome in outcomes if not outcome["ok"]),
            ["conflict"],
            outcomes,
        )

    def test_cli_init_join_send_poll_credentials_and_structured_errors(self) -> None:
        cli_repo = self.scratch / "cli-repo"
        cli_repo.mkdir()
        init, init_json = self._cli_json(cli_repo, "init")
        self.assertEqual(init.returncode, 0, init.stderr)
        self.assertTrue(init_json["ok"])

        join, join_json = self._cli_json(
            cli_repo,
            "join",
            "--tool",
            "codex",
            "--name",
            "cli-owner",
            "--external-id",
            "cli-owner-1",
        )
        self.assertEqual(join.returncode, 0, join.stderr)
        self.assertTrue(join_json["ok"])
        session = join_json["result"]["session"]
        agent_id = join_json["result"]["agent"]["id"]
        self.assertTrue(session)

        env = os.environ.copy()
        env["CROSS_AGENT_SESSION"] = session
        project_payload = json.dumps(
            {
                "title": "CLI project",
                "objective": "Exercise the real CLI entry point.",
                "acceptance": "Messages persist and are paged by cursor.",
                "authorization": "human-approved CLI test",
            }
        )
        project_call, project_json = self._cli_json(
            cli_repo, "call", "project.create", "--data", project_payload, env=env
        )
        self.assertEqual(project_call.returncode, 0, project_call.stderr)
        project_id = project_json["result"]["project"]["id"]

        sent, sent_json = self._cli_json(
            cli_repo,
            "send",
            project_id,
            "--body",
            "CLI message",
            "--request-id",
            "cli-send-1",
            env=env,
        )
        self.assertEqual(sent.returncode, 0, sent.stderr)
        self.assertNotIn(session, sent.stdout)
        message_id = sent_json["result"]["message"]["id"]
        resent, resent_json = self._cli_json(
            cli_repo,
            "send",
            project_id,
            "--body",
            "CLI message",
            "--request-id",
            "cli-send-1",
            env=env,
        )
        self.assertEqual(resent.returncode, 0, resent.stderr)
        self.assertEqual(resent_json["result"]["message"]["id"], message_id)

        polled, poll_json = self._cli_json(cli_repo, "poll", project_id, "--limit", "1", env=env)
        self.assertEqual(polled.returncode, 0, polled.stderr)
        self.assertEqual([m["id"] for m in poll_json["result"]["messages"]], [message_id])
        self.assertEqual(poll_json["result"]["messages"][0]["from_agent_id"], agent_id)

        unauthorized, unauthorized_json = self._cli_json(cli_repo, "status")
        self.assertNotEqual(unauthorized.returncode, 0)
        self.assertEqual(unauthorized_json["ok"], False)
        self.assertEqual(unauthorized_json["error"]["code"], "unauthorized")
        bad_limit, bad_limit_json = self._cli_json(cli_repo, "poll", project_id, "--limit", "0", env=env)
        self.assertEqual(bad_limit.returncode, 2)
        self.assertEqual(bad_limit_json["ok"], False)
        self.assertEqual(bad_limit_json["error"]["code"], "invalid_arguments")

        for raw in ('{"project_id":"one","project_id":"two"}', "[" * 2000 + "]" * 2000, "x" * (256 * 1024 + 1)):
            invalid = self._cli(cli_repo, "call", "message.send", "--stdin", env=env, input_text=raw)
            self.assertEqual(invalid.returncode, 2, invalid.stderr)
            invalid_json = json.loads(invalid.stdout)
            self.assertEqual(invalid_json["error"]["code"], "invalid_input")
            self.assertNotIn("Traceback", invalid.stderr)

        immediate, immediate_json = self._cli_json(
            cli_repo, "wait", project_id, "--after", "0", "--timeout-seconds", "1", env=env
        )
        self.assertEqual(immediate.returncode, 0, immediate.stderr)
        self.assertFalse(immediate_json["result"]["timed_out"])
        self.assertEqual(immediate_json["result"]["next_cursor"], message_id)
        empty_wait, empty_wait_json = self._cli_json(
            cli_repo, "wait", project_id, "--after", str(message_id), "--timeout-seconds", "1", env=env
        )
        self.assertEqual(empty_wait.returncode, 0, empty_wait.stderr)
        self.assertTrue(empty_wait_json["result"]["timed_out"])
        self.assertEqual(empty_wait_json["result"]["messages"], [])
        self.assertEqual(empty_wait_json["result"]["next_cursor"], message_id)


if __name__ == "__main__":
    unittest.main()
