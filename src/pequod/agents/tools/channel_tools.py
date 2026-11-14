"""channel_rules tool."""

from langchain_core.tools import BaseTool, tool

from pequod.types import ChannelRules


def channel_tools(rules: dict[str, ChannelRules]) -> list[BaseTool]:
    @tool
    def channel_rules(channel: str) -> str:
        """Return the message rules of a channel: max length, whether it has a subject, whether links are ok."""
        if channel not in rules:
            return f"Error: Unknown channel '{channel}'. Known channels: {', '.join(rules)}"
        r = rules[channel]
        return f"{channel}: max_length={r.max_length}, subject={r.subject}, links_ok={r.links_ok}"

    return [channel_rules]
