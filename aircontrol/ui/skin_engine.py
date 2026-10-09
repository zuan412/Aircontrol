"""Extensible device skinning and profiling engine for Aircontrol.

Loads and manages device profiles from JSON manifests, supporting:
- Custom aspect ratios, corner radiuses, and bezel thicknesses.
- PBR metallic vector colors and high-DPI textures.
- Dynamic device matching based on iOS product_type identifiers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)


def get_default_skins_dir() -> Path:
    """Resolve skins directory across development, PyInstaller, and portable runtime."""
    if getattr(sys, "frozen", False):
        exe_skins = Path(sys.executable).resolve().parent / "skins"
        if exe_skins.is_dir():
            return exe_skins
        if hasattr(sys, "_MEIPASS"):
            bundle_skins = Path(sys._MEIPASS) / "skins"
            if bundle_skins.is_dir():
                return bundle_skins

    repo_skins = Path(__file__).resolve().parent.parent.parent / "skins"
    return repo_skins


DEFAULT_SKINS_DIR = get_default_skins_dir()


@dataclass
class SkinProfile:
    """Defines physical dimensions and styling parameters for a simulated device."""

    id: str
    name: str
    compatible_devices: List[str] = field(default_factory=list)
    aspect_ratio: float = 9.0 / 19.5
    bezel_width_ratio: float = 0.024
    corner_radius_ratio: float = 0.09
    has_dynamic_island: bool = True
    has_home_bar: bool = True
    chassis_color: Tuple[float, float, float] = (0.61, 0.64, 0.69)
    chamfer_highlight: bool = True
    texture_path: Optional[str] = None

    @property
    def bezel_width(self) -> float:
        """Calculated bezel width in pixels for typical viewport."""
        if self.bezel_width_ratio <= 0.001:
            return 0.0
        return max(1.0, 360.0 * float(self.bezel_width_ratio))

    @classmethod
    def from_dict(cls, data: Dict[str, Any], skin_dir: Optional[Path] = None) -> SkinProfile:
        screen = data.get("screen", {})
        visuals = data.get("visuals", {})

        color_raw = visuals.get("chassis_color", [0.61, 0.64, 0.69])
        chassis_color = (float(color_raw[0]), float(color_raw[1]), float(color_raw[2]))

        tex_path = visuals.get("texture_path")
        if tex_path and skin_dir:
            full_path = skin_dir / tex_path
            tex_path = str(full_path) if full_path.exists() else None

        return cls(
            id=data.get("id", "custom-skin"),
            name=data.get("name", "Custom Device"),
            compatible_devices=data.get("compatible_devices", []),
            aspect_ratio=float(screen.get("aspect_ratio", 9.0 / 19.5)),
            bezel_width_ratio=float(visuals.get("bezel_width_ratio", 0.024)),
            corner_radius_ratio=float(screen.get("corner_radius_ratio", 0.09)),
            has_dynamic_island=bool(screen.get("has_dynamic_island", True)),
            has_home_bar=bool(screen.get("has_home_bar", True)),
            chassis_color=chassis_color,
            chamfer_highlight=bool(visuals.get("chamfer_highlight", True)),
            texture_path=tex_path,
        )


class SkinManager(QObject):
    """Discovers, loads, and switches device skins."""

    skin_changed = Signal(SkinProfile)

    DEFAULT_SKIN_ID = "stage-manager-clean"

    def __init__(self, skins_dir: Optional[Path] = None, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.skins_dir = skins_dir or DEFAULT_SKINS_DIR
        self._skins: Dict[str, SkinProfile] = {}
        self.default_skin_id = self.DEFAULT_SKIN_ID
        self.load_skins(self.skins_dir)

        self._active_skin: SkinProfile = self._skins.get(
            self.default_skin_id,
            SkinProfile(
                id=self.default_skin_id,
                name="Không Viền (Bo góc nhẹ)",
                bezel_width_ratio=0.0,
            ),
        )

    @property
    def available_skins(self) -> Dict[str, SkinProfile]:
        """Dictionary of loaded skin profiles keyed by skin ID."""
        return dict(self._skins)

    @property
    def active_skin(self) -> SkinProfile:
        """Currently active device skin profile."""
        return self._active_skin

    def load_skins(self, skins_dir: Path) -> None:
        """Scan directory and parse all skin.json manifests."""
        self._skins.clear()
        if not skins_dir.exists() or not skins_dir.is_dir():
            return

        for folder in skins_dir.iterdir():
            if not folder.is_dir():
                continue
            manifest_path = folder / "skin.json"
            if manifest_path.exists():
                try:
                    data = json.loads(manifest_path.read_text(encoding="utf-8"))
                    profile = SkinProfile.from_dict(data, skin_dir=folder)
                    self._skins[profile.id] = profile
                except Exception as e:
                    logger.warning("Failed to parse skin manifest %s: %s", manifest_path, e)

    def get_skin(self, skin_id: str) -> SkinProfile:
        """Retrieve skin profile by ID, falling back to default skin."""
        if skin_id in self._skins:
            return self._skins[skin_id]
        if self.default_skin_id in self._skins:
            return self._skins[self.default_skin_id]
        return self._active_skin

    def match_device(self, product_type: str) -> SkinProfile:
        """Match iOS device product_type identifier to best matching skin."""
        clean_type = (product_type or "").strip()
        for profile in self._skins.values():
            if clean_type in profile.compatible_devices:
                return profile

        # Partial matching heuristic
        clean_lower = clean_type.lower()
        if "16,1" in clean_lower or "16,2" in clean_lower or "17,1" in clean_lower or "17,2" in clean_lower:
            return self.get_skin("iphone-16-pro-natural")
        if "15," in clean_lower:
            return self.get_skin("iphone-15")

        return self.get_skin(self.default_skin_id)

    def switch_skin(self, skin_id: str) -> bool:
        """Switch active skin profile and emit skin_changed signal."""
        target = self.get_skin(skin_id)
        if target.id == self._active_skin.id and self._active_skin in self._skins.values():
            return True
        self._active_skin = target
        self.skin_changed.emit(self._active_skin)
        return True

    def set_active_skin(self, skin_id: str) -> Optional[SkinProfile]:
        """Set active skin by ID, returning the active profile."""
        if self.switch_skin(skin_id):
            return self._active_skin
        return None
