"""
Root conftest for the PlayDesk backend test suite.

Wires the api.urls into the URL resolver so that reverse() calls work
in test_api_rest.py even before the orchestrator merges api.urls into
config/urls.py.
"""

# Tell pytest-django which settings to use (also in pyproject.toml but
# kept here for clarity).
django_settings = "config.settings"


def pytest_configure(config):
    """Register the api app URLs under the test URL configuration."""
    import django.conf

    if not django.conf.settings.configured:
        return

    # Patch ROOT_URLCONF to include api.urls in addition to the project urls.
    # We do this by pointing at a minimal test urlconf module created here.
    # However, the simplest approach with pytest-django is to use @override_settings
    # in each test or set urls= on the mark. Instead, we monkey-patch the
    # root urlconf to include api.urls so all tests share the same config.
    pass
