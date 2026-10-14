"""Exact editorial duration targets. No media processing or platform assumptions."""
from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class DurationPreset:
    key: str
    label: str
    min_seconds: float
    max_seconds: float
    max_inclusive: bool = False

    def contains(self, duration: float) -> bool:
        value = finite_seconds(duration, "duration")
        return (value > 0 and value >= self.min_seconds
                and (value <= self.max_seconds if self.max_inclusive else value < self.max_seconds))


DURATION_PRESETS = (
    DurationPreset("auto_under_90", "Auto (<90s)", 0, 90),
    DurationPreset("under_30", "<30s", 0, 30),
    DurationPreset("from_30_to_59", "30s~59s", 30, 60),
    DurationPreset("from_60_to_89", "60s~89s", 60, 90),
    DurationPreset("from_90_to_180", "90s~3m", 90, 180),
    DurationPreset("from_180_to_300", "3m~5m", 180, 300),
    DurationPreset("from_300_to_600", "5m~10m", 300, 600),
    DurationPreset("from_600_to_900", "10m~15m", 600, 900, True),
)
DEFAULT_DURATION_PRESET = "auto_under_90"


def finite_seconds(value, name="time") -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} deve ser um número finito em segundos")
    return float(value)


def get_preset(key=DEFAULT_DURATION_PRESET) -> DurationPreset:
    for preset in DURATION_PRESETS:
        if key in (preset.key, preset.label):
            return preset
    raise ValueError(f"Preset de duração desconhecido: {key}")


def validate_window(start, end, source_duration) -> float:
    start = finite_seconds(start, "source_start")
    end = finite_seconds(end, "source_end")
    total = finite_seconds(source_duration, "source_duration")
    if not 0 <= start < end <= total:
        raise ValueError("Intervalo deve estar dentro da fonte e ter duração positiva")
    return end - start


def duration_metadata(key, duration) -> dict:
    preset = get_preset(key)
    value = finite_seconds(duration, "duration")
    if value <= 0:
        raise ValueError("A duração deve ser positiva")
    within = preset.contains(value)
    return {
        "duration_preset": preset.key,
        "duration_label": preset.label,
        "duration_min_seconds": preset.min_seconds,
        "duration_min_inclusive": preset.min_seconds > 0,
        "duration_max_seconds": preset.max_seconds,
        "duration_max_inclusive": preset.max_inclusive,
        "actual_duration_seconds": value,
        "duration_within_target": within,
        "requested_duration": preset.label,
        "proposed_duration": value,
        "preview_duration": None,
        "rendered_duration": None,
        "duration_deviation_reason": None if within else (
            "Conteúdo comprovado menor que o mínimo; não foi preenchido artificialmente."
            if value < preset.min_seconds else
            "Unidade de fala/pergunta e resposta preservada além da faixa; revisão humana necessária."
        ),
        "encoding_tolerance_seconds": None,
        "duration_verified_by_ffprobe": False,
    }
