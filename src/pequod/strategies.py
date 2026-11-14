"""Load strategy catalog."""

from collections.abc import Mapping

from pequod.types import Strategy


class StrategyCatalog:
    """Base catalog of wave actions. A base, not a limit: agents may also describe custom strategies."""

    def __init__(self, strategies: dict[str, Strategy]) -> None:
        self._strategies = strategies

    @classmethod
    def from_config(cls, cfg: Mapping) -> "StrategyCatalog":
        return cls({name: Strategy.model_validate(dict(spec)) for name, spec in cfg.items()})

    def get(self, strategy_id: str) -> Strategy:
        if strategy_id not in self._strategies:
            raise ValueError(f"Unknown strategy '{strategy_id}'. Known strategies: {', '.join(self._strategies)}")
        return self._strategies[strategy_id]

    def for_channel(self, channel: str | None = None) -> dict[str, Strategy]:
        return {k: s for k, s in self._strategies.items() if channel is None or channel in s.channels}
