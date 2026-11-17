"""list_strategies tool."""

from langchain_core.tools import BaseTool, tool

from pequod.strategies import StrategyCatalog


def strategy_tools(catalog: StrategyCatalog, platforms: dict[str, str]) -> list[BaseTool]:
    """`platforms` maps each channel name to its platform; strategy allowance is defined
    per platform, so a channel is resolved to its platform before the catalog is filtered."""
    known = sorted(platforms)

    @tool
    def list_strategies(channel: str | None = None) -> str:
        """List the catalog strategies (id, description, payload, platforms), optionally for one channel."""
        if channel is not None and channel not in known:
            return f"Error: Unknown channel '{channel}'. Known channels: {', '.join(known)}"
        platform = platforms[channel] if channel is not None else None
        return "\n".join(
            f"{name}: {s.description} | payload: {s.payload or 'none'} | platforms: {', '.join(s.platforms)}"
            for name, s in catalog.for_platform(platform).items()
        )

    return [list_strategies]
