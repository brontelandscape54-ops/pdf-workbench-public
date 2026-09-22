from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from pdf_workbench.gui.bundle_update import install_bundle_update
from pdf_workbench.gui.context_help import install_context_help
from pdf_workbench.gui.custom_first import install_custom_first
from pdf_workbench.gui.multi_page_edit import install_multi_page_edit
from pdf_workbench.gui.page_locking import install_page_locking
from pdf_workbench.gui.recursive_auto_split import install_recursive_auto_split
from pdf_workbench.gui.window_fit import fit_window_to_available_screen
from pdf_workbench.gui.workbench_window import WorkbenchMainWindow
from pdf_workbench.gui.workspace_resume import install_workspace_resume


def main() -> int:
    app = QApplication(sys.argv)
    window = WorkbenchMainWindow()
    install_page_locking(window)
    install_recursive_auto_split(window)
    install_workspace_resume(window)
    install_bundle_update(window)
    install_context_help(window)
    install_custom_first(window)
    install_multi_page_edit(window)
    fit_window_to_available_screen(window)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
