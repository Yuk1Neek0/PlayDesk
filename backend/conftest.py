"""Root conftest for the PlayDesk backend test suite.

v10a staff-auth — ``/api/admin/*`` URLs are now gated by
``StaffOnlyMiddleware`` which returns 401 for anonymous requests. The
existing test suite was written before there was any real auth and
hits admin endpoints with the plain Django test client. To keep that
suite green:

  - The ``client`` fixture is overridden so the default test client
    is pre-staff-authenticated (covers the ~30 admin-hitting tests
    that use the fixture).
  - ``make_staff_client(Client_cls)`` is exposed for the handful of
    tests that construct a fresh ``Client()`` / ``APIClient()`` inline
    (billing/tests/*, tests/test_api_rest.py).
  - ``anon_client`` is the escape hatch for tests that must drive an
    unauthenticated request (staff-auth tests + customer-portal auth
    tests).

Tests that want a specific staff user (e.g. for ``CustomerNote.author``
attribution) keep using the standard ``client.force_login(my_user)``
pattern — that swaps the session out cleanly.

Customer-facing endpoints (``/api/me/*``, ``/api/quote/``,
``/api/c/<token>/``, ``/api/bookings/``) are NOT gated by the staff
middleware, so attaching a staff session to those test calls is harmless.
"""

import pytest

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


# ---------------------------------------------------------------------------
# Staff-auth fixtures (v10a)
# ---------------------------------------------------------------------------


@pytest.fixture
def staff_user(db):
    """A shared staff user for `/api/admin/*` test calls.

    Idempotent within a single test DB — ``get_or_create`` keeps the
    row stable across the fixture's repeated instantiations.
    ``test_staff`` is intentionally short and distinct from the seeded
    ``playdesk_staff`` user so a real ``seed_data`` run can't collide
    with test fixtures.
    """
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user, _ = User.objects.get_or_create(
        username="test_staff",
        defaults={"is_staff": True, "is_active": True},
    )
    # Ensure the row's flags + password are exactly what tests expect
    # even if a prior test promoted/demoted the same row.
    user.set_password("test_staff_pw")
    user.is_staff = True
    user.is_active = True
    user.save()
    return user


@pytest.fixture
def anon_client():
    """Unauthenticated Django test client.

    Use this in tests that exercise the 401/403 behaviour of the staff
    middleware, or in customer-side tests that want to assert "no staff
    session" preconditions. The default ``client`` fixture in this
    project is pre-staff-logged-in; ``anon_client`` is a fresh client
    with no session.
    """
    from django.test import Client

    return Client()


@pytest.fixture
def staff_client(staff_user):
    """Django test client pre-logged-in as the shared `test_staff` user.

    The default ``client`` fixture (see below) returns this same
    pre-authenticated client — ``staff_client`` exists as a named
    alias for tests that want to be explicit about the precondition.
    """
    from django.test import Client

    c = Client()
    c.force_login(staff_user)
    return c


# pytest-django ships a `client` fixture returning an unauthenticated
# Django test client. We override it here so the default test client
# is pre-authenticated as the shared staff user. This keeps the
# migration path for the ~14 admin-hitting test files at zero lines
# of change, while leaving an `anon_client` escape hatch for tests
# that need the un-authenticated baseline (notably the staff-auth
# tests themselves and customer-portal auth tests).
@pytest.fixture
def client(staff_client):  # noqa: F811 — intentionally shadows pytest-django
    return staff_client


# ---------------------------------------------------------------------------
# Helper for tests that construct Client() / APIClient() directly
# ---------------------------------------------------------------------------
#
# A handful of tests (billing/tests/*, tests/test_api_rest.py, etc.)
# construct a fresh Django ``Client()`` or DRF ``APIClient()`` inline
# rather than asking for the ``client`` / ``api_client`` fixtures.
# After v10a those calls hit ``/api/admin/*`` anonymously and get 401
# from ``StaffOnlyMiddleware``. ``make_staff_client(...)`` wraps any
# fresh client with a ``force_login(test_staff)`` call — fixture-free
# so it composes naturally inside ``with override_settings(...):``
# blocks.


def make_staff_client(client_cls):
    """Return a freshly-constructed test client pre-logged-in as test_staff.

    ``client_cls`` is the class (``django.test.Client`` or
    ``rest_framework.test.APIClient``) — passing the class instead of
    an instance lets the caller import whichever flavour the tests
    already use.
    """
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user, _ = User.objects.get_or_create(
        username="test_staff",
        defaults={"is_staff": True, "is_active": True},
    )
    user.is_staff = True
    user.is_active = True
    user.save()
    c = client_cls()
    c.force_login(user)
    return c
