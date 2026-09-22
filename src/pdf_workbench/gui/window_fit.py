from __future__ import annotations

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication, QWidget


def fit_window_to_available_screen(
    window: QWidget,
    *,
    width_fraction: float = 0.94,
    height_fraction: float = 0.90,
) -> None:
    """Keep the application window inside the usable desktop area.

    The usable area excludes the macOS menu bar and Dock.  The helper is
    intentionally called before ``show()`` so the first visible frame already
    has an accessible bottom/right resize edge.
    """
    app = QApplication.instance()
    if app is None:
        return

    screen = window.screen() or QApplication.primaryScreen()
    if screen is None:
        return

    available: QRect = screen.availableGeometry()
    if available.width() <= 0 or available.height() <= 0:
        return

    width_fraction = min(1.0, max(0.25, float(width_fraction)))
    height_fraction = min(1.0, max(0.25, float(height_fraction)))

    max_width = max(1, int(available.width() * width_fraction))
    max_height = max(1, int(available.height() * height_fraction))

    target_width = min(max(1, window.width()), max_width)
    target_height = min(max(1, window.height()), max_height)
    window.resize(target_width, target_height)

    frame = window.frameGeometry()
    frame.moveCenter(available.center())

    # Clamp once more after centering in case window-manager frame decorations
    # extend a few pixels beyond the available rectangle.
    x = min(
        max(frame.x(), available.left()),
        max(available.left(), available.right() - frame.width() + 1),
    )
    y = min(
        max(frame.y(), available.top()),
        max(available.top(), available.bottom() - frame.height() + 1),
    )
    window.move(x, y)
