"""WebCodecsView: Hardware-accelerated Direct3D 11 Chromium viewport embedding the iPhone canvas."""

from __future__ import annotations

import logging
from PySide6.QtCore import Qt, QUrl
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QWidget

logger = logging.getLogger(__name__)


class WebCodecsView(QWebEngineView):
    """Embeds the WebCodecs hardware accelerated HEVC canvas viewport."""

    def __init__(self, url: str = "http://127.0.0.1:8080", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.stream_url = url
        self._configure_settings()
        self.setUrl(QUrl(self.stream_url))

    def _configure_settings(self) -> None:
        settings = self.settings()
        # Enable GPU acceleration & WebCodecs features
        settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.AllowRunningInsecureContent, True)

        # Context menu policy - clean desktop app look
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
