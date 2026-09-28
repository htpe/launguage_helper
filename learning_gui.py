"""Study translations saved by Language Helper without modifying the log."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import random
import re
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

from PySide6.QtCore import QByteArray, QDate, QEvent, QSettings, QStandardPaths, QTimer, Qt
from PySide6.QtGui import QKeyEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


HEADER_PATTERN = re.compile(r"^\[(?P<timestamp>[^\]]+)\]\s{2}\((?P<languages>.*)\)$")
ORIGINAL_PATTERN = re.compile(r"^  Original : ?(.*)$")
EXAMPLES_PATTERN = re.compile(r"^  Examples\s*:")
EXAMPLE_PATTERN = re.compile(r"^    \d+\.\s?(.*)$")
EXAMPLE_CONTINUATION = "       "


@dataclass
class TranslationEntry:
    timestamp: datetime
    source_language: str
    target_languages: tuple[str, ...]
    original: str
    translations: dict[str, str] = field(default_factory=dict)
    examples: list[str] = field(default_factory=list)

    def stable_key(self, duplicate_index: int) -> str:
        content = {
            "timestamp": self.timestamp.isoformat(),
            "source": self.source_language,
            "targets": self.target_languages,
            "original": self.original,
            "translations": self.translations,
            "examples": self.examples,
            "duplicate_index": duplicate_index,
        }
        encoded = json.dumps(content, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass
class ParseResult:
    entries: list[TranslationEntry]
    warnings: list[str]
    entry_spans: list[tuple[int, int]] = field(default_factory=list)
    source_digest: str | None = None


def _parse_header(line: str) -> tuple[datetime, str, tuple[str, ...]] | None:
    match = HEADER_PATTERN.match(line)
    if not match:
        return None
    try:
        timestamp = datetime.strptime(match.group("timestamp"), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None

    languages = match.group("languages")
    if " → " not in languages:
        return None
    source, targets = languages.split(" → ", 1)
    target_languages = tuple(value.strip() for value in targets.split(",") if value.strip())
    return timestamp, source.strip(), target_languages


def parse_log_text(text: str) -> ParseResult:
    """Parse the app's plain-text log, including adjacent and multiline entries."""
    raw_lines = text.splitlines(keepends=True)
    lines = [line.rstrip("\r\n") for line in raw_lines]
    line_offsets: list[int] = []
    offset = 0
    for raw_line in raw_lines:
        line_offsets.append(offset)
        offset += len(raw_line)

    starts: list[tuple[int, int, datetime, str, tuple[str, ...]]] = []
    warnings: list[str] = []

    for index, line in enumerate(lines):
        if not line.startswith("["):
            continue
        parsed_header = _parse_header(line)
        if parsed_header is None:
            if re.match(r"^\[\d{4}-\d{2}-\d{2} ", line):
                warnings.append(f"Line {index + 1}: unrecognized or invalid record header.")
            continue
        timestamp, source_language, target_languages = parsed_header
        starts.append((index, line_offsets[index], timestamp, source_language, target_languages))
        if index + 1 >= len(lines) or not ORIGINAL_PATTERN.match(lines[index + 1]):
            warnings.append(f"Line {index + 1}: record header is not followed by an Original field.")

    if not starts:
        if text.strip():
            warnings.append("No valid translation records were found.")
        return ParseResult([], warnings)

    if any(line.strip() for line in lines[: starts[0][0]]):
        warnings.append("Text before the first record header was ignored.")

    entries: list[TranslationEntry] = []
    entry_spans: list[tuple[int, int]] = []
    for record_index, (start, char_start, timestamp, source_language, targets) in enumerate(starts):
        end = starts[record_index + 1][0] if record_index + 1 < len(starts) else len(lines)
        char_end = starts[record_index + 1][1] if record_index + 1 < len(starts) else len(text)
        original_lines: list[str] = []
        translations: dict[str, list[str]] = {}
        examples: list[list[str]] = []
        section: tuple[str, str | None] | None = None

        for line_number, line in enumerate(lines[start + 1 : end], start=start + 2):
            if not line.strip():
                continue

            original_match = ORIGINAL_PATTERN.match(line)
            if original_match:
                section = ("original", None)
                original_lines.append(original_match.group(1).rstrip())
                continue

            if EXAMPLES_PATTERN.match(line):
                section = ("examples", None)
                continue

            example_match = EXAMPLE_PATTERN.match(line)
            if example_match and section is not None and section[0] == "examples":
                examples.append([example_match.group(1).rstrip()])
                continue

            matched_target = None
            for target in targets:
                target_pattern = re.compile(rf"^  {re.escape(target)}\s*: ?(.*)$")
                target_match = target_pattern.match(line)
                if target_match:
                    matched_target = (target, target_match.group(1).rstrip())
                    break
            if matched_target is not None:
                language, value = matched_target
                translations.setdefault(language, []).append(value)
                section = ("translation", language)
                continue

            if section is not None and section[0] == "examples" and line.startswith(EXAMPLE_CONTINUATION):
                if examples:
                    examples[-1].append(line[len(EXAMPLE_CONTINUATION) :].rstrip())
                else:
                    warnings.append(f"Line {line_number}: example continuation has no numbered example.")
            elif section is not None and section[0] == "original":
                original_lines.append(line.rstrip())
            elif section is not None and section[0] == "translation":
                translations[section[1]].append(line.rstrip())
            elif section is not None and section[0] == "examples":
                warnings.append(f"Line {line_number}: unrecognized example line was ignored.")
            else:
                warnings.append(f"Line {line_number}: unrecognized content was ignored.")

        original = "\n".join(original_lines).strip()
        if not original:
            warnings.append(f"Record at line {start + 1} has no usable Original field and was skipped.")
            continue

        entries.append(
            TranslationEntry(
                timestamp=timestamp,
                source_language=source_language,
                target_languages=targets,
                original=original,
                translations={language: "\n".join(value).strip() for language, value in translations.items()},
                examples=["\n".join(value).strip() for value in examples if "\n".join(value).strip()],
            )
        )
        entry_spans.append((char_start, char_end))

    return ParseResult(entries, warnings, entry_spans)


def parse_log_file(path: str | os.PathLike[str]) -> ParseResult:
    try:
        source_bytes = Path(path).read_bytes()
        text = source_bytes.decode("utf-8-sig")
        result = parse_log_text(text)
        result.source_digest = hashlib.sha256(source_bytes).hexdigest()
        return result
    except (OSError, UnicodeError) as exc:
        return ParseResult([], [f"Could not read the selected log: {exc}"])


def delete_log_entry(
    path: str | os.PathLike[str],
    span: tuple[int, int],
    expected_digest: str,
) -> None:
    """Delete one parsed record, refusing to overwrite a log changed since loading."""
    source_path = Path(path)
    original_bytes = source_path.read_bytes()
    if hashlib.sha256(original_bytes).hexdigest() != expected_digest:
        raise RuntimeError("The log changed after it was loaded. Refresh it before deleting an entry.")

    text = original_bytes.decode("utf-8-sig")
    start, end = span
    if start < 0 or end <= start or end > len(text):
        raise ValueError("The selected record no longer has a valid source range.")

    bom_length = 3 if original_bytes.startswith(b"\xef\xbb\xbf") else 0
    byte_start = bom_length + len(text[:start].encode("utf-8"))
    byte_end = bom_length + len(text[:end].encode("utf-8"))
    updated_bytes = original_bytes[:byte_start] + original_bytes[byte_end:]

    current_bytes = source_path.read_bytes()
    if hashlib.sha256(current_bytes).hexdigest() != expected_digest:
        raise RuntimeError("The log changed during deletion. Refresh it before trying again.")
    source_path.write_bytes(updated_bytes)


def _log_identity(path: str | os.PathLike[str]) -> str:
    canonical_path = os.path.normcase(os.path.realpath(os.fspath(path)))
    return hashlib.sha256(canonical_path.encode("utf-8")).hexdigest()


def _entry_keys(entries: Iterable[TranslationEntry]) -> list[str]:
    duplicate_counts: dict[str, int] = {}
    keys: list[str] = []
    for entry in entries:
        content_key = entry.stable_key(0)
        duplicate_index = duplicate_counts.get(content_key, 0)
        duplicate_counts[content_key] = duplicate_index + 1
        keys.append(entry.stable_key(duplicate_index))
    return keys


class ScoreStore:
    """Store score metadata only, keyed by a hash of log path and entry content."""

    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)

    def load(self, log_path: str | os.PathLike[str], entries: list[TranslationEntry]) -> dict[str, int]:
        try:
            with self.path.open("r", encoding="utf-8") as store_file:
                data = json.load(store_file)
        except FileNotFoundError:
            return {}
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}

        log_scores = data.get("logs", {}).get(_log_identity(log_path), {})
        if not isinstance(log_scores, dict):
            return {}
        keys = _entry_keys(entries)
        return {
            key: int(log_scores[key])
            for key in keys
            if key in log_scores and str(log_scores[key]).isdigit() and 1 <= int(log_scores[key]) <= 5
        }

    def save(
        self,
        log_path: str | os.PathLike[str],
        scores: dict[str, int],
        entry_keys: Iterable[str] | None = None,
    ) -> None:
        try:
            with self.path.open("r", encoding="utf-8") as store_file:
                data = json.load(store_file)
        except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
            data = {"version": 1, "logs": {}}

        if not isinstance(data, dict) or not isinstance(data.get("logs"), dict):
            data = {"version": 1, "logs": {}}
        safe_scores = {key: score for key, score in scores.items() if isinstance(score, int) and 1 <= score <= 5}
        identity = _log_identity(log_path)
        previous_scores = data["logs"].get(identity, {})
        if not isinstance(previous_scores, dict):
            previous_scores = {}
        merged_scores = dict(previous_scores)
        for key in entry_keys or ():
            if key not in safe_scores:
                merged_scores.pop(key, None)
        merged_scores.update(safe_scores)
        data["logs"][identity] = merged_scores

        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent, delete=False) as temporary_file:
                temporary_path = temporary_file.name
                json.dump(data, temporary_file, ensure_ascii=False, indent=2)
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path and os.path.exists(temporary_path):
                os.unlink(temporary_path)


def export_entries(
    path: str | os.PathLike[str],
    entries: list[TranslationEntry],
    scores: dict[str, int],
    fields: list[tuple[str, str]],
    entry_keys: list[str] | None = None,
) -> None:
    """Export selected fields and scores as a UTF-8 CSV file."""
    keys = entry_keys if entry_keys is not None else _entry_keys(entries)
    if len(keys) != len(entries):
        raise ValueError("Entry key count must match entry count.")
    with open(path, "w", encoding="utf-8-sig", newline="") as output_file:
        writer = csv.writer(output_file)
        writer.writerow([label for _, label in fields] + ["Score"])
        for entry, key in zip(entries, keys):
            row: list[str] = []
            for field_name, _ in fields:
                if field_name == "original":
                    row.append(entry.original)
                elif field_name == "timestamp":
                    row.append(entry.timestamp.strftime("%Y-%m-%d %H:%M:%S"))
                elif field_name == "examples":
                    examples = [" ".join(example.split()) for example in entry.examples if example.strip()]
                    row.append(" | ".join(examples))
                elif field_name.startswith("translation:"):
                    row.append(entry.translations.get(field_name.split(":", 1)[1], ""))
            row.append(str(scores[key]) if key in scores else "")
            writer.writerow(row)


class LearningWindow(QMainWindow):
    def __init__(self, settings_path: str | os.PathLike[str] | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Language Helper - Learning")
        self.resize(1050, 760)
        self._settings_ready = False
        self.log_path: str | None = None
        self.entries: list[TranslationEntry] = []
        self.scores: dict[str, int] = {}
        self.entry_keys: list[str] = []
        self.entry_spans: list[tuple[int, int]] = []
        self.log_digest: str | None = None
        self.filtered_entries: list[TranslationEntry] = []
        self.filtered_keys: list[str] = []
        self.filtered_spans: list[tuple[int, int]] = []
        self.current_index = 0
        self.revealed = False
        self.study_font_size = 14
        self._session_deadline: datetime | None = None
        self._session_expired = False
        app_data = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
        app_data_path = Path(app_data) if app_data else Path.home() / ".language-helper"
        self.score_store = ScoreStore(app_data_path / "learning-scores.json")
        self.settings = QSettings(
            os.fspath(settings_path or app_data_path / "learning-settings.ini"),
            QSettings.Format.IniFormat,
        )
        self.field_checks: dict[str, QCheckBox] = {}
        self.session_timer = QTimer(self)
        self.session_timer.setInterval(1000)
        self.session_timer.timeout.connect(self._update_session_timer)

        self._build_ui()
        self._restore_settings()
        self._settings_ready = True
        app = QApplication.instance()
        if app:
            app.installEventFilter(self)
        self._update_controls()
        last_log_path = str(self.settings.value("general/last_log_path", ""))
        if last_log_path and Path(last_log_path).is_file():
            self.load_log(last_log_path)

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(14, 14, 14, 14)

        file_row = QHBoxLayout()
        self.path_label = QLabel("No log loaded")
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.open_button = QPushButton("Open log…")
        self.open_button.clicked.connect(self.open_log)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh_log)
        self.export_button = QPushButton("Export CSV…")
        self.export_button.clicked.connect(self.export_current)
        self.delete_button = QPushButton("Delete selected…")
        self.delete_button.clicked.connect(self.delete_current_entry)
        file_row.addWidget(self.path_label, 1)
        file_row.addWidget(self.open_button)
        file_row.addWidget(self.refresh_button)
        file_row.addWidget(self.export_button)
        file_row.addWidget(self.delete_button)
        root_layout.addLayout(file_row)

        self.preview_label = QLabel("Choose a translation log to begin.")
        root_layout.addWidget(self.preview_label)

        filters_box = QGroupBox("Study filters")
        filters_layout = QGridLayout(filters_box)
        self.use_dates = QCheckBox("Date range")
        self.start_date = QDateEdit(calendarPopup=True)
        self.end_date = QDateEdit(calendarPopup=True)
        today = QDate.currentDate()
        self.start_date.setDate(QDate(today.year(), 1, 1))
        self.end_date.setDate(today)
        self.category = QComboBox()
        self.category.addItems(["All", "Words", "Phrases", "Sentences (length-based)"])
        self.phrase_max = QSpinBox()
        self.phrase_max.setRange(2, 50)
        self.phrase_max.setValue(4)
        self.phrase_max.setSuffix(" words max")
        self.minimum_score = QSpinBox()
        self.minimum_score.setRange(1, 5)
        self.minimum_score.setValue(1)
        self.maximum_score = QSpinBox()
        self.maximum_score.setRange(1, 5)
        self.maximum_score.setValue(5)
        self.include_unrated = QCheckBox("Include unrated")
        self.include_unrated.setChecked(True)
        self.maximum_items = QSpinBox()
        self.maximum_items.setRange(0, 100000)
        self.maximum_items.setSpecialValueText("No limit")
        self.duration_minutes = QSpinBox()
        self.duration_minutes.setRange(0, 1440)
        self.duration_minutes.setSpecialValueText("No timer")
        self.duration_minutes.setSuffix(" min")
        self.shuffle_button = QPushButton("Shuffle study")
        self.shuffle_button.clicked.connect(self.shuffle_study)

        filters_layout.addWidget(self.use_dates, 0, 0)
        filters_layout.addWidget(QLabel("From"), 0, 1)
        filters_layout.addWidget(self.start_date, 0, 2)
        filters_layout.addWidget(QLabel("To"), 0, 3)
        filters_layout.addWidget(self.end_date, 0, 4)
        filters_layout.addWidget(QLabel("Entry type"), 1, 0)
        filters_layout.addWidget(self.category, 1, 1)
        filters_layout.addWidget(self.phrase_max, 1, 2)
        filters_layout.addWidget(QLabel("Score"), 1, 3)
        score_row = QWidget()
        score_layout = QHBoxLayout(score_row)
        score_layout.setContentsMargins(0, 0, 0, 0)
        score_layout.addWidget(self.minimum_score)
        score_layout.addWidget(QLabel("to"))
        score_layout.addWidget(self.maximum_score)
        score_layout.addWidget(self.include_unrated)
        filters_layout.addWidget(score_row, 1, 4, 1, 2)
        filters_layout.addWidget(QLabel("Maximum items"), 2, 0)
        filters_layout.addWidget(self.maximum_items, 2, 1)
        filters_layout.addWidget(QLabel("Session duration"), 2, 2)
        filters_layout.addWidget(self.duration_minutes, 2, 3)
        filters_layout.addWidget(self.shuffle_button, 2, 4)
        root_layout.addWidget(filters_box)

        fields_box = QGroupBox("Fields to display and export")
        self.fields_layout = QHBoxLayout(fields_box)
        self.fields_layout.addWidget(QLabel("Load a log to choose available fields."))
        root_layout.addWidget(fields_box)

        self.tabs = QTabWidget()
        self.study_page = self._build_study_tab()
        self.tabs.addTab(self.study_page, "Study")
        self.tabs.addTab(self._build_list_tab(), "List")
        root_layout.addWidget(self.tabs, 1)

        self.status_label = QLabel("")
        root_layout.addWidget(self.status_label)
        self.setCentralWidget(root)

        self.use_dates.stateChanged.connect(self.apply_filters)
        self.use_dates.stateChanged.connect(self._update_controls)
        self.category.currentIndexChanged.connect(self.apply_filters)
        self.category.currentIndexChanged.connect(self._update_controls)
        self.phrase_max.valueChanged.connect(self.apply_filters)
        self.minimum_score.valueChanged.connect(self.apply_filters)
        self.maximum_score.valueChanged.connect(self.apply_filters)
        self.include_unrated.stateChanged.connect(self.apply_filters)
        self.maximum_items.valueChanged.connect(self.apply_filters)
        self.duration_minutes.valueChanged.connect(self._update_controls)
        self.start_date.dateChanged.connect(self.apply_filters)
        self.end_date.dateChanged.connect(self.apply_filters)

        QShortcut(QKeySequence(Qt.Key.Key_Left), self).activated.connect(self.previous_entry)
        QShortcut(QKeySequence(Qt.Key.Key_Right), self).activated.connect(self.next_entry)
        self._apply_study_font()

        for signal in (
            self.use_dates.stateChanged,
            self.category.currentIndexChanged,
            self.phrase_max.valueChanged,
            self.minimum_score.valueChanged,
            self.maximum_score.valueChanged,
            self.include_unrated.stateChanged,
            self.maximum_items.valueChanged,
            self.duration_minutes.valueChanged,
            self.start_date.dateChanged,
            self.end_date.dateChanged,
            self.tabs.currentChanged,
        ):
            signal.connect(self._save_settings)

    def _restore_settings(self) -> None:
        self.use_dates.setChecked(self.settings.value("filters/use_dates", False, type=bool))
        self.category.setCurrentText(str(self.settings.value("filters/category", "All")))
        self.phrase_max.setValue(self.settings.value("filters/phrase_max", 4, type=int))
        self.minimum_score.setValue(self.settings.value("filters/minimum_score", 1, type=int))
        self.maximum_score.setValue(self.settings.value("filters/maximum_score", 5, type=int))
        self.include_unrated.setChecked(self.settings.value("filters/include_unrated", True, type=bool))
        self.maximum_items.setValue(self.settings.value("filters/maximum_items", 0, type=int))
        self.duration_minutes.setValue(self.settings.value("filters/duration_minutes", 0, type=int))
        self.study_font_size = max(8, min(40, self.settings.value("display/font_size", 14, type=int)))
        self.tabs.setCurrentIndex(max(0, min(1, self.settings.value("window/current_tab", 0, type=int))))

        for key, control in (
            ("filters/start_date", self.start_date),
            ("filters/end_date", self.end_date),
        ):
            parsed_date = QDate.fromString(str(self.settings.value(key, "")), Qt.DateFormat.ISODate)
            if parsed_date.isValid():
                control.setDate(parsed_date)

        saved_geometry = str(self.settings.value("window/geometry", ""))
        if saved_geometry:
            self.restoreGeometry(QByteArray.fromHex(saved_geometry.encode("ascii")))
        self._apply_study_font()

    def _save_settings(self, *_args: object) -> None:
        if not self._settings_ready:
            return
        self.settings.setValue("filters/use_dates", self.use_dates.isChecked())
        self.settings.setValue("filters/category", self.category.currentText())
        self.settings.setValue("filters/phrase_max", self.phrase_max.value())
        self.settings.setValue("filters/minimum_score", self.minimum_score.value())
        self.settings.setValue("filters/maximum_score", self.maximum_score.value())
        self.settings.setValue("filters/include_unrated", self.include_unrated.isChecked())
        self.settings.setValue("filters/maximum_items", self.maximum_items.value())
        self.settings.setValue("filters/duration_minutes", self.duration_minutes.value())
        self.settings.setValue("filters/start_date", self.start_date.date().toString(Qt.DateFormat.ISODate))
        self.settings.setValue("filters/end_date", self.end_date.date().toString(Qt.DateFormat.ISODate))
        self.settings.setValue("display/font_size", self.study_font_size)
        self.settings.setValue("window/current_tab", self.tabs.currentIndex())
        if self.log_path:
            self.settings.setValue("general/last_log_path", self.log_path)
        if self.field_checks:
            self.settings.setValue("display/fields", json.dumps([name for name, _ in self._selected_fields()]))
        self.settings.sync()

    def closeEvent(self, event: object) -> None:
        if self._settings_ready:
            self.settings.setValue("window/geometry", bytes(self.saveGeometry().toHex()).decode("ascii"))
            self._save_settings()
        app = QApplication.instance()
        if app:
            app.removeEventFilter(self)
        super().closeEvent(event)

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if (
            isinstance(event, QKeyEvent)
            and event.type() == QEvent.Type.KeyPress
            and self.isActiveWindow()
            and self.tabs.currentWidget() is self.study_page
        ):
            control_down = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            if control_down and event.key() in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
                self.increase_study_font()
                return True
            if control_down and event.key() in (Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
                self.decrease_study_font()
                return True
            if event.key() == Qt.Key.Key_Space and not control_down:
                self.toggle_reveal()
                return True
            if not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                score_by_key = {
                    Qt.Key.Key_1: 1,
                    Qt.Key.Key_2: 2,
                    Qt.Key.Key_3: 3,
                    Qt.Key.Key_4: 4,
                    Qt.Key.Key_5: 5,
                }
                score = score_by_key.get(Qt.Key(event.key()))
                if score is not None:
                    self.set_score(score)
                    return True
        return super().eventFilter(watched, event)

    def _apply_study_font(self) -> None:
        self.study_page.setStyleSheet(f"font-size: {self.study_font_size}pt;")

    def increase_study_font(self) -> None:
        self.study_font_size = min(40, self.study_font_size + 1)
        self._apply_study_font()
        self._save_settings()

    def decrease_study_font(self) -> None:
        self.study_font_size = max(8, self.study_font_size - 1)
        self._apply_study_font()
        self._save_settings()

    def _build_study_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.study_counter = QLabel("No entries")
        self.study_counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.study_counter)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.study_content = QWidget()
        self.study_content_layout = QVBoxLayout(self.study_content)
        self.study_content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self.study_content)
        layout.addWidget(scroll, 1)

        self.reveal_button = QPushButton("Reveal translations")
        self.reveal_button.clicked.connect(self.toggle_reveal)
        layout.addWidget(self.reveal_button)

        score_group = QGroupBox("Memory score")
        score_layout = QHBoxLayout(score_group)
        self.score_buttons: dict[int, QPushButton] = {}
        for score in range(1, 6):
            button = QPushButton(str(score))
            button.setCheckable(True)
            meanings = {
                1: "Forgot it",
                2: "Very difficult",
                3: "Some effort",
                4: "Remembered well",
                5: "Easy to remember",
            }
            button.setToolTip(f"{score}: {meanings[score]}")
            button.clicked.connect(lambda checked=False, value=score: self.set_score(value))
            self.score_buttons[score] = button
            score_layout.addWidget(button)
        self.clear_score_button = QPushButton("Unrated")
        self.clear_score_button.clicked.connect(lambda: self.set_score(None))
        score_layout.addWidget(self.clear_score_button)
        layout.addWidget(score_group)

        navigation = QHBoxLayout()
        self.previous_button = QPushButton("Previous")
        self.previous_button.clicked.connect(self.previous_entry)
        self.next_button = QPushButton("Next")
        self.next_button.clicked.connect(self.next_entry)
        self.session_button = QPushButton("Start timed session")
        self.session_button.clicked.connect(self.start_session)
        navigation.addWidget(self.previous_button)
        navigation.addWidget(self.session_button)
        navigation.addWidget(self.next_button)
        layout.addLayout(navigation)
        return page

    def _build_list_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.list_table = QTableWidget()
        self.list_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.list_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.list_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.list_table.cellClicked.connect(self.select_list_entry)
        layout.addWidget(self.list_table)
        return page

    def open_log(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select translation log", str(Path.home()), "Log files (*.log *.txt);;All files (*)"
        )
        if path:
            self.load_log(path)

    def load_log(self, path: str) -> None:
        result = parse_log_file(path)
        if not result.entries and result.warnings:
            QMessageBox.warning(self, "No entries loaded", "\n".join(result.warnings) or "No records were found.")
            return

        self.session_timer.stop()
        self._session_deadline = None
        self._session_expired = False
        self.session_button.setText("Start timed session")
        self.log_path = path
        self.entries = result.entries
        self.entry_spans = result.entry_spans
        self.log_digest = result.source_digest
        self.entry_keys = _entry_keys(self.entries)
        self.scores = self.score_store.load(path, self.entries)
        self.path_label.setText(path)
        self.path_label.setToolTip(path)
        self._rebuild_field_choices()
        message = f"Loaded {len(self.entries)} entries."
        if result.warnings:
            message += f" {len(result.warnings)} parser warning(s); hover for details."
            self.preview_label.setToolTip("\n".join(result.warnings))
        else:
            self.preview_label.setToolTip("")
        self.preview_label.setText(message)
        self.status_label.setText("Scores are saved separately on this computer.")
        self.current_index = 0
        self.apply_filters()
        self._save_settings()

    def refresh_log(self) -> None:
        if self.log_path:
            self.load_log(self.log_path)

    def _rebuild_field_choices(self) -> None:
        while self.fields_layout.count():
            item = self.fields_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.field_checks.clear()

        saved_fields_value = self.settings.value("display/fields", None)
        saved_fields: set[str] | None = None
        if saved_fields_value is not None:
            try:
                saved_fields = set(json.loads(str(saved_fields_value)))
            except (TypeError, json.JSONDecodeError):
                saved_fields = set()

        self._add_field_checkbox("original", "Original", True, saved_fields)
        target_languages = list(dict.fromkeys(language for entry in self.entries for language in entry.translations))
        for language in target_languages:
            self._add_field_checkbox(f"translation:{language}", f"{language} translation", True, saved_fields)
        if any(entry.examples for entry in self.entries):
            self._add_field_checkbox("examples", "Examples", True, saved_fields)
        self._add_field_checkbox("timestamp", "Timestamp", False, saved_fields)
        self.fields_layout.addStretch(1)
        for checkbox in self.field_checks.values():
            checkbox.stateChanged.connect(self._fields_changed)

    def _add_field_checkbox(
        self,
        name: str,
        label: str,
        checked: bool,
        saved_fields: set[str] | None = None,
    ) -> None:
        if saved_fields is not None:
            checked = name in saved_fields
        checkbox = QCheckBox(label)
        checkbox.setChecked(checked)
        self.field_checks[name] = checkbox
        self.fields_layout.addWidget(checkbox)

    def _selected_fields(self) -> list[tuple[str, str]]:
        return [(name, checkbox.text()) for name, checkbox in self.field_checks.items() if checkbox.isChecked()]

    def _fields_changed(self) -> None:
        self._render_study_entry()
        self._render_list()
        self._save_settings()

    def apply_filters(self, *_args: object) -> None:
        if not self.entries:
            self.filtered_entries = []
            self.filtered_keys = []
            self.filtered_spans = []
            self.current_index = 0
            self._render_study_entry()
            self._render_list()
            self._update_controls()
            self.preview_label.setText("Loaded 0 entries; no entries are available to study.")
            return

        minimum = self.minimum_score.value()
        maximum = self.maximum_score.value()
        selected: list[tuple[TranslationEntry, str, tuple[int, int]]] = []
        for entry, key, span in zip(self.entries, self.entry_keys, self.entry_spans):
            score = self.scores.get(key)
            if score is None:
                if not self.include_unrated.isChecked():
                    continue
            elif not minimum <= score <= maximum:
                continue

            if self.use_dates.isChecked():
                start = self.start_date.date().toPython()
                end = self.end_date.date().toPython()
                if not start <= entry.timestamp.date() <= end:
                    continue

            word_count = len(entry.original.split())
            threshold = self.phrase_max.value()
            category = self.category.currentText()
            if category == "Words" and word_count != 1:
                continue
            if category == "Phrases" and not 2 <= word_count <= threshold:
                continue
            if category == "Sentences (length-based)" and word_count <= threshold:
                continue
            selected.append((entry, key, span))

        limit = self.maximum_items.value()
        if limit:
            selected = selected[:limit]
        self.filtered_entries = [entry for entry, _, _ in selected]
        self.filtered_keys = [key for _, key, _ in selected]
        self.filtered_spans = [span for _, _, span in selected]
        self.current_index = min(self.current_index, max(0, len(self.filtered_entries) - 1))
        self.revealed = False
        self._render_study_entry()
        self._render_list()
        self._update_controls()
        self.preview_label.setText(
            f"Loaded {len(self.entries)} entries; {len(self.filtered_entries)} match the current filters."
        )

    def _update_controls(self, *_args: object) -> None:
        has_entries = bool(self.filtered_entries)
        study_enabled = has_entries and not self._session_expired
        self.refresh_button.setEnabled(bool(self.log_path))
        self.export_button.setEnabled(has_entries)
        self.delete_button.setEnabled(has_entries and bool(self.log_path) and self.log_digest is not None)
        self.start_date.setEnabled(self.use_dates.isChecked())
        self.end_date.setEnabled(self.use_dates.isChecked())
        self.phrase_max.setEnabled(self.category.currentText() != "All")
        self.previous_button.setEnabled(study_enabled)
        self.next_button.setEnabled(study_enabled)
        has_translations = any(name.startswith("translation:") for name, _ in self._selected_fields())
        self.reveal_button.setEnabled(study_enabled and has_translations)
        for button in self.score_buttons.values():
            button.setEnabled(study_enabled)
        self.clear_score_button.setEnabled(study_enabled)
        self.list_table.setEnabled(has_entries and not self._session_expired)
        self.session_button.setEnabled(has_entries and self.duration_minutes.value() > 0)
        self.shuffle_button.setEnabled(has_entries and not self._session_expired)

    def _clear_study_content(self) -> None:
        while self.study_content_layout.count():
            item = self.study_content_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _render_study_entry(self) -> None:
        self._clear_study_content()
        if not self.filtered_entries:
            self.study_counter.setText("No entries match these filters")
            self.reveal_button.setText("Reveal translations")
            for button in self.score_buttons.values():
                button.setChecked(False)
            return

        self.current_index = max(0, min(self.current_index, len(self.filtered_entries) - 1))
        entry = self.filtered_entries[self.current_index]
        key = self.filtered_keys[self.current_index]
        self.study_counter.setText(f"{self.current_index + 1} / {len(self.filtered_entries)}")
        self.reveal_button.setText("Hide translations" if self.revealed else "Reveal translations")

        for field_name, label in self._selected_fields():
            if field_name.startswith("translation:") and not self.revealed:
                continue
            if field_name == "original":
                value = entry.original
            elif field_name == "timestamp":
                value = entry.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            elif field_name == "examples":
                value = "\n\n".join(entry.examples)
            elif field_name.startswith("translation:"):
                language = field_name.split(":", 1)[1]
                value = entry.translations.get(language, "")
            else:
                continue
            if not value:
                continue

            field_box = QGroupBox(label)
            field_layout = QVBoxLayout(field_box)
            value_label = QLabel(value)
            value_label.setWordWrap(True)
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value_label.setMinimumHeight(36)
            field_layout.addWidget(value_label)
            self.study_content_layout.addWidget(field_box)

        current_score = self.scores.get(key)
        for score, button in self.score_buttons.items():
            button.setChecked(current_score == score)
        self._render_list_selection()

    def _render_list(self) -> None:
        fields = self._selected_fields()
        headers = [label for _, label in fields] + ["Score"]
        self.list_table.clear()
        self.list_table.setColumnCount(len(headers))
        self.list_table.setHorizontalHeaderLabels(headers)
        self.list_table.setRowCount(len(self.filtered_entries))
        for row, (entry, key) in enumerate(zip(self.filtered_entries, self.filtered_keys)):
            values: list[str] = []
            for field_name, _ in fields:
                if field_name == "original":
                    values.append(entry.original)
                elif field_name == "timestamp":
                    values.append(entry.timestamp.strftime("%Y-%m-%d %H:%M:%S"))
                elif field_name == "examples":
                    values.append("\n".join(entry.examples))
                elif field_name.startswith("translation:"):
                    language = field_name.split(":", 1)[1]
                    values.append(entry.translations.get(language, ""))
            values.append(str(self.scores[key]) if key in self.scores else "")
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.list_table.setItem(row, column, item)
        self.list_table.resizeColumnsToContents()
        self.list_table.resizeRowsToContents()
        self._render_list_selection()

    def _render_list_selection(self) -> None:
        if 0 <= self.current_index < self.list_table.rowCount():
            self.list_table.selectRow(self.current_index)

    def select_list_entry(self, row: int, _column: int) -> None:
        if not self._session_expired and 0 <= row < len(self.filtered_entries):
            self.current_index = row
            self.revealed = False
            self.tabs.setCurrentIndex(0)
            self._render_study_entry()

    def previous_entry(self) -> None:
        if self.filtered_entries and not self._session_expired:
            self.current_index = (self.current_index - 1) % len(self.filtered_entries)
            self.revealed = False
            self._render_study_entry()

    def next_entry(self) -> None:
        if self.filtered_entries and not self._session_expired:
            self.current_index = (self.current_index + 1) % len(self.filtered_entries)
            self.revealed = False
            self._render_study_entry()

    def toggle_reveal(self) -> None:
        if not self.filtered_entries or self._session_expired:
            return
        self.revealed = not self.revealed
        self._render_study_entry()

    def set_score(self, score: int | None) -> None:
        if not self.filtered_entries or not self.log_path or self._session_expired:
            return
        key = self.filtered_keys[self.current_index]
        if score is None:
            self.scores.pop(key, None)
        else:
            self.scores[key] = score
        try:
            self.score_store.save(self.log_path, self.scores, self.entry_keys)
            self.status_label.setText("Score saved separately from the selected log.")
        except OSError as exc:
            QMessageBox.warning(self, "Score not saved", f"Could not save score metadata:\n{exc}")
        self.apply_filters()

    def delete_current_entry(self) -> None:
        if not self.filtered_entries or not self.log_path or self.log_digest is None:
            return

        answer = QMessageBox.question(
            self,
            "Confirm log deletion",
            f"Delete the selected entry from {Path(self.log_path).name}? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            delete_log_entry(
                self.log_path,
                self.filtered_spans[self.current_index],
                self.log_digest,
            )
        except (OSError, UnicodeError, RuntimeError, ValueError) as exc:
            QMessageBox.warning(self, "Entry not deleted", str(exc))
            return

        deleted_entry = self.filtered_entries[self.current_index].original
        self.load_log(self.log_path)
        self.status_label.setText(f"Deleted entry: {deleted_entry[:100]}")

    def shuffle_study(self) -> None:
        if not self.filtered_entries or self._session_expired:
            return
        combined = list(zip(self.filtered_entries, self.filtered_keys, self.filtered_spans))
        random.shuffle(combined)
        self.filtered_entries = [entry for entry, _, _ in combined]
        self.filtered_keys = [key for _, key, _ in combined]
        self.filtered_spans = [span for _, _, span in combined]
        self.current_index = 0
        self.revealed = False
        self._render_study_entry()
        self._render_list()
        self.status_label.setText("Study order shuffled.")

    def start_session(self) -> None:
        if self.session_timer.isActive():
            self.session_timer.stop()
            self._session_deadline = None
            self._session_expired = False
            self.session_button.setText("Start timed session")
            self.status_label.setText("Timed session stopped.")
            self._update_controls()
            return
        minutes = self.duration_minutes.value()
        if minutes <= 0:
            return
        self._session_deadline = datetime.now() + timedelta(minutes=minutes)
        self._session_expired = False
        self._update_controls()
        self.session_timer.start()
        self._update_session_timer()
        self.status_label.setText("Timed session started. It will not advance cards automatically.")

    def _update_session_timer(self) -> None:
        if self._session_deadline is None:
            return
        remaining = int((self._session_deadline - datetime.now()).total_seconds() + 0.999)
        if remaining <= 0:
            self.session_timer.stop()
            self._session_deadline = None
            self._session_expired = True
            self.session_button.setText("Start new session")
            self.status_label.setText("Timed session ended.")
            self._update_controls()
            return
        self.session_button.setText(f"End session ({remaining // 60}:{remaining % 60:02d})")

    def export_current(self) -> None:
        if not self.filtered_entries:
            return
        default_name = str(Path(self.log_path or "translations.log").with_suffix(".csv"))
        path, _ = QFileDialog.getSaveFileName(self, "Export study list", default_name, "CSV files (*.csv)")
        if not path:
            return
        try:
            export_entries(
                path,
                self.filtered_entries,
                self.scores,
                self._selected_fields(),
                self.filtered_keys,
            )
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", f"Could not write the CSV file:\n{exc}")
            return
        self.status_label.setText(f"Exported {len(self.filtered_entries)} entries to {path}.")


def main() -> int:
    app = QApplication(sys.argv)
    app.setOrganizationName("LanguageHelper")
    app.setApplicationName("LanguageHelperLearning")
    window = LearningWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())