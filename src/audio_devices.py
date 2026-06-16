"""Resolve audio devices by name so that a USB re-plug or reboot — which can
renumber device indices — doesn't leave Forge deaf (no capture) or mute (no
playback).

Two *different* numbering schemes are involved, which is why there are two
functions:

  * Capture goes through sounddevice / PortAudio, which has its own device
    index. `resolve_input_device()` returns that integer index.
  * Playback goes through `aplay -D plughw:<card>`, which uses the ALSA *card*
    index — a different scheme. `resolve_output_device()` returns a full
    `plughw:CARD=<id>,DEV=0` string, which is keyed on the stable ALSA card id
    rather than a position, so it survives renumbering.

Both fall back to the numeric values configured in settings if a name match
isn't found, so behaviour is unchanged when the names don't match.
"""
import logging
import re

import sounddevice as sd

from config.settings import (
    AUDIO_INPUT_DEVICE,
    AUDIO_OUTPUT_DEVICE,
    AUDIO_INPUT_NAME,
    AUDIO_OUTPUT_NAME,
)

logger = logging.getLogger(__name__)


def resolve_input_device(name=AUDIO_INPUT_NAME, fallback=AUDIO_INPUT_DEVICE):
    """Return the PortAudio index of the first input-capable device whose name
    contains `name` (case-insensitive). Falls back to the configured index."""
    try:
        for device in sd.query_devices():
            if name.lower() in device["name"].lower() and device["max_input_channels"] > 0:
                logger.info(f"Resolved input device to index {device['index']}: {device['name']}")
                return device["index"]
    except Exception as e:
        logger.warning(f"Could not query audio devices for input: {e}")
    logger.info(f"Input device matching '{name}' not found; using configured index {fallback}")
    return fallback


def _alsa_cards():
    """Yield (index, card_id, description) for each card in /proc/asound/cards.

    Example line: " 1 [USB            ]: USB-Audio - Scarlett 2i4 USB"
    -> (1, "USB", "USB-Audio - Scarlett 2i4 USB")
    """
    try:
        text = open("/proc/asound/cards", encoding="utf-8").read()
    except OSError as e:
        logger.warning(f"Could not read /proc/asound/cards: {e}")
        return
    for match in re.finditer(r"^\s*(\d+)\s*\[([^\]]+)\]\s*:\s*(.+)$", text, re.MULTILINE):
        yield int(match.group(1)), match.group(2).strip(), match.group(3).strip()


def resolve_output_device(name=AUDIO_OUTPUT_NAME, fallback=AUDIO_OUTPUT_DEVICE):
    """Return an `aplay -D` device string for the speakers, matched by name.

    Prefers the index-independent `plughw:CARD=<id>,DEV=0` form. Falls back to
    the configured numeric ALSA card index (`plughw:<n>,0`)."""
    name_l = name.lower()
    for _index, card_id, description in _alsa_cards():
        if name_l in description.lower() or name_l in card_id.lower():
            device = f"plughw:CARD={card_id},DEV=0"
            logger.info(f"Resolved output device to {device} ({description})")
            return device
    device = f"plughw:{fallback},0"
    logger.info(f"Output device matching '{name}' not found; using {device}")
    return device
