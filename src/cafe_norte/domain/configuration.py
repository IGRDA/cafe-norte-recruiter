"""Loading the two store configurations from ``config/*.yaml`` into ``StoreConfiguration``."""

from pathlib import Path

from cafe_norte.domain.contracts import ConfigId, StoreConfiguration


def load_configurations(directory: Path) -> dict[ConfigId, StoreConfiguration]:
    """Parse and validate every configuration file. Fails startup on an invalid one, a duplicate
    id, or a referenced knowledge document that does not exist in the manifest."""
    raise NotImplementedError
