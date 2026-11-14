"""list_strategies tool."""

from langchain_core.tools import BaseTool, tool

from pequod.strategies import StrategyCatalog


def strategy_tools(catalog: StrategyCatalog) -> list[BaseTool]:
    known = sorted({c for s in catalog.for_channel().values() for c in s.channels})

    @tool
    def list_strategies(channel: str | None = None) -> str:
        """List the catalog strategies (id, description, payload, channels), optionally for one channel."""
        if channel is not None and channel not in known:
            return f"Error: Unknown channel '{channel}'. Known channels: {', '.join(known)}"
        return "\n".join(
            f"{name}: {s.description} | payload: {s.payload or 'none'} | channels: {', '.join(s.channels)}"
            for name, s in catalog.for_channel(channel).items()
        )

    return [list_strategies]
