"""Hydra entry: build objects, run the loop."""

from pathlib import Path

import hydra
from dotenv import load_dotenv
from omegaconf import DictConfig, OmegaConf

# Absolute: as a console script, Hydra reads a relative config_path as a package.
CONFIGS = str(Path(__file__).parents[2] / "configs")


@hydra.main(version_base=None, config_path=CONFIGS, config_name="config")
def main(cfg: DictConfig) -> None:
    load_dotenv()  # API keys and credentials from .env
    print(OmegaConf.to_yaml(cfg))
