"""Human-readable sizes, durations and size comparisons. All numbers come from real files."""
from __future__ import annotations

from dataclasses import dataclass

_UNITS = {
    "ru": ("Б", "КБ", "МБ", "ГБ"),
    "en": ("B", "KB", "MB", "GB"),
}


def format_size(size: int, lang: str = "en") -> str:
    units = _UNITS.get(lang, _UNITS["en"])
    value = float(max(size, 0))
    for unit in units[:-1]:
        if value < 1024:
            return f"{int(value)} {unit}" if unit == units[0] else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} {units[-1]}"


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return ""
    total = int(round(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


@dataclass(frozen=True)
class SizeComparison:
    original: int
    result: int

    @property
    def saved(self) -> int:
        """Positive when the result is smaller, negative when it grew."""
        return self.original - self.result

    @property
    def reduction_percent(self) -> float:
        if self.original <= 0:
            return 0.0
        return round(self.saved / self.original * 100, 1)

    @property
    def is_smaller(self) -> bool:
        return self.result < self.original


def compare_sizes(original: int, result: int) -> SizeComparison:
    if original < 0 or result < 0:
        raise ValueError("sizes must be non-negative")
    return SizeComparison(original=original, result=result)
