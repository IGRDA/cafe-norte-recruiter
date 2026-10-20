"""Loading the two store configurations from ``config/*.yaml`` into ``StoreConfiguration``."""

from pathlib import Path

import yaml

from cafe_norte.domain.contracts import ConfigId, StoreConfiguration


def load_configurations(directory: Path) -> dict[ConfigId, StoreConfiguration]:
    """Parse and validate every configuration file. Fails startup on an invalid file or a
    duplicate id. Checking ``kb_doc_ids`` against the knowledge manifest lands with the
    knowledge stage."""
    configurations: dict[ConfigId, StoreConfiguration] = {}
    for path in sorted(directory.glob("*.yaml")):
        configuration = StoreConfiguration.model_validate(
            yaml.safe_load(path.read_text(encoding="utf-8"))
        )
        if configuration.config_id in configurations:
            raise ValueError(f"duplicate config_id {configuration.config_id} in {path.name}")
        configurations[configuration.config_id] = configuration
    if not configurations:
        raise ValueError(f"no configuration files in {directory}")
    return configurations
