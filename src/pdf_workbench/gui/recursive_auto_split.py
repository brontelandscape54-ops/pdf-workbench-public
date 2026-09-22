from __future__ import annotations

from types import MethodType

from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pdf_workbench.core.auto_split import (
    AUTO_SPLIT_PRESETS,
    AutoSplitPlan,
    build_whitespace_split_plan,
    get_auto_split_preset,
    graft_auto_split_plan,
)
from pdf_workbench.core.models import (
    SplitMode,
    custom_leaf_paths,
    custom_leaf_rects,
)
from pdf_workbench.core.page_ranges import parse_page_spec
from pdf_workbench.core.pdf_engine import render_page_to_image


def _selected_region_image(window, page_index: int, path):
    settings = window.page_settings[page_index]
    rect = custom_leaf_rects(settings.custom_root).get(path)
    if rect is None:
        raise ValueError("選択領域が現在の分割に存在しません")

    image = render_page_to_image(window.doc[page_index], 110)
    x0, y0, x1, y1 = rect
    box = (
        max(0, min(image.width - 1, round(x0 * image.width))),
        max(0, min(image.height - 1, round(y0 * image.height))),
        max(1, min(image.width, round(x1 * image.width))),
        max(1, min(image.height, round(y1 * image.height))),
    )
    if box[2] - box[0] < 24 or box[3] - box[1] < 24:
        raise ValueError("選択領域が小さすぎるため解析できません")
    return image.crop(box)


def _scrollable_panel(widget: QWidget) -> QScrollArea:
    """Wrap a tall right-side panel without forcing the whole window taller."""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setMinimumSize(0, 0)
    widget.setMinimumHeight(0)
    scroll.setWidget(widget)
    return scroll


def install_recursive_auto_split(window) -> None:
    """Install recursive / multi-page auto split controls in a dedicated tab."""

    splitter = window.centralWidget()
    manual_panel = splitter.widget(2)

    tabs = QTabWidget()
    tabs.setMinimumSize(0, 0)
    auto_panel = QWidget()
    auto_panel.setMinimumHeight(0)
    auto_layout = QVBoxLayout(auto_panel)

    replaced = splitter.replaceWidget(2, tabs)
    if replaced is not None:
        manual_panel = replaced

    manual_scroll = _scrollable_panel(manual_panel)
    auto_scroll = _scrollable_panel(auto_panel)
    tabs.addTab(manual_scroll, "手動・出力")
    tabs.addTab(auto_scroll, "自動分割")
    splitter.setSizes([175, 965, 330])
    window.right_tabs = tabs
    window.manual_controls_scroll = manual_scroll
    window.auto_split_scroll = auto_scroll
    window.auto_split_tab = auto_panel

    intro = QLabel(
        "画像中の白い谷を解析してCustom splitを自動生成します。\n"
        "頁を移動しても、このタブからいつでも再実行できます。"
    )
    intro.setWordWrap(True)
    auto_layout.addWidget(intro)

    sensitivity_label = QLabel("検出感度")
    sensitivity = QComboBox()
    for preset in AUTO_SPLIT_PRESETS:
        sensitivity.addItem(preset.label, preset.key)
    sensitivity.setCurrentIndex(sensitivity.findData("standard"))
    sensitivity.setToolTip("安全 → 標準 → 積極的 → 探索的 の順に、より弱い候補線まで採用します。")
    sensitivity_help = QLabel("")
    sensitivity_help.setWordWrap(True)
    window.auto_split_sensitivity = sensitivity
    window.auto_split_sensitivity_help = sensitivity_help
    auto_layout.addWidget(sensitivity_label)
    auto_layout.addWidget(sensitivity)
    auto_layout.addWidget(sensitivity_help)

    max_label = QLabel("1頁・1領域あたりの安全上限")
    max_regions = QSpinBox()
    max_regions.setRange(2, 30)
    max_regions.setValue(12)
    max_regions.setSuffix(" 領域")
    max_regions.setToolTip(
        "この数まで必ず分割するわけではありません。候補がなくなれば自動停止します。"
    )
    window.auto_split_max_regions = max_regions
    auto_layout.addWidget(max_label)
    auto_layout.addWidget(max_regions)

    balance_fallback = QCheckBox("大きな未分割領域を均衡補正する")
    balance_fallback.setChecked(True)
    balance_fallback.setToolTip(
        "白い谷が十分明瞭でなくても、大きく残った領域では中央付近の低インク位置を"
        "低優先度の補正線として候補にします。頁内・頁間の分割数の偏りを抑えます。"
    )
    balance_help = QLabel(
        "補正線は明瞭な余白線より低優先度です。効きすぎる場合はOFFにできます。"
    )
    balance_help.setWordWrap(True)
    window.auto_split_balance_fallback = balance_fallback
    auto_layout.addWidget(balance_fallback)
    auto_layout.addWidget(balance_help)

    current_label = QLabel("現在の頁・領域")
    current_region_button = QPushButton("現在の選択領域を自動分割")
    current_page_button = QPushButton("現在ページ全体を自動分割")
    auto_layout.addWidget(current_label)
    auto_layout.addWidget(current_region_button)
    auto_layout.addWidget(current_page_button)

    bulk_label = QLabel("複数頁をまとめて自動分割")
    range_note = QLabel(
        "下の『指定ページ』は手動タブと共通です。\n"
        "例: 1-100 / 4-60/7 / 4,11-60/7"
    )
    range_note.setWordWrap(True)
    range_button = QPushButton("指定ページを一括自動分割")
    selected_button = QPushButton("左で選択したページを一括自動分割")
    window.auto_split_current_region_button = current_region_button
    window.auto_split_current_page_button = current_page_button
    window.auto_split_range_button = range_button
    window.auto_split_selected_pages_button = selected_button
    auto_layout.addWidget(bulk_label)
    auto_layout.addWidget(range_note)
    auto_layout.addWidget(range_button)
    auto_layout.addWidget(selected_button)
    auto_layout.addStretch(1)

    old_auto_button = window.custom_auto_split_button
    try:
        old_auto_button.clicked.disconnect()
    except (RuntimeError, TypeError):
        pass
    old_auto_button.setVisible(False)

    def selected_preset():
        return get_auto_split_preset(str(sensitivity.currentData()))

    def update_sensitivity_help() -> None:
        sensitivity_help.setText(selected_preset().description)

    sensitivity.currentIndexChanged.connect(update_sensitivity_help)
    update_sensitivity_help()

    def max_count() -> int:
        return int(max_regions.value())

    def build_plan(image) -> AutoSplitPlan:
        return build_whitespace_split_plan(
            image,
            max_regions=max_count(),
            preset=selected_preset(),
            enable_balance_fallback=balance_fallback.isChecked(),
        )

    def analyze_page(page_index: int) -> AutoSplitPlan:
        image = render_page_to_image(window.doc[page_index], 90)
        return build_plan(image)

    def plan_breakdown(plan: AutoSplitPlan) -> str:
        return (
            f"余白検出線: {plan.whitespace_split_count} 本\n"
            f"均衡補正線: {plan.balance_split_count} 本"
        )

    def apply_plan_to_selected_region(plan: AutoSplitPlan) -> None:
        settings = window.page_settings[window.current_page]
        path = window.page_view.selected_custom_path
        snapshot = (window.current_page, window._clone_all_settings())
        selection_before = window._capture_custom_selection()
        try:
            settings.custom_order = graft_auto_split_plan(
                settings.custom_root,
                settings.custom_order,
                path,
                plan.root,
            )
        except ValueError as exc:
            QMessageBox.warning(window, "自動分割", str(exc))
            return

        window._history_selection_override = selection_before
        window._record_undo_snapshot(snapshot)
        window.page_view.set_settings(settings)
        local_first = custom_leaf_paths(plan.root)[0]
        window.page_view.select_custom_path(path + local_first)
        window._refresh_thumbnail(window.current_page)
        window._refresh_custom_selection_label()

    def auto_split_selected_region() -> None:
        if not window.page_settings or window.doc is None:
            return
        if window.current_page in getattr(window, "locked_pages", set()):
            QMessageBox.information(
                window,
                "自動分割",
                "現在のページは固定されています。固定を解除してから編集してください。",
            )
            return
        settings = window.page_settings[window.current_page]
        if settings.mode != SplitMode.CUSTOM:
            QMessageBox.information(
                window,
                "自動分割",
                "選択領域の自動分割はCustom splitの頁で利用できます。\n"
                "頁全体を解析する場合は『現在ページ全体を自動分割』を使ってください。",
            )
            return
        if len(window.page_view.selected_custom_paths) != 1:
            QMessageBox.information(
                window,
                "自動分割",
                "自動分割する領域を1つだけ選択してください。",
            )
            return

        preset = selected_preset()
        try:
            image = _selected_region_image(
                window,
                window.current_page,
                window.page_view.selected_custom_path,
            )
            plan = build_plan(image)
        except Exception as exc:
            QMessageBox.warning(window, "自動分割", f"画像解析に失敗しました。\n\n{exc}")
            return

        if plan.split_count == 0:
            QMessageBox.information(
                window,
                "自動分割",
                f"検出感度「{preset.label}」では分割候補を見つけられませんでした。",
            )
            return

        answer = QMessageBox.question(
            window,
            "自動分割候補",
            f"検出感度: {preset.label}\n"
            f"分割線候補: {plan.split_count} 本\n"
            f"{plan_breakdown(plan)}\n"
            f"分割後の領域数: {plan.leaf_count}\n"
            f"平均信頼度（暫定）: {plan.average_score:.2f}\n"
            f"最低信頼度（暫定）: {plan.minimum_score:.2f}\n\n"
            "まとめてこの分割を適用しますか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        apply_plan_to_selected_region(plan)
        window.statusBar().showMessage(
            f"{preset.label}で選択領域を {plan.leaf_count} 領域に自動分割しました"
        )

    def batch_auto_split(indexes: list[int], label: str) -> None:
        if not window.page_settings or window.doc is None:
            return
        requested = sorted(set(indexes))
        locked = getattr(window, "locked_pages", set())
        targets = [index for index in requested if index not in locked]
        skipped_locked = len(requested) - len(targets)
        if not targets:
            QMessageBox.information(
                window,
                "一括自動分割",
                "対象ページがありません。固定ページだけが指定されている場合は、先に固定を解除してください。",
            )
            return

        preset = selected_preset()
        balance_state = "ON" if balance_fallback.isChecked() else "OFF"
        answer = QMessageBox.question(
            window,
            "一括自動分割",
            f"{len(targets)} ページを画像解析し、各ページ全体の分割設定を自動生成します。\n"
            f"検出感度: {preset.label}\n"
            f"均衡補正: {balance_state}\n"
            f"固定中のページは除外: {skipped_locked}\n"
            f"1ページあたりの安全上限: {max_count()} 領域\n\n"
            "候補が見つかったページだけCustom splitへ置き換えます。\n"
            "処理全体は1回の⌘Zで戻せます。続行しますか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        progress = QProgressDialog(
            "ページの余白構造を解析しています…",
            "Cancel",
            0,
            len(targets),
            window,
        )
        progress.setWindowTitle("一括自動分割")
        progress.setMinimumDuration(0)

        plans: dict[int, AutoSplitPlan] = {}
        try:
            for position, page_index in enumerate(targets, start=1):
                progress.setLabelText(
                    f"{page_index + 1}頁を解析しています… ({position}/{len(targets)})"
                )
                QApplication.processEvents()
                if progress.wasCanceled():
                    progress.close()
                    window.statusBar().showMessage("一括自動分割をキャンセルしました（変更なし）")
                    return
                plan = analyze_page(page_index)
                if plan.split_count > 0:
                    plans[page_index] = plan
                progress.setValue(position)
                QApplication.processEvents()
            progress.close()
        except Exception as exc:
            progress.close()
            QMessageBox.warning(window, "一括自動分割", f"画像解析に失敗しました。\n\n{exc}")
            return

        if not plans:
            QMessageBox.information(
                window,
                "一括自動分割",
                f"検出感度「{preset.label}」では対象ページに候補を検出できませんでした。",
            )
            return

        snapshot = (window.current_page, window._clone_all_settings())
        selection_before = window._capture_custom_selection()
        for page_index, plan in plans.items():
            settings = window.page_settings[page_index]
            settings.mode = SplitMode.CUSTOM
            settings.custom_root = plan.root.clone()
            settings.custom_order = []

        window._history_selection_override = selection_before
        window._record_undo_snapshot(snapshot)

        for page_index in plans:
            if page_index != window.current_page:
                window._refresh_thumbnail(page_index)
        if window.current_page in plans:
            window._show_current_page()
            window._refresh_thumbnail(window.current_page)

        unchanged = len(targets) - len(plans)
        total_whitespace = sum(plan.whitespace_split_count for plan in plans.values())
        total_balance = sum(plan.balance_split_count for plan in plans.values())
        window.statusBar().showMessage(
            f"{label}: {len(plans)}頁を{preset.label}で自動分割"
            f"（候補なし {unchanged}頁、固定除外 {skipped_locked}頁）"
        )
        QMessageBox.information(
            window,
            "一括自動分割 完了",
            f"検出感度: {preset.label}\n"
            f"均衡補正: {balance_state}\n"
            f"自動分割を適用: {len(plans)} ページ\n"
            f"余白検出線: {total_whitespace} 本\n"
            f"均衡補正線: {total_balance} 本\n"
            f"候補なし: {unchanged} ページ\n"
            f"固定のため除外: {skipped_locked} ページ\n\n"
            "必要なページだけ手動タブで赤線をドラッグして微調整できます。",
        )

    def auto_split_current_page() -> None:
        if not window.page_settings:
            return
        batch_auto_split([window.current_page], "現在ページの自動分割")

    def auto_split_range() -> None:
        if not window.page_settings:
            return
        try:
            indexes = parse_page_spec(
                window.page_range_input.text(),
                len(window.page_settings),
            )
        except ValueError as exc:
            QMessageBox.warning(window, "ページ指定", str(exc))
            return
        batch_auto_split(indexes, "指定ページの一括自動分割")

    def auto_split_selected_pages() -> None:
        indexes = sorted({index.row() for index in window.page_list.selectedIndexes()})
        if not indexes:
            QMessageBox.information(
                window,
                "ページ選択",
                "左のサムネイル一覧で、対象ページを⌘クリックまたはShiftクリックで選択してください。",
            )
            return
        batch_auto_split(indexes, "選択ページの一括自動分割")

    current_region_button.clicked.connect(auto_split_selected_region)
    current_page_button.clicked.connect(auto_split_current_page)
    range_button.clicked.connect(auto_split_range)
    selected_button.clicked.connect(auto_split_selected_pages)

    original_set_controls_enabled = window._set_controls_enabled

    def set_controls_enabled(self, enabled: bool) -> None:
        original_set_controls_enabled(enabled)
        sensitivity.setEnabled(enabled)
        max_regions.setEnabled(enabled)
        balance_fallback.setEnabled(enabled)
        current_region_button.setEnabled(enabled)
        current_page_button.setEnabled(enabled)
        range_button.setEnabled(enabled)
        selected_button.setEnabled(enabled)

    window._set_controls_enabled = MethodType(set_controls_enabled, window)
    enabled = bool(window.page_settings)
    sensitivity.setEnabled(enabled)
    max_regions.setEnabled(enabled)
    balance_fallback.setEnabled(enabled)
    current_region_button.setEnabled(enabled)
    current_page_button.setEnabled(enabled)
    range_button.setEnabled(enabled)
    selected_button.setEnabled(enabled)
