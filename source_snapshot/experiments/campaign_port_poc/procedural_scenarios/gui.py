"""PySide6 desktop application for procedural scenario generation and delivery."""

from __future__ import annotations

import copy
import json
from datetime import datetime
import secrets
import sys
import traceback
from pathlib import Path
from typing import Any, Callable

from .catalog import ContentKind
from .game_context import discover_golden_era_context
from .profile import ScenarioProfileV1
from .service import (
    build_catalog,
    generate_bundle,
    generated_library,
    install_generated_bundle,
    load_profile,
    uninstall_generated_scenario,
    validate_generated_bundle,
)

try:
    from PySide6.QtCore import QObject, QRunnable, QSettings, Qt, QThreadPool, Signal
    from PySide6.QtGui import QAction, QColor, QBrush, QPen
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QFileDialog,
        QFormLayout,
        QGraphicsScene,
        QGraphicsView,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QProgressBar,
        QPushButton,
        QScrollArea,
        QSpinBox,
        QDoubleSpinBox,
        QSplitter,
        QStyle,
        QTabWidget,
        QTableWidget,
        QTableWidgetItem,
        QToolBar,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover - exercised only without desktop deps
    raise RuntimeError(
        "PySide6 is required for the procedural scenario desktop application"
    ) from exc


class _TaskSignals(QObject):
    result = Signal(object)
    error = Signal(str)
    finished = Signal()


class _Task(QRunnable):
    def __init__(self, operation: Callable[[], Any]):
        super().__init__()
        self.operation = operation
        self.signals = _TaskSignals()

    def run(self) -> None:
        try:
            self.signals.result.emit(self.operation())
        except Exception:
            self.signals.error.emit(traceback.format_exc())
        finally:
            self.signals.finished.emit()


class ScenarioGeneratorWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Olden Era Procedural Scenarios")
        self.resize(1420, 900)
        self.pool = QThreadPool.globalInstance()
        self.settings = QSettings("Olden Era Modding", "Procedural Scenarios")
        self.catalog = None
        self.current_result = None
        self._build_ui()
        self._apply_profile(ScenarioProfileV1(seed=1).normalized())
        self._restore_install_context()
        self.refresh_library()

    def _build_ui(self) -> None:
        self._build_toolbar()
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_controls())
        splitter.addWidget(self._build_workspace())
        splitter.setSizes([430, 990])
        self.setCentralWidget(splitter)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(150)
        self.progress.setVisible(False)
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().showMessage("Ready")

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Profile")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        open_action = QAction(self.style().standardIcon(QStyle.SP_DialogOpenButton), "Open profile", self)
        open_action.setToolTip("Open profile")
        open_action.triggered.connect(self.open_profile)
        save_action = QAction(self.style().standardIcon(QStyle.SP_DialogSaveButton), "Save profile", self)
        save_action.setToolTip("Save profile")
        save_action.triggered.connect(self.save_profile)
        refresh_action = QAction(self.style().standardIcon(QStyle.SP_BrowserReload), "Refresh library", self)
        refresh_action.setToolTip("Refresh library")
        refresh_action.triggered.connect(self.refresh_library)
        toolbar.addAction(open_action)
        toolbar.addAction(save_action)
        toolbar.addSeparator()
        toolbar.addAction(refresh_action)

    def _path_row(
        self,
        target: QLineEdit,
        directory: bool = False,
        *,
        auto_detect: bool = False,
    ) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(target, 1)
        button = QPushButton()
        button.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        button.setToolTip("Browse")
        button.setFixedWidth(34)
        button.clicked.connect(lambda: self._browse_path(target, directory))
        layout.addWidget(button)
        if auto_detect:
            detect_button = QPushButton()
            detect_button.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
            detect_button.setToolTip("Auto-detect Golden Era installation")
            detect_button.setFixedWidth(34)
            detect_button.clicked.connect(lambda: self._detect_install())
            layout.addWidget(detect_button)
        return row

    def _build_controls(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        root = QVBoxLayout(body)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        paths = QGroupBox("Installation and delivery")
        form = QFormLayout(paths)
        self.game_root = QLineEdit()
        self.game_root.editingFinished.connect(self._store_game_root)
        self.library_root = QLineEdit(str(Path.cwd() / "build" / "procedural_library"))
        self.custom_manifests = QLineEdit()
        self.content_allowlist = QLineEdit()
        form.addRow(
            "Golden Era root",
            self._path_row(self.game_root, True, auto_detect=True),
        )
        form.addRow("Library", self._path_row(self.library_root, True))
        form.addRow("Custom manifests", self.custom_manifests)
        form.addRow("Content allowlist", self.content_allowlist)
        self.catalog_button = QPushButton("Build catalog")
        self.catalog_button.setIcon(self.style().standardIcon(QStyle.SP_FileDialogDetailedView))
        self.catalog_button.clicked.connect(self.build_content_catalog)
        form.addRow(self.catalog_button)
        root.addWidget(paths)

        profile_box = QGroupBox("Scenario profile")
        form = QFormLayout(profile_box)
        self.preset = QComboBox()
        self.preset.addItems(["Balanced", "Dense", "Lean", "Hard"])
        self.preset.currentTextChanged.connect(self._apply_preset)
        self.seed = QSpinBox()
        self.seed.setRange(0, 2_147_483_647)
        seed_row = QWidget()
        seed_layout = QHBoxLayout(seed_row)
        seed_layout.setContentsMargins(0, 0, 0, 0)
        seed_layout.addWidget(self.seed, 1)
        random_seed = QPushButton()
        random_seed.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        random_seed.setToolTip("Random seed")
        random_seed.clicked.connect(lambda: self.seed.setValue(secrets.randbelow(2_147_483_648)))
        seed_layout.addWidget(random_seed)
        self.archetype = QComboBox()
        self.archetype.addItems(["exploration", "conquest", "objective_chain"])
        self.map_size = QComboBox()
        self.map_size.addItems(["32", "48", "64"])
        self.player_faction = QComboBox()
        self.player_faction.setEditable(True)
        self.ai_factions = QLineEdit()
        self.ai_count = QSpinBox()
        self.ai_count.setRange(0, 7)
        self.difficulty = QComboBox()
        self.difficulty.addItems(["easy", "normal", "hard", "expert"])
        self.biomes = QLineEdit()
        form.addRow("Preset", self.preset)
        form.addRow("Seed", seed_row)
        form.addRow("Archetype", self.archetype)
        form.addRow("Map size", self.map_size)
        form.addRow("Player faction", self.player_faction)
        form.addRow("AI factions", self.ai_factions)
        form.addRow("AI count", self.ai_count)
        form.addRow("Difficulty", self.difficulty)
        form.addRow("Biomes", self.biomes)
        root.addWidget(profile_box)

        balance = QGroupBox("Balance and density")
        form = QFormLayout(balance)
        self.starting_gold = QSpinBox(); self.starting_gold.setRange(0, 1_000_000)
        self.reward_multiplier = QDoubleSpinBox(); self.reward_multiplier.setRange(0.1, 10.0); self.reward_multiplier.setSingleStep(0.1)
        self.recurring_income = QCheckBox()
        self.spacing_min = QSpinBox(); self.spacing_min.setRange(2, 1_000_000)
        self.spacing_max = QSpinBox(); self.spacing_max.setRange(2, 1_000_000)
        self.scenery_density = QDoubleSpinBox(); self.scenery_density.setRange(0.0, 100.0); self.scenery_density.setSingleStep(0.5)
        self.gameplay_per_zone = QDoubleSpinBox(); self.gameplay_per_zone.setRange(0.0, 5.0); self.gameplay_per_zone.setDecimals(2); self.gameplay_per_zone.setSingleStep(0.25)
        self.optional_loops = QCheckBox()
        self.high_risk = QCheckBox()
        self.high_risk_count = QSpinBox(); self.high_risk_count.setRange(0, 5)
        self.neutral_cities = QSpinBox(); self.neutral_cities.setRange(0, 8)
        self.roads = QCheckBox()
        self.elevation = QCheckBox()
        self.elevation_fraction = QDoubleSpinBox(); self.elevation_fraction.setRange(0.0, 0.6); self.elevation_fraction.setDecimals(2); self.elevation_fraction.setSingleStep(0.05)
        self.elevation.toggled.connect(self.elevation_fraction.setEnabled)
        form.addRow("Starting gold", self.starting_gold)
        form.addRow("Reward multiplier", self.reward_multiplier)
        form.addRow("Recurring income", self.recurring_income)
        form.addRow("Decision spacing min", self.spacing_min)
        form.addRow("Decision spacing max", self.spacing_max)
        form.addRow("Scenery / 100 tiles", self.scenery_density)
        form.addRow("Optional gameplay / zone", self.gameplay_per_zone)
        form.addRow("Optional loops", self.optional_loops)
        form.addRow("High-risk side areas", self.high_risk)
        form.addRow("High-risk area count", self.high_risk_count)
        form.addRow("Neutral cities", self.neutral_cities)
        form.addRow("Roads", self.roads)
        form.addRow("Elevation", self.elevation)
        form.addRow("Elevation fraction", self.elevation_fraction)
        root.addWidget(balance)

        events = QGroupBox("Events and text")
        form = QFormLayout(events)
        self.turn_events = QCheckBox(); self.visit_events = QCheckBox()
        self.defeat_events = QCheckBox(); self.capture_events = QCheckBox()
        self.resource_rewards = QCheckBox(); self.objective_progress = QCheckBox()
        self.locale = QLineEdit()
        self.text_mode = QComboBox(); self.text_mode.addItems(["none", "optional", "required"])
        self.endpoint = QLineEdit(); self.model = QLineEdit()
        form.addRow("Turn schedules", self.turn_events)
        form.addRow("Visits", self.visit_events)
        form.addRow("Squad defeats", self.defeat_events)
        form.addRow("Captures", self.capture_events)
        form.addRow("Resource rewards", self.resource_rewards)
        form.addRow("Objective progression", self.objective_progress)
        form.addRow("Locale", self.locale)
        form.addRow("Text mode", self.text_mode)
        form.addRow("Endpoint", self.endpoint)
        form.addRow("Model", self.model)
        root.addWidget(events)

        commands = QWidget()
        commands_layout = QHBoxLayout(commands)
        commands_layout.setContentsMargins(0, 0, 0, 0)
        self.generate_button = QPushButton("Generate")
        self.generate_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.generate_button.clicked.connect(self.generate)
        self.validate_button = QPushButton("Validate")
        self.validate_button.setIcon(self.style().standardIcon(QStyle.SP_DialogApplyButton))
        self.validate_button.clicked.connect(self.validate_selected)
        self.install_button = QPushButton("Install")
        self.install_button.setIcon(self.style().standardIcon(QStyle.SP_ArrowDown))
        self.install_button.clicked.connect(self.install_selected)
        self.uninstall_button = QPushButton("Uninstall")
        self.uninstall_button.setIcon(self.style().standardIcon(QStyle.SP_TrashIcon))
        self.uninstall_button.clicked.connect(self.uninstall_selected)
        for button in (self.generate_button, self.validate_button, self.install_button, self.uninstall_button):
            commands_layout.addWidget(button)
        root.addWidget(commands)
        root.addStretch(1)
        scroll.setWidget(body)
        scroll.setMinimumWidth(410)
        return scroll

    def _build_workspace(self) -> QWidget:
        tabs = QTabWidget()
        self.preview_scene = QGraphicsScene(self)
        self.preview_view = QGraphicsView(self.preview_scene)
        self.preview_view.setRenderHints(self.preview_view.renderHints())
        tabs.addTab(self.preview_view, "Map preview")
        self.summary = QPlainTextEdit(); self.summary.setReadOnly(True)
        tabs.addTab(self.summary, "Balance summary")
        self.diagnostics = QPlainTextEdit(); self.diagnostics.setReadOnly(True)
        tabs.addTab(self.diagnostics, "Diagnostics")
        activity = QWidget()
        activity_layout = QVBoxLayout(activity)
        activity_layout.setContentsMargins(0, 0, 0, 0)
        self.activity_log = QPlainTextEdit()
        self.activity_log.setReadOnly(True)
        self.activity_log.setMaximumBlockCount(2000)
        activity_layout.addWidget(self.activity_log, 1)
        activity_commands = QHBoxLayout()
        activity_commands.setContentsMargins(0, 0, 0, 0)
        copy_log = QPushButton("Copy log")
        copy_log.setIcon(self.style().standardIcon(QStyle.SP_DialogSaveButton))
        copy_log.setToolTip("Copy the activity log to the clipboard")
        copy_log.clicked.connect(self._copy_activity_log)
        clear_log = QPushButton("Clear")
        clear_log.setIcon(self.style().standardIcon(QStyle.SP_DialogResetButton))
        clear_log.setToolTip("Clear the activity log")
        clear_log.clicked.connect(self.activity_log.clear)
        activity_commands.addWidget(copy_log)
        activity_commands.addWidget(clear_log)
        activity_commands.addStretch(1)
        activity_layout.addLayout(activity_commands)
        tabs.addTab(activity, "Activity log")
        self.library = QTableWidget(0, 5)
        self.library.setHorizontalHeaderLabels(["Map SID", "Archetype", "Seed", "Version", "Path"])
        self.library.setSelectionBehavior(QTableWidget.SelectRows)
        self.library.setEditTriggers(QTableWidget.NoEditTriggers)
        self.library.itemSelectionChanged.connect(self._load_selected_preview)
        tabs.addTab(self.library, "Generated library")
        return tabs

    def _browse_path(self, target: QLineEdit, directory: bool) -> None:
        if directory:
            value = QFileDialog.getExistingDirectory(self, "Select directory", target.text())
        else:
            value, _ = QFileDialog.getOpenFileName(self, "Select file", target.text())
        if value:
            target.setText(value)
            if target is self.game_root:
                self._store_game_root()

    def _game_root_value(self) -> Path | None:
        value = self.game_root.text().strip()
        return Path(value) if value else None

    def _store_game_root(self) -> None:
        value = self.game_root.text().strip()
        if value:
            self.settings.setValue("goldenEraRoot", value)
        else:
            self.settings.remove("goldenEraRoot")

    def _restore_install_context(self) -> None:
        saved = str(self.settings.value("goldenEraRoot", "") or "").strip()
        if saved:
            self.game_root.setText(saved)
            try:
                context = discover_golden_era_context(game_root=saved)
            except Exception as exc:
                self._log(f"ERROR configured installation is invalid: {exc}")
                self.diagnostics.setPlainText(
                    json.dumps(
                        {"installContextError": str(exc), "configuredRoot": saved},
                        indent=2,
                        sort_keys=True,
                    )
                )
                return
            self.statusBar().showMessage(f"Golden Era: {context.game_root}")
            return
        self._detect_install(report_error=False)

    def _detect_install(self, report_error: bool = True) -> None:
        self._log("START installation auto-detection")
        try:
            context = discover_golden_era_context()
        except Exception as exc:
            detail = json.dumps(
                {"installContextError": str(exc)},
                indent=2,
                sort_keys=True,
            )
            self._log(f"ERROR installation auto-detection failed: {exc}")
            self.diagnostics.setPlainText(detail)
            if report_error:
                QMessageBox.critical(self, "Installation not found", str(exc))
            return
        self.game_root.setText(str(context.game_root))
        self._store_game_root()
        self._log(f"COMPLETE installation auto-detection: {context.game_root}")
        self.statusBar().showMessage(f"Golden Era: {context.game_root}")

    def _apply_preset(self, name: str) -> None:
        if not hasattr(self, "spacing_min"):
            return
        presets = {
            "Balanced": (8, 35, 3, "normal"),
            "Dense": (6, 50, 5, "hard"),
            "Lean": (10, 22, 2, "normal"),
            "Hard": (7, 40, 4, "expert"),
        }
        if name not in presets:
            return
        spacing, scenery, gameplay, difficulty = presets[name]
        self.spacing_min.setValue(max(6, spacing - 1))
        self.spacing_max.setValue(min(10, spacing + 1))
        self.scenery_density.setValue(scenery)
        self.gameplay_per_zone.setValue(gameplay)
        self.difficulty.setCurrentText(difficulty)

    def _profile(self) -> ScenarioProfileV1:
        raw = copy.deepcopy(self._profile_template)
        raw.update({
            "seed": self.seed.value(),
            "archetype": self.archetype.currentText(),
            "mapSize": int(self.map_size.currentText()),
            "playerFaction": self.player_faction.currentText().strip(),
            "aiFactions": [item.strip() for item in self.ai_factions.text().split(",") if item.strip()],
            "aiCount": self.ai_count.value(),
            "difficulty": self.difficulty.currentText(),
            "biomes": [item.strip() for item in self.biomes.text().split(",") if item.strip()],
            "locale": self.locale.text().strip(),
            "contentAllowlist": [
                item.strip()
                for item in self.content_allowlist.text().split(",")
                if item.strip()
            ],
        })
        raw["economy"].update({
            "startingGold": self.starting_gold.value(),
            "rewardMultiplier": self.reward_multiplier.value(),
            "recurringIncomeEnabled": self.recurring_income.isChecked(),
        })
        raw["density"].update({
            "decisionSpacingMin": self.spacing_min.value(),
            "decisionSpacingMax": self.spacing_max.value(),
            "sceneryPer100Tiles": self.scenery_density.value(),
            "optionalGameplayPerZone": self.gameplay_per_zone.value(),
        })
        raw["eventPolicy"].update({
            "turnSchedulesEnabled": self.turn_events.isChecked(),
            "visitEventsEnabled": self.visit_events.isChecked(),
            "squadDefeatEventsEnabled": self.defeat_events.isChecked(),
            "captureEventsEnabled": self.capture_events.isChecked(),
            "resourceRewardsEnabled": self.resource_rewards.isChecked(),
            "objectiveProgressEnabled": self.objective_progress.isChecked(),
        })
        raw["topology"].update({
            "optionalLoopsEnabled": self.optional_loops.isChecked(),
            "highRiskSideAreasEnabled": self.high_risk.isChecked(),
            "highRiskSideAreaCount": self.high_risk_count.value() if self.high_risk.isChecked() else 0,
            "neutralCityCount": self.neutral_cities.value(),
        })
        raw["terrain"]["roadsEnabled"] = self.roads.isChecked()
        raw["terrain"]["elevationEnabled"] = self.elevation.isChecked()
        raw["terrain"]["elevationFraction"] = self.elevation_fraction.value() if self.elevation.isChecked() else 0.0
        raw["textProvider"].update({
            "mode": self.text_mode.currentText(),
            "endpoint": self.endpoint.text().strip() or None,
            "model": self.model.text().strip() or None,
        })
        return ScenarioProfileV1.from_dict(raw).normalized()

    def _apply_profile(self, profile: ScenarioProfileV1) -> None:
        value = profile.normalized()
        self._profile_template = copy.deepcopy(value.to_dict())
        self.seed.setValue(value.seed)
        self.archetype.setCurrentText(value.archetype.value)
        self.map_size.setCurrentText(str(value.map_size))
        self.player_faction.setCurrentText(value.player_faction)
        self.ai_factions.setText(", ".join(value.ai_factions))
        self.ai_count.setValue(value.ai_count)
        self.difficulty.setCurrentText(value.difficulty.value)
        self.biomes.setText(", ".join(value.biomes))
        self.content_allowlist.setText(", ".join(value.content_allowlist))
        self.starting_gold.setValue(value.economy.starting_gold)
        self.reward_multiplier.setValue(value.economy.reward_multiplier)
        self.recurring_income.setChecked(value.economy.recurring_income_enabled)
        self.spacing_min.setValue(value.density.decision_spacing_min)
        self.spacing_max.setValue(value.density.decision_spacing_max)
        self.scenery_density.setValue(value.density.scenery_per_100_tiles)
        self.gameplay_per_zone.setValue(value.density.optional_gameplay_per_zone)
        self.optional_loops.setChecked(value.topology.optional_loops_enabled)
        self.high_risk.setChecked(value.topology.high_risk_side_areas_enabled)
        self.high_risk_count.setValue(value.topology.high_risk_side_area_count)
        self.neutral_cities.setValue(value.topology.neutral_city_count)
        self.roads.setChecked(value.terrain.roads_enabled)
        self.elevation.setChecked(value.terrain.elevation_enabled)
        self.elevation_fraction.setValue(value.terrain.elevation_fraction)
        self.turn_events.setChecked(value.event_policy.turn_schedules_enabled)
        self.visit_events.setChecked(value.event_policy.visit_events_enabled)
        self.defeat_events.setChecked(value.event_policy.squad_defeat_events_enabled)
        self.capture_events.setChecked(value.event_policy.capture_events_enabled)
        self.resource_rewards.setChecked(value.event_policy.resource_rewards_enabled)
        self.objective_progress.setChecked(value.event_policy.objective_progress_enabled)
        self.locale.setText(value.locale)
        self.text_mode.setCurrentText(value.text_provider.mode.value)
        self.endpoint.setText(value.text_provider.endpoint or "")
        self.model.setText(value.text_provider.model or "")

    def _log(self, message: str) -> None:
        if not hasattr(self, "activity_log"):
            return
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        self.activity_log.appendPlainText(f"[{stamp}] {message}")
        scrollbar = self.activity_log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _copy_activity_log(self) -> None:
        QApplication.clipboard().setText(self.activity_log.toPlainText())
        self.statusBar().showMessage("Activity log copied to clipboard")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.progress.setVisible(busy)
        for button in (
            self.catalog_button,
            self.generate_button,
            self.install_button,
            self.uninstall_button,
        ):
            button.setEnabled(not busy)

    def _task_finished(self) -> None:
        label = getattr(self, "_active_label", "operation")
        self._active_label = None
        self._active_success = None
        self._set_busy(False)
        self._log(f"IDLE {label}")
        self.statusBar().showMessage("Ready")

    def _submit(self, label: str, operation: Callable[[], Any], success: Callable[[Any], None]) -> None:
        if getattr(self, "_busy", False):
            self._task_error("Another mutating operation is already running.")
            return
        self._set_busy(True)
        self._active_label = label
        self._active_success = success
        self._log(f"START {label}")
        self.statusBar().showMessage(label)
        task = _Task(operation)
        task.signals.result.connect(self._task_result)

        task.signals.error.connect(self._task_error)
        task.signals.finished.connect(self._task_finished)
        self.pool.start(task)

    def _task_result(self, value: Any) -> None:
        label = getattr(self, "_active_label", "operation")
        success = getattr(self, "_active_success", None)
        self._log(f"RESULT {label}: {type(value).__name__}")
        if success is None:
            self._task_error("missing GUI completion handler")
            return
        try:
            success(value)
        except BaseException:
            self._log(f"ERROR completion handler: {label}")
            self._task_error(traceback.format_exc())
            return
        self._log(f"COMPLETE {label}")
    def _task_error(self, detail: str) -> None:
        self._log("ERROR operation failed")
        self._log(detail.rstrip())
        self.diagnostics.setPlainText(detail)
        QMessageBox.critical(self, "Operation failed", detail.splitlines()[-1])

    def _manifest_paths(self) -> tuple[Path, ...]:
        return tuple(
            Path(item.strip())
            for item in self.custom_manifests.text().split(";")
            if item.strip()
        )

    def build_content_catalog(self) -> None:
        profile = self._profile()
        game_root = self._game_root_value()
        manifests = self._manifest_paths()
        self._submit(
            "Building content catalog...",
            lambda: build_catalog(
                game_root=game_root,
                custom_manifests=manifests,
                allowlist=profile.content_allowlist,
            ),
            self._catalog_ready,
        )

    def _catalog_ready(self, catalog: Any) -> None:
        self.catalog = catalog
        factions = [
            entry.sid for entry in catalog.entries
            if entry.eligible and entry.kind is ContentKind.FACTION
        ]
        current = self.player_faction.currentText()
        self.player_faction.clear(); self.player_faction.addItems(sorted(factions))
        self.player_faction.setCurrentText(current)
        counts: dict[str, int] = {}
        for entry in catalog.entries:
            if entry.eligible:
                counts[entry.kind.value] = counts.get(entry.kind.value, 0) + 1
        self.summary.setPlainText(json.dumps({
            "catalogFingerprint": catalog.fingerprint,
            "sourceHashes": dict(catalog.source_hashes),
            "eligibleByKind": counts,
        }, indent=2, sort_keys=True))

    def generate(self) -> None:
        profile = self._profile()
        library_root = Path(self.library_root.text())
        game_root = self._game_root_value()
        manifests = self._manifest_paths()
        self._submit(
            "Generating and validating scenario...",
            lambda: generate_bundle(
                profile,
                game_root=game_root,
                output_root=library_root,
                publish_by_sid=True,
                custom_manifests=manifests,
                allowlist=profile.content_allowlist,
                flavor_cache_root=library_root / ".flavor_cache",
            ),
            self._generation_ready,
        )

    def _generation_ready(self, result: Any) -> None:
        self.current_result = result
        self._render_scenario(result.scenario.to_dict())
        self.diagnostics.setPlainText(json.dumps({
            "ir": result.ir_validation.to_dict(),
            "bundle": result.bundle_validation.to_dict(),
            "flavor": result.flavor.to_manifest_dict(),
            "warnings": list(result.warnings),
        }, indent=2, sort_keys=True))
        self.refresh_library()

    def _render_scenario(self, scenario: dict[str, Any]) -> None:
        self.preview_scene.clear()
        size = int(scenario["profile"]["mapSize"])
        terrain = scenario["terrain"]
        tile = max(5.0, min(12.0, 700.0 / size))
        colors = {
            "grass": QColor("#5f8f4e"), "forest": QColor("#346342"),
            "dirt": QColor("#92704c"), "desert": QColor("#c8ab62"),
            "snow": QColor("#d8e3e7"), "swamp": QColor("#4f6b58"),
            "lava": QColor("#8f4338"), "wasteland": QColor("#796c67"),
        }
        biome_map = terrain.get("biomeMap", [])
        blocked = terrain.get("blocked", [])
        no_pen = QPen(Qt.NoPen)
        for node in range(size * size):
            x, y = node % size, node // size
            biome = biome_map[node] if node < len(biome_map) else "grass"
            color = QColor("#2d3033") if node < len(blocked) and blocked[node] else colors.get(biome, QColor("#68745a"))
            self.preview_scene.addRect(x * tile, y * tile, tile + 0.2, tile + 0.2, no_pen, QBrush(color))
        role_by_zone = {
            zone["zoneId"]: zone.get("role", "transit")
            for zone in scenario["topology"].get("zones", [])
        }
        zone_colors = {
            "start": QColor(235, 238, 210, 45),
            "objective": QColor(245, 204, 69, 45),
            "victory": QColor(245, 204, 69, 60),
            "high_risk": QColor(189, 64, 85, 45),
            "settlement": QColor(84, 143, 190, 45),
            "transit": QColor(220, 220, 220, 22),
        }
        for zone in scenario["layout"].get("zones", []):
            center = zone["center"]
            radius_px = float(zone.get("radius", 1)) * tile
            color = zone_colors.get(role_by_zone.get(zone["zoneId"], "transit"), QColor(220, 220, 220, 22))
            outline = QColor(color); outline.setAlpha(150)
            item = self.preview_scene.addEllipse(
                (center["x"] + 0.5) * tile - radius_px,
                (center["y"] + 0.5) * tile - radius_px,
                radius_px * 2,
                radius_px * 2,
                QPen(outline),
                QBrush(color),
            )
            item.setToolTip(f"{zone['zoneId']}: {role_by_zone.get(zone['zoneId'], 'transit')}")
        route_pen = QPen(QColor("#d5c56e")); route_pen.setWidthF(max(1.5, tile * 0.25))
        for route in scenario["layout"].get("routes", []):
            cells = route.get("cells", [])
            for first, second in zip(cells, cells[1:]):
                self.preview_scene.addLine(
                    (first["x"] + 0.5) * tile, (first["y"] + 0.5) * tile,
                    (second["x"] + 0.5) * tile, (second["y"] + 0.5) * tile,
                    route_pen,
                )
        kind_colors = {
            "player_start": QColor("#f4f0d0"), "ai_settlement": QColor("#d7564b"),
            "objective": QColor("#f5cc45"), "encounter": QColor("#bd4055"),
            "reward": QColor("#5fd3ba"), "interactable": QColor("#72a8dc"),
            "scenery": QColor("#273f32"),
        }
        for placement in scenario.get("placements", []):
            origin = placement["origin"]
            radius = max(2.5, tile * (0.38 if placement["kind"] != "scenery" else 0.2))
            item = self.preview_scene.addEllipse(
                (origin["x"] + 0.5) * tile - radius,
                (origin["y"] + 0.5) * tile - radius,
                radius * 2,
                radius * 2,
                QPen(QColor("#1b1b1b")),
                QBrush(kind_colors.get(placement["kind"], QColor("white"))),
            )
            item.setToolTip(f"{placement['kind']}: {placement['contentSid']}")
        self.preview_scene.setSceneRect(0, 0, size * tile, size * tile)
        self.preview_view.fitInView(self.preview_scene.sceneRect(), Qt.KeepAspectRatio)
        self.summary.setPlainText(json.dumps({
            "mapSid": scenario["mapSid"],
            "archetype": scenario["profile"]["archetype"],
            "seed": scenario["seed"],
            "metrics": scenario["metrics"],
            "zones": scenario["topology"]["zones"],
            "stageSeeds": scenario["provenance"]["stageSeeds"],
        }, indent=2, sort_keys=True))

    def refresh_library(self) -> None:
        root = Path(self.library_root.text())
        rows = generated_library(root)
        library_issues: list[dict[str, str]] = []
        self.library.setRowCount(len(rows))
        for index, row in enumerate(rows):
            preview: dict[str, Any] = {}
            error = str(row.get("error") or "")
            if not error:
                try:
                    loaded_preview = json.loads(
                        (Path(row["path"]) / "preview.json").read_text(encoding="utf-8")
                    )
                    if not isinstance(loaded_preview, dict):
                        raise ValueError("preview root must be an object")
                    preview = loaded_preview
                except (OSError, json.JSONDecodeError, ValueError) as exc:
                    error = f"preview unreadable: {exc}"
            if error:
                library_issues.append({"path": str(row.get("path") or ""), "error": error})
            values = [
                row.get("mapSid") or ("<invalid>" if error else None),
                preview.get("archetype"),
                row.get("seed"),
                row.get("generatorVersion"),
                row.get("path"),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem("" if value is None else str(value))
                if error:
                    item.setToolTip(error)
                self.library.setItem(index, column, item)
        self.library.resizeColumnsToContents()
        if library_issues:
            self.diagnostics.setPlainText(
                json.dumps({"libraryIssues": library_issues}, indent=2, sort_keys=True)
            )

    def _selected_bundle(self) -> Path:
        rows = self.library.selectionModel().selectedRows()
        if not rows:
            if self.current_result is not None:
                return Path(self.current_result.bundle.root)
            raise ValueError("select a generated scenario")
        return Path(self.library.item(rows[0].row(), 4).text())

    def _load_selected_preview(self) -> None:
        bundle = self._selected_bundle()
        try:
            preview = json.loads((bundle / "preview.json").read_text(encoding="utf-8"))
            if not isinstance(preview, dict):
                raise ValueError("preview root must be an object")
            scenario = {
                "mapSid": preview.get("mapSid"), "seed": preview.get("seed"),
                "profile": {"mapSize": preview.get("size"), "archetype": preview.get("archetype")},
                "terrain": preview.get("terrain", {}), "layout": preview.get("layout", {}),
                "placements": preview.get("placements", []), "metrics": preview.get("metrics", {}),
                "topology": preview.get("topology", {}), "provenance": {"stageSeeds": {}},
            }
            self._render_scenario(scenario)
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            self.diagnostics.setPlainText(
                json.dumps(
                    {"previewError": str(exc), "bundle": str(bundle)},
                    indent=2,
                    sort_keys=True,
                )
            )

    def validate_selected(self) -> None:
        bundle = self._selected_bundle()
        self._submit("Validating bundle...", lambda: validate_generated_bundle(bundle), self._validation_ready)

    def _validation_ready(self, report: Any) -> None:
        self.diagnostics.setPlainText(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        if not report.ok:
            QMessageBox.warning(self, "Validation failed", "The bundle has validation errors.")

    def install_selected(self) -> None:
        bundle = self._selected_bundle()
        game_root = self._game_root_value()
        self._submit(
            "Installing scenario...",
            lambda: install_generated_bundle(bundle, game_root=game_root),
            lambda result: self.diagnostics.setPlainText(json.dumps({
                "mapSid": result.map_sid,
                "hashes": result.installed_hashes,
                "preflightChecks": list(result.preflight_checks),
            }, indent=2, sort_keys=True)),
        )

    def uninstall_selected(self) -> None:
        bundle = self._selected_bundle()
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        game_root = self._game_root_value()
        self._submit(
            "Uninstalling scenario...",
            lambda: uninstall_generated_scenario(manifest["mapSid"], game_root=game_root),
            lambda result: self.diagnostics.setPlainText(json.dumps({
                "mapSid": result.map_sid, "restored": list(result.restored)
            }, indent=2, sort_keys=True)),
        )

    def open_profile(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open profile", "", "JSON (*.json)")
        if path:
            self._apply_profile(load_profile(path))

    def save_profile(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save profile", "scenario.profile.json", "JSON (*.json)")
        if path:
            Path(path).write_text(
                json.dumps(self._profile().to_dict(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )


def main(argv: list[str] | None = None) -> int:
    app = QApplication(list(sys.argv if argv is None else argv))
    app.setApplicationName("Olden Era Procedural Scenarios")
    window = ScenarioGeneratorWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())