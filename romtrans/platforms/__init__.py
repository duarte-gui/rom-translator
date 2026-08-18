"""Registro de plugins de plataforma."""

from __future__ import annotations

from .base import Detection, PlatformPlugin, PointerSpec
from .gba import GbaPlugin
from .generic import GenericPlugin
from .nes import NesPlugin
from .snes import SnesPlugin

#: ordem importa apenas para desempate; a escolha e por confianca
PLUGINS: list[PlatformPlugin] = [SnesPlugin(), NesPlugin(), GbaPlugin(), GenericPlugin()]

__all__ = ["PLUGINS", "PlatformPlugin", "Detection", "PointerSpec", "identify", "get"]


def get(name: str) -> PlatformPlugin:
    for plugin in PLUGINS:
        if plugin.name == name:
            return plugin
    raise KeyError(f"plataforma desconhecida: {name!r}")


def identify(data: bytes) -> tuple[PlatformPlugin, Detection]:
    """Escolhe o plugin de maior confianca para `data`."""
    best: tuple[PlatformPlugin, Detection] | None = None
    for plugin in PLUGINS:
        det = plugin.detect(bytes(data))
        if det is None:
            continue
        if best is None or det.confidence > best[1].confidence:
            best = (plugin, det)
    assert best is not None, "GenericPlugin deveria sempre casar"
    return best
