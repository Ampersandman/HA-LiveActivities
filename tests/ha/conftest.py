"""Use the official custom-integration Home Assistant fixtures."""

import pytest


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    """Enable loading custom_components in the real HA test runtime."""
