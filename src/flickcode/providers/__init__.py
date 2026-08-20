"""Provider factory and exports."""

from flickcode.providers.base import BaseProvider, Message, StreamEvent

__all__ = ["BaseProvider", "Message", "StreamEvent", "create_provider"]


def create_provider(config: "ProviderConfig", client=None) -> BaseProvider:
    """Create a provider instance based on the given configuration.

    Args:
        config: Provider configuration.

    Returns:
        An initialized provider instance.

    Raises:
        ValueError: If the protocol is unsupported.
    """
    protocol = config.protocol

    if protocol == "anthropic":
        from flickcode.providers.anthropic import AnthropicProvider

        return AnthropicProvider(config, client=client)

    if protocol == "openai":
        from flickcode.providers.openai import OpenAIProvider

        return OpenAIProvider(config, client=client)

    raise ValueError(
        f"Unsupported protocol: '{protocol}'. "
        f"Supported values: anthropic, openai."
    )


# Late import for type hint
from flickcode.config import ProviderConfig  # noqa: E402, F401
