"""Shared fixtures. pytest-homeassistant-custom-component provides `hass`."""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load custom_components/ecoflow_cloud in every test."""
    yield
