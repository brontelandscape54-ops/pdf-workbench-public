"""Keyboard selection in the central Custom split preview."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent, QKeySequence, QPixmap
from PySide6.QtWidgets import QApplication, QLineEdit, QListWidget

from pdf_workbench.core.models import (
    CustomSplitDirection,
    PageSplitSettings,
    SplitMode,
    custom_leaf_paths,
    split_custom_leaf,
)
from pdf_workbench.gui.page_view import PageView


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication([])
    yield instance


@pytest.fixture
def view(app):
    result = PageView()
    settings = PageSplitSettings(mode=SplitMode.CUSTOM)
    split_custom_leaf(settings.custom_root, (), CustomSplitDirection.VERTICAL)
    split_custom_leaf(settings.custom_root, (0,), CustomSplitDirection.HORIZONTAL)
    result.set_page(QPixmap(400, 600), settings)
    yield result
    result.close()


def _select_all_key_event() -> QKeyEvent:
    combo = QKeySequence(QKeySequence.StandardKey.SelectAll)[0]
    return QKeyEvent(
        QEvent.Type.KeyPress,
        combo.key(),
        combo.keyboardModifiers(),
    )


def test_select_all_shortcut_selects_all_regions_without_modifying_layout(view) -> None:
    original = view._settings.clone()
    selection_events = []
    view.on_custom_selected = selection_events.append
    view.keyPressEvent(_select_all_key_event())
    assert view.selected_custom_paths == set(custom_leaf_paths(original.custom_root))
    assert len(view.selected_custom_paths) == 3
    assert view.selected_custom_line_path is None
    assert view._settings == original
    assert selection_events == [view.selected_custom_path]


def test_escape_collapses_multi_selection_to_active_region(view) -> None:
    view.select_all_custom_regions()
    current = view.selected_custom_path
    view.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    assert view.selected_custom_paths == {current}
    assert view.selected_custom_line_path is None


def test_select_all_is_ignored_while_reordering(view) -> None:
    assert view.begin_custom_reorder(set(custom_leaf_paths(view._settings.custom_root)))
    original = view.selected_custom_paths
    assert view.select_all_custom_regions() is False
    view.keyPressEvent(_select_all_key_event())
    assert view.is_reordering_custom
    assert view.selected_custom_paths == original
    view.cancel_custom_reorder()


def test_select_all_is_only_handled_for_custom_page(view) -> None:
    view.set_settings(PageSplitSettings(mode=SplitMode.NONE))
    assert view.select_all_custom_regions() is False


def test_unrelated_thumbnail_and_text_input_selection_remain_independent(app, view) -> None:
    thumbnails = QListWidget()
    thumbnails.addItems(["page 1", "page 2"])
    thumbnails.item(1).setSelected(True)
    field = QLineEdit("1,2-4")
    field.setSelection(0, 1)
    view.keyPressEvent(_select_all_key_event())
    assert thumbnails.selectedItems()[0].text() == "page 2"
    assert field.selectedText() == "1"
    thumbnails.close()
    field.close()
