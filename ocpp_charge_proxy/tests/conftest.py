"""Test configuration."""

import pytest

try:
    import pytest_socket
    # pytest-socket is installed — mark all tests to allow sockets
    @pytest.fixture(autouse=True)
    def allow_socket(socket_enabled):
        """Enable socket access for all tests (needed for aiohttp test client)."""
except ImportError:
    # pytest-socket not installed — no fixture needed
    pass
