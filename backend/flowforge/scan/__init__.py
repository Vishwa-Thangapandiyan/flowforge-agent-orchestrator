"""The repo scanner (D21): `scan(root) -> ScanResult`. Plain code, read-only, no network and no LLM (D20)."""

from flowforge.scan.models import Dependency, ScanResult
from flowforge.scan.scanner import scan

__all__ = ["Dependency", "ScanResult", "scan"]
