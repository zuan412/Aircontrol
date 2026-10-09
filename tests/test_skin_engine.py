"""Unit tests for Aircontrol SkinEngine (SkinProfile and SkinManager)."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from aircontrol.ui.skin_engine import SkinProfile, SkinManager


def test_skin_profile_defaults():
    profile = SkinProfile(
        id="test-device",
        name="Test Device",
        compatible_devices=["iPhone16,1"],
        aspect_ratio=9.0 / 19.5,
        bezel_width_ratio=0.024,
        corner_radius_ratio=0.09,
    )
    assert profile.id == "test-device"
    assert profile.name == "Test Device"
    assert profile.compatible_devices == ["iPhone16,1"]
    assert profile.has_dynamic_island is True
    assert profile.has_home_bar is True
    assert profile.chassis_color == (0.61, 0.64, 0.69)
    assert profile.chamfer_highlight is True
    assert profile.texture_path is None


def test_skin_manager_loading_and_fallback(tmp_path: Path):
    skins_dir = tmp_path / "skins"
    skins_dir.mkdir()

    # Create a valid custom skin
    skin_folder = skins_dir / "custom-phone"
    skin_folder.mkdir()
    manifest = {
        "id": "custom-phone",
        "name": "Custom Phone",
        "compatible_devices": ["iPhone15,2"],
        "screen": {
            "aspect_ratio": 0.5,
            "corner_radius_ratio": 0.08,
            "has_dynamic_island": True,
            "has_home_bar": False,
        },
        "visuals": {
            "bezel_width_ratio": 0.03,
            "chassis_color": [0.2, 0.2, 0.2],
            "chamfer_highlight": False,
        },
    }
    (skin_folder / "skin.json").write_text(json.dumps(manifest), encoding="utf-8")

    mgr = SkinManager(skins_dir=skins_dir)
    assert "custom-phone" in mgr.available_skins
    custom_skin = mgr.get_skin("custom-phone")
    assert custom_skin.name == "Custom Phone"
    assert custom_skin.aspect_ratio == 0.5
    assert custom_skin.has_home_bar is False
    assert custom_skin.chassis_color == (0.2, 0.2, 0.2)

    # Fallback for unknown skin id
    fallback = mgr.get_skin("non-existent-id")
    assert fallback.id == mgr.default_skin_id


def test_skin_manager_bundled_skins_exist():
    mgr = SkinManager()
    assert "iphone-16-pro-natural" in mgr.available_skins
    assert "iphone-16-pro-black" in mgr.available_skins
    assert "iphone-15" in mgr.available_skins
    assert "stage-manager-clean" in mgr.available_skins

    clean = mgr.get_skin("stage-manager-clean")
    assert clean.bezel_width_ratio == 0.0


def test_skin_manager_device_matching():
    mgr = SkinManager()
    # iPhone16,1 or iPhone16,2 should match iPhone 16 Pro
    skin = mgr.match_device("iPhone16,1")
    assert "16-pro" in skin.id

    # iPhone15,4 should match iPhone 15
    skin_15 = mgr.match_device("iPhone15,4")
    assert "15" in skin_15.id

    # Unknown device falls back to default skin
    fallback = mgr.match_device("UnknownDevice99,9")
    assert fallback.id == mgr.default_skin_id


def test_skin_manager_switching():
    mgr = SkinManager()
    changed_skins = []
    mgr.skin_changed.connect(lambda s: changed_skins.append(s.id))

    assert mgr.active_skin.id == mgr.default_skin_id
    success = mgr.switch_skin("iphone-16-pro-natural")
    assert success is True
    assert mgr.active_skin.id == "iphone-16-pro-natural"
    assert len(changed_skins) == 1
    assert changed_skins[0] == "iphone-16-pro-natural"
