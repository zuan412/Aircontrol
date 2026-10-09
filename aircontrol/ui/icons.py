"""Monochrome vector icon generator for Aircontrol's Bespoke UI design system."""

from __future__ import annotations

from typing import Optional
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


def _create_canvas(size: int = 36) -> tuple[QPixmap, QPainter]:
    """Create a high-DPI antialiased canvas for drawing monochrome icons."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    return pix, painter


def get_monochrome_icon(
    icon_type: str,
    base_color: str = "#C5CBD8",
    active_color: str = "#FFFFFF",
    size: int = 36,
) -> QIcon:
    """Generate a crisp, high-resolution monochrome vector QIcon.

    Supports normal (unselected) and active/hover states with antialiased stroke rendering.
    """
    normal_pix = _render_vector_icon(icon_type, base_color, size)
    active_pix = _render_vector_icon(icon_type, active_color, size)

    icon = QIcon()
    icon.addPixmap(normal_pix, QIcon.Mode.Normal, QIcon.State.Off)
    icon.addPixmap(active_pix, QIcon.Mode.Active, QIcon.State.Off)
    icon.addPixmap(active_pix, QIcon.Mode.Selected, QIcon.State.Off)
    return icon


def _render_vector_icon(icon_type: str, color_hex: str, size: int) -> QPixmap:
    pix, p = _create_canvas(size)
    color = QColor(color_hex)
    pen = QPen(color, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    c = size / 2.0  # Center point (18.0 for size 36)

    if icon_type == "device":
        # Sleek iPhone silhouette with rounded display and top pill
        frame = QRectF(c - 7.0, c - 12.0, 14.0, 24.0)
        p.drawRoundedRect(frame, 3.5, 3.5)
        # Dynamic Island pill
        p.setPen(QPen(color, 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(c - 2.0, c - 8.5), QPointF(c + 2.0, c - 8.5))

    elif icon_type == "home":
        # Minimalist modern house outline
        path = QPainterPath()
        path.moveTo(c - 9.0, c + 7.0)
        path.lineTo(c - 9.0, c - 1.0)
        path.lineTo(c, c - 9.0)
        path.lineTo(c + 9.0, c - 1.0)
        path.lineTo(c + 9.0, c + 7.0)
        path.closeSubpath()
        p.drawPath(path)
        # Doorway line
        p.drawLine(QPointF(c - 3.0, c + 7.0), QPointF(c - 3.0, c + 1.5))
        p.drawLine(QPointF(c - 3.0, c + 1.5), QPointF(c + 3.0, c + 1.5))
        p.drawLine(QPointF(c + 3.0, c + 1.5), QPointF(c + 3.0, c + 7.0))

    elif icon_type == "app_switcher":
        # 4 rounded cards grid (Lucide LayoutGrid style)
        r1 = QRectF(c - 9.0, c - 9.0, 7.5, 7.5)
        r2 = QRectF(c + 1.5, c - 9.0, 7.5, 7.5)
        r3 = QRectF(c - 9.0, c + 1.5, 7.5, 7.5)
        r4 = QRectF(c + 1.5, c + 1.5, 7.5, 7.5)
        p.drawRoundedRect(r1, 2.0, 2.0)
        p.drawRoundedRect(r2, 2.0, 2.0)
        p.drawRoundedRect(r3, 2.0, 2.0)
        p.drawRoundedRect(r4, 2.0, 2.0)

    elif icon_type == "frame":
        # Dashed / corner frame boundary (Frame / Borderless toggle)
        s = 8.5
        # Top-left corner
        p.drawLine(QPointF(c - s, c - s + 4.0), QPointF(c - s, c - s))
        p.drawLine(QPointF(c - s, c - s), QPointF(c - s + 4.0, c - s))
        # Top-right corner
        p.drawLine(QPointF(c + s - 4.0, c - s), QPointF(c + s, c - s))
        p.drawLine(QPointF(c + s, c - s), QPointF(c + s, c - s + 4.0))
        # Bottom-right corner
        p.drawLine(QPointF(c + s, c + s - 4.0), QPointF(c + s, c + s))
        p.drawLine(QPointF(c + s, c + s), QPointF(c + s - 4.0, c + s))
        # Bottom-left corner
        p.drawLine(QPointF(c - s + 4.0, c + s), QPointF(c - s, c + s))
        p.drawLine(QPointF(c - s, c + s), QPointF(c - s, c + s - 4.0))

    elif icon_type == "rotate":
        # Clean 270-degree rotation arc with sharp arrow
        arc_rect = QRectF(c - 8.0, c - 8.0, 16.0, 16.0)
        p.drawArc(arc_rect, 40 * 16, 275 * 16)
        arrow = QPainterPath()
        arrow.moveTo(c + 5.5, c - 8.5)
        arrow.lineTo(c + 9.5, c - 5.5)
        arrow.lineTo(c + 5.5, c - 2.5)
        p.drawPath(arrow)

    elif icon_type == "keyboard":
        # Rounded keyboard silhouette with keys and spacebar
        body = QRectF(c - 10.0, c - 6.5, 20.0, 13.0)
        p.drawRoundedRect(body, 2.5, 2.5)
        # Top key row dots
        p.setPen(QPen(color, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawPoint(QPointF(c - 6.0, c - 2.5))
        p.drawPoint(QPointF(c - 2.0, c - 2.5))
        p.drawPoint(QPointF(c + 2.0, c - 2.5))
        p.drawPoint(QPointF(c + 6.0, c - 2.5))
        # Spacebar line
        p.drawLine(QPointF(c - 4.0, c + 2.5), QPointF(c + 4.0, c + 2.5))

    elif icon_type == "moon":
        # Smooth crescent moon (Night / Dim screen)
        path = QPainterPath()
        path.moveTo(c + 5.0, c - 8.0)
        path.arcTo(QRectF(c - 8.0, c - 8.0, 16.0, 16.0), 55, 250)
        path.arcTo(QRectF(c - 5.0, c - 7.0, 13.0, 14.0), 305, -230)
        path.closeSubpath()
        p.drawPath(path)

    elif icon_type == "lock":
        # Sleek padlock
        body = QRectF(c - 6.5, c - 1.5, 13.0, 10.0)
        p.drawRoundedRect(body, 2.0, 2.0)
        # Shackle
        shackle = QPainterPath()
        shackle.arcMoveTo(QRectF(c - 4.5, c - 8.0, 9.0, 9.0), 0)
        shackle.arcTo(QRectF(c - 4.5, c - 8.0, 9.0, 9.0), 0, 180)
        p.drawPath(shackle)

    elif icon_type == "pin":
        # Minimalist pushpin icon (Always on Top)
        path = QPainterPath()
        path.moveTo(c - 4.0, c - 7.0)
        path.lineTo(c + 4.0, c - 7.0)
        path.lineTo(c + 2.0, c - 1.0)
        path.lineTo(c + 6.0, c + 1.0)
        path.lineTo(c - 6.0, c + 1.0)
        path.lineTo(c - 2.0, c - 1.0)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(c, c + 1.0), QPointF(c, c + 8.0))

    elif icon_type == "folder":
        # Clean folder outline
        path = QPainterPath()
        path.moveTo(c - 9.0, c + 6.0)
        path.lineTo(c - 9.0, c - 5.0)
        path.lineTo(c - 4.0, c - 5.0)
        path.lineTo(c - 2.0, c - 3.0)
        path.lineTo(c + 9.0, c - 3.0)
        path.lineTo(c + 9.0, c + 6.0)
        path.closeSubpath()
        p.drawPath(path)

    elif icon_type == "clipboard":
        # Clean clipboard outline with top clip
        board = QRectF(c - 7.0, c - 5.0, 14.0, 14.0)
        p.drawRoundedRect(board, 2.0, 2.0)
        clip = QRectF(c - 3.5, c - 8.0, 7.0, 4.0)
        p.drawRoundedRect(clip, 1.5, 1.5)

    elif icon_type == "check":
        # Crisp checkmark for active skin
        check_pen = QPen(QColor("#22C55E"), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(check_pen)
        path = QPainterPath()
        path.moveTo(c - 7.0, c + 0.5)
        path.lineTo(c - 2.0, c + 5.5)
        path.lineTo(c + 7.0, c - 5.0)
        p.drawPath(path)

    p.end()
    return pix
