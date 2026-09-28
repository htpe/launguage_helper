import csv
import hashlib
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QDate, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QGroupBox, QMessageBox

from learning_gui import (
    LearningWindow,
    ScoreStore,
    _entry_keys,
    delete_log_entry,
    export_entries,
    parse_log_file,
    parse_log_text,
)


SYNTHETIC_LOG = """[2026-08-14 09:12:33]  (de → fr, es)
  Original : Guten Morgen
  fr       : Bonjour
  es       : Buenos días
  Examples :
    1. Guten Morgen, wie geht es dir?
       Mir geht es gut.
[2026-08-14 09:12:34]  (de → fr, es)
  Original : Ich lerne Deutsch.
  fr       : J'apprends l'allemand.
  es       : Estoy aprendiendo alemán.
"""


class ParseLogTests(unittest.TestCase):
    def test_parses_adjacent_records_translations_and_examples(self):
        result = parse_log_text(SYNTHETIC_LOG)

        self.assertEqual(len(result.entries), 2)
        self.assertEqual(result.entries[0].original, "Guten Morgen")
        self.assertEqual(result.entries[0].translations["fr"], "Bonjour")
        self.assertEqual(result.entries[0].translations["es"], "Buenos días")
        self.assertEqual(result.entries[0].examples, ["Guten Morgen, wie geht es dir?\nMir geht es gut."])
        self.assertEqual(result.entries[1].original, "Ich lerne Deutsch.")

    def test_keeps_multiline_original_and_translation(self):
        text = """[2026-08-14 09:12:33]  (de → fr)
  Original : Erste Zeile
Zweite Zeile
  fr       : Première ligne
Deuxième ligne
"""
        result = parse_log_text(text)

        self.assertEqual(result.entries[0].original, "Erste Zeile\nZweite Zeile")
        self.assertEqual(result.entries[0].translations["fr"], "Première ligne\nDeuxième ligne")

    def test_reports_malformed_and_incomplete_records(self):
        text = """[2026-08-14 09:12:33]  (de → fr)
  fr       : Bonjour
[2026-02-30 09:12:33]  (de → fr)
"""
        result = parse_log_text(text)

        self.assertEqual(result.entries, [])
        self.assertTrue(any("no usable Original" in warning for warning in result.warnings))
        self.assertTrue(any("unrecognized" in warning for warning in result.warnings))

    def test_identical_records_receive_distinct_score_keys(self):
        text = SYNTHETIC_LOG.replace("09:12:34", "09:12:33").replace(
            "Ich lerne Deutsch.", "Guten Morgen"
        ).replace("J'apprends l'allemand.", "Bonjour").replace("Estoy aprendiendo alemán.", "Buenos días")
        result = parse_log_text(text)
        keys = _entry_keys(result.entries)

        self.assertNotEqual(keys[0], keys[1])

    def test_delete_removes_one_record_and_preserves_bom_and_crlf(self):
        text = SYNTHETIC_LOG.replace("\n", "\r\n")
        original_bytes = b"\xef\xbb\xbf" + text.encode("utf-8")
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "translations.log"
            log_path.write_bytes(original_bytes)
            result = parse_log_file(log_path)

            delete_log_entry(
                log_path,
                result.entry_spans[0],
                result.source_digest,
            )

            updated_bytes = log_path.read_bytes()

        self.assertTrue(updated_bytes.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(updated_bytes, b"\xef\xbb\xbf" + text[result.entry_spans[0][1] :].encode("utf-8"))
        self.assertNotIn(b"Guten Morgen", updated_bytes)
        self.assertIn("Ich lerne Deutsch.".encode("utf-8"), updated_bytes)

    def test_delete_refuses_log_changed_since_parse(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "translations.log"
            log_path.write_text(SYNTHETIC_LOG, encoding="utf-8")
            result = parse_log_file(log_path)
            log_path.write_text(SYNTHETIC_LOG + "external append\n", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "changed after it was loaded"):
                delete_log_entry(log_path, result.entry_spans[0], result.source_digest)

            self.assertTrue(log_path.read_text(encoding="utf-8").endswith("external append\n"))


class ScoreStoreAndExportTests(unittest.TestCase):
    def test_score_round_trip_does_not_modify_log(self):
        result = parse_log_text(SYNTHETIC_LOG)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log_path = root / "translations.log"
            log_path.write_text(SYNTHETIC_LOG, encoding="utf-8")
            original_log = log_path.read_bytes()
            store = ScoreStore(root / "app-data" / "scores.json")
            keys = _entry_keys(result.entries)

            store.save(log_path, {keys[0]: 4})

            self.assertEqual(store.load(log_path, result.entries), {keys[0]: 4})
            self.assertEqual(log_path.read_bytes(), original_log)
            other_log = root / "other.log"
            other_log.write_text(SYNTHETIC_LOG, encoding="utf-8")
            self.assertEqual(store.load(other_log, result.entries), {})

    def test_sidecar_preserves_scores_for_temporarily_missing_entries(self):
        entries = parse_log_text(SYNTHETIC_LOG).entries
        keys = _entry_keys(entries)
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "translations.log"
            store = ScoreStore(Path(directory) / "scores.json")

            store.save(log_path, {keys[0]: 4}, [keys[0]])
            store.save(log_path, {keys[1]: 2}, [keys[1]])
            self.assertEqual(store.load(log_path, entries), {keys[0]: 4, keys[1]: 2})

            store.save(log_path, {keys[1]: 2}, keys)
            self.assertEqual(store.load(log_path, entries), {keys[1]: 2})

    def test_csv_flattens_and_quotes_examples_in_one_physical_row(self):
        result = parse_log_text(SYNTHETIC_LOG)
        result.entries[0].examples = [
            "Guten Morgen, wie geht es dir?\nMir geht es gut.",
            'He said "hello", then left.',
        ]
        keys = _entry_keys(result.entries)
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "export.csv"
            export_entries(
                output_path,
                result.entries[:1],
                {keys[0]: 5},
                [("original", "Original"), ("examples", "Examples")],
            )

            with output_path.open(encoding="utf-8-sig", newline="") as output_file:
                rows = list(csv.reader(output_file))
            physical_lines = output_path.read_text(encoding="utf-8-sig").splitlines()

        self.assertEqual(rows[0], ["Original", "Examples", "Score"])
        self.assertEqual(
            rows[1],
            [
                "Guten Morgen",
                'Guten Morgen, wie geht es dir? Mir geht es gut. | He said "hello", then left.',
                "5",
            ],
        )
        self.assertEqual(len(physical_lines), 2)
        self.assertIn('"Guten Morgen, wie geht es dir?', physical_lines[1])

        def test_csv_uses_entry_keys_after_duplicate_entries_are_shuffled(self):
                duplicate_log = """[2026-08-14 09:12:33]  (de → fr)
    Original : Hallo
    fr       : Salut
[2026-08-14 09:12:33]  (de → fr)
    Original : Hallo
    fr       : Salut
"""
                entries = parse_log_text(duplicate_log).entries
                keys = _entry_keys(entries)
                with tempfile.TemporaryDirectory() as directory:
                        output_path = Path(directory) / "export.csv"
                        export_entries(
                                output_path,
                                entries[::-1],
                                {keys[0]: 2, keys[1]: 5},
                                [("original", "Original")],
                                keys[::-1],
                        )
                        with output_path.open(encoding="utf-8-sig", newline="") as output_file:
                                rows = list(csv.reader(output_file))

                self.assertEqual([row[-1] for row in rows[1:]], ["5", "2"])


class LearningWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self, settings_path=None):
        if settings_path is None:
            temporary_directory = tempfile.TemporaryDirectory()
            self.addCleanup(temporary_directory.cleanup)
            settings_path = Path(temporary_directory.name) / "learning-settings.ini"
        window = LearningWindow(settings_path=settings_path)
        self.addCleanup(window.close)
        return window

    def test_study_reveal_navigation_list_and_timer(self):
        window = self.make_window()
        parsed = parse_log_text(SYNTHETIC_LOG)
        window.entries = parsed.entries
        window.entry_spans = parsed.entry_spans
        window.entry_keys = _entry_keys(window.entries)
        window._rebuild_field_choices()
        window.apply_filters()

        self.assertEqual(window.list_table.rowCount(), 2)
        group_titles = [group.title() for group in window.study_content.findChildren(QGroupBox)]
        self.assertNotIn("fr translation", group_titles)

        window.toggle_reveal()
        group_titles = [group.title() for group in window.study_content.findChildren(QGroupBox)]
        self.assertIn("fr translation", group_titles)
        window.next_entry()
        self.assertEqual(window.current_index, 1)

        window.duration_minutes.setValue(1)
        window.start_session()
        self.assertTrue(window.session_timer.isActive())
        window._session_deadline = datetime.now() - timedelta(seconds=1)
        window._update_session_timer()
        self.assertTrue(window._session_expired)
        self.assertFalse(window.next_button.isEnabled())
        window.apply_filters()
        self.assertFalse(window.next_button.isEnabled())
        window.start_session()
        self.assertTrue(window.next_button.isEnabled())
        self.assertTrue(window.session_timer.isActive())
        window.start_session()
        self.assertFalse(window.session_timer.isActive())

        window._session_expired = True
        window._update_controls()
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "translations.log"
            log_path.write_text(SYNTHETIC_LOG, encoding="utf-8")
            window.load_log(str(log_path))
        self.assertFalse(window._session_expired)
        self.assertTrue(window.next_button.isEnabled())
        window.close()

    def test_date_score_category_and_count_filters_combine(self):
        window = self.make_window()
        parsed = parse_log_text(SYNTHETIC_LOG)
        window.entries = parsed.entries
        window.entry_spans = parsed.entry_spans
        window.entry_keys = _entry_keys(window.entries)
        window.scores = {window.entry_keys[0]: 5, window.entry_keys[1]: 3}
        window._rebuild_field_choices()

        window.minimum_score.setValue(5)
        window.include_unrated.setChecked(False)
        window.category.setCurrentText("Phrases")
        window.phrase_max.setValue(2)
        window.use_dates.setChecked(True)
        window.start_date.setDate(QDate(2026, 8, 14))
        window.end_date.setDate(QDate(2026, 8, 14))
        window.maximum_items.setValue(1)

        self.assertEqual(window.filtered_entries, [window.entries[0]])

        window.category.setCurrentText("Sentences (length-based)")
        window.phrase_max.setValue(2)
        window.minimum_score.setValue(1)
        window.maximum_score.setValue(5)
        window.include_unrated.setChecked(True)
        window.maximum_items.setValue(0)

        self.assertEqual(window.filtered_entries, [window.entries[1]])
        window.close()

    def test_study_shortcuts_and_bounded_font_scaling(self):
        window = self.make_window()
        parsed = parse_log_text(SYNTHETIC_LOG)
        window.entries = parsed.entries
        window.entry_spans = parsed.entry_spans
        window.entry_keys = _entry_keys(window.entries)
        window._rebuild_field_choices()
        window.apply_filters()
        window.show()
        window.activateWindow()
        QTest.qWaitForWindowActive(window, 1000)

        start_size = window.study_font_size
        QTest.keyClick(
            window.next_button,
            Qt.Key.Key_Equal,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
        )
        self.assertEqual(window.study_font_size, start_size + 1)
        QTest.keyClick(window.next_button, Qt.Key.Key_Minus, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(window.study_font_size, start_size)

        QTest.keyClick(window.next_button, Qt.Key.Key_Space)
        self.assertTrue(window.revealed)
        QTest.keyClick(window.next_button, Qt.Key.Key_Space)
        self.assertFalse(window.revealed)

        window.tabs.setCurrentIndex(1)
        QTest.keyClick(
            window.list_table,
            Qt.Key.Key_Equal,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
        )
        self.assertEqual(window.study_font_size, start_size)
        self.assertFalse(window.revealed)

        window.tabs.setCurrentIndex(0)
        window.study_font_size = 40
        QTest.keyClick(
            window.next_button,
            Qt.Key.Key_Equal,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
        )
        self.assertEqual(window.study_font_size, 40)
        window.study_font_size = 8
        QTest.keyClick(window.next_button, Qt.Key.Key_Minus, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(window.study_font_size, 8)
        window.close()

    def test_digit_keys_set_memory_scores(self):
        window = self.make_window()
        parsed = parse_log_text(SYNTHETIC_LOG)
        window.entries = parsed.entries
        window.entry_spans = parsed.entry_spans
        window.entry_keys = _entry_keys(window.entries)
        window._rebuild_field_choices()
        window.apply_filters()
        window.show()
        window.activateWindow()
        QTest.qWaitForWindowActive(window, 1000)

        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "translations.log"
            log_path.write_text(SYNTHETIC_LOG, encoding="utf-8")
            window.log_path = str(log_path)
            window.score_store = ScoreStore(Path(directory) / "scores.json")

            for digit, score in zip("12345", range(1, 6)):
                QTest.keyClick(window.next_button, getattr(Qt.Key, f"Key_{digit}"))
                self.assertEqual(window.scores[window.filtered_keys[window.current_index]], score)

            self.assertEqual(window.score_store.load(log_path, window.entries)[window.entry_keys[0]], 5)
        window.close()

    def test_delete_selected_requires_confirmation_and_refreshes_log(self):
        window = self.make_window()
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "translations.log"
            log_path.write_text(SYNTHETIC_LOG, encoding="utf-8")
            window.score_store = ScoreStore(Path(directory) / "scores.json")
            window.load_log(str(log_path))
            original_log = log_path.read_text(encoding="utf-8")

            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No) as confirm:
                window.delete_current_entry()
            confirm.assert_called_once()
            self.assertEqual(log_path.read_text(encoding="utf-8"), original_log)

            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                window.delete_current_entry()

            remaining_log = log_path.read_text(encoding="utf-8")
            self.assertNotIn("Guten Morgen", remaining_log)
            self.assertIn("Ich lerne Deutsch.", remaining_log)
            self.assertEqual(len(window.entries), 1)
            self.assertEqual(window.entries[0].original, "Ich lerne Deutsch.")

    def test_delete_last_entry_leaves_empty_log_and_empty_view(self):
        window = self.make_window()
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "translations.log"
            log_path.write_text(SYNTHETIC_LOG.split("[2026-08-14 09:12:34]")[0], encoding="utf-8")
            window.score_store = ScoreStore(Path(directory) / "scores.json")
            window.load_log(str(log_path))

            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                window.delete_current_entry()

            self.assertEqual(log_path.read_text(encoding="utf-8"), "")
            self.assertEqual(window.entries, [])
            self.assertEqual(window.list_table.rowCount(), 0)
            self.assertFalse(window.delete_button.isEnabled())

    def test_delete_after_shuffle_targets_the_selected_record(self):
        window = self.make_window()
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "translations.log"
            log_path.write_text(SYNTHETIC_LOG, encoding="utf-8")
            window.score_store = ScoreStore(Path(directory) / "scores.json")
            window.load_log(str(log_path))

            with patch("learning_gui.random.shuffle", side_effect=lambda items: items.reverse()):
                window.shuffle_study()
            self.assertEqual(window.filtered_entries[0].original, "Ich lerne Deutsch.")

            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                window.delete_current_entry()

            remaining_log = log_path.read_text(encoding="utf-8")
            self.assertIn("Guten Morgen", remaining_log)
            self.assertNotIn("Ich lerne Deutsch.", remaining_log)
            self.assertEqual([entry.original for entry in window.entries], ["Guten Morgen"])

    def test_export_respects_score_filter_after_score_change(self):
        window = self.make_window()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log_path = root / "translations.log"
            export_path = root / "filtered.csv"
            log_path.write_text(SYNTHETIC_LOG, encoding="utf-8")
            window.score_store = ScoreStore(root / "scores.json")
            window.load_log(str(log_path))
            window.scores = {key: 5 for key in window.entry_keys}
            window.include_unrated.setChecked(False)
            window.minimum_score.setValue(4)
            window.apply_filters()
            self.assertEqual(len(window.filtered_entries), 2)

            window.set_score(2)

            self.assertEqual([entry.original for entry in window.filtered_entries], ["Ich lerne Deutsch."])
            with patch.object(QFileDialog, "getSaveFileName", return_value=(str(export_path), "CSV files (*.csv)")):
                window.export_current()

            with export_path.open(encoding="utf-8-sig", newline="") as csv_file:
                rows = list(csv.reader(csv_file))

        self.assertEqual(len(rows), 2)
        self.assertIn("Ich lerne Deutsch.", rows[1])
        self.assertNotIn("Guten Morgen", rows[1])
        self.assertEqual(rows[1][-1], "5")

    def test_settings_restore_on_next_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings_path = root / "learning-settings.ini"
            log_path = root / "translations.log"
            log_path.write_text(SYNTHETIC_LOG, encoding="utf-8")

            first = self.make_window(settings_path)
            first.load_log(str(log_path))
            first.use_dates.setChecked(True)
            first.start_date.setDate(QDate(2026, 8, 1))
            first.end_date.setDate(QDate(2026, 8, 31))
            first.category.setCurrentText("Phrases")
            first.phrase_max.setValue(3)
            first.minimum_score.setValue(2)
            first.maximum_score.setValue(4)
            first.include_unrated.setChecked(False)
            first.maximum_items.setValue(25)
            first.duration_minutes.setValue(15)
            first.field_checks["translation:fr"].setChecked(False)
            first.field_checks["timestamp"].setChecked(True)
            first.increase_study_font()
            first.tabs.setCurrentIndex(1)
            first.close()

            restored = self.make_window(settings_path)

            self.assertEqual(restored.log_path, str(log_path))
            self.assertTrue(restored.use_dates.isChecked())
            self.assertEqual(restored.start_date.date(), QDate(2026, 8, 1))
            self.assertEqual(restored.end_date.date(), QDate(2026, 8, 31))
            self.assertEqual(restored.category.currentText(), "Phrases")
            self.assertEqual(restored.phrase_max.value(), 3)
            self.assertEqual(restored.minimum_score.value(), 2)
            self.assertEqual(restored.maximum_score.value(), 4)
            self.assertFalse(restored.include_unrated.isChecked())
            self.assertEqual(restored.maximum_items.value(), 25)
            self.assertEqual(restored.duration_minutes.value(), 15)
            self.assertFalse(restored.field_checks["translation:fr"].isChecked())
            self.assertTrue(restored.field_checks["timestamp"].isChecked())
            self.assertEqual(restored.study_font_size, 15)
            self.assertEqual(restored.tabs.currentIndex(), 1)


if __name__ == "__main__":
    unittest.main()