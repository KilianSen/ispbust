"""Report rendering: analysis in, one self-contained HTML file out."""

from .builder import build_report
from .strings import Strings

__all__ = ["build_report", "Strings"]
