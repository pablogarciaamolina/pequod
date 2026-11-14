import pytest
from hydra import compose, initialize_config_dir
from omegaconf import OmegaConf

from pequod.main import CONFIGS


def load(overrides=()):
    with initialize_config_dir(config_dir=CONFIGS, version_base=None):
        return compose(config_name="config", overrides=list(overrides))


@pytest.fixture
def cfg():
    return load()


@pytest.fixture
def engagement(cfg):
    from pequod.types import Engagement

    return Engagement.model_validate(OmegaConf.to_container(cfg.engagement))
