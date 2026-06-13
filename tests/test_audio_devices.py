"""Tests for name-based audio device resolution (Phase 1, item 5).

Pure logic over fake device data — no audio hardware is touched. Covers the two
numbering schemes: PortAudio index for capture, ALSA card id for playback.
"""
import audio_devices


# --- input (PortAudio index) ---------------------------------------------

def test_resolve_input_picks_named_input_capable_device(monkeypatch):
    fake = [
        {"index": 0, "name": "vc4-hdmi-1", "max_input_channels": 0},
        {"index": 5, "name": "Scarlett 2i4 USB", "max_input_channels": 2},
    ]
    monkeypatch.setattr(audio_devices.sd, "query_devices", lambda: fake)
    assert audio_devices.resolve_input_device(name="Scarlett", fallback=1) == 5


def test_resolve_input_skips_a_name_match_with_no_input_channels(monkeypatch):
    # The Scarlett can appear output-only (e.g. while held by another process);
    # it must not be chosen as an input then — fall back instead.
    fake = [{"index": 0, "name": "Scarlett 2i4 USB", "max_input_channels": 0}]
    monkeypatch.setattr(audio_devices.sd, "query_devices", lambda: fake)
    assert audio_devices.resolve_input_device(name="Scarlett", fallback=9) == 9


def test_resolve_input_falls_back_when_name_absent(monkeypatch):
    fake = [{"index": 0, "name": "vc4-hdmi", "max_input_channels": 0}]
    monkeypatch.setattr(audio_devices.sd, "query_devices", lambda: fake)
    assert audio_devices.resolve_input_device(name="Scarlett", fallback=7) == 7


# --- output (ALSA card id) ------------------------------------------------

def test_resolve_output_uses_stable_card_id(monkeypatch):
    monkeypatch.setattr(audio_devices, "_alsa_cards", lambda: [
        (1, "USB", "USB-Audio - Scarlett 2i4 USB"),
        (3, "Device", "USB-Audio - USB PnP Audio Device"),
    ])
    result = audio_devices.resolve_output_device(name="USB PnP Audio Device", fallback=3)
    assert result == "plughw:CARD=Device,DEV=0"


def test_resolve_output_falls_back_to_numeric_index(monkeypatch):
    monkeypatch.setattr(audio_devices, "_alsa_cards", lambda: [(0, "hdmi", "vc4-hdmi")])
    assert audio_devices.resolve_output_device(name="Nonexistent", fallback=3) == "plughw:3,0"
