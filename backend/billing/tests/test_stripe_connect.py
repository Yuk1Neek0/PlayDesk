"""Tests for the Stripe Connect onboarding views (task #179)."""

from __future__ import annotations

from unittest import mock

import pytest
from django.test import Client, override_settings


@pytest.mark.django_db
class TestConnectEndpoint:
    def test_503_when_misconfigured_in_live_mode(self, store):
        # Live mode + no key → must 503, not silently 200.
        with (
            override_settings(STRIPE_SECRET_KEY=""),
            mock.patch.dict("os.environ", {"STRIPE_TEST_MODE": "False"}, clear=False),
            mock.patch.dict("os.environ", {"STRIPE_SECRET_KEY": ""}, clear=False),
        ):
            resp = Client().post(
                "/api/admin/stripe/connect/",
                content_type="application/json",
                HTTP_X_PD_STORE_SLUG=store.slug,
            )
        assert resp.status_code == 503

    def test_test_mode_unconfigured_returns_stub(self, store):
        with (
            override_settings(STRIPE_SECRET_KEY=""),
            mock.patch.dict(
                "os.environ",
                {"STRIPE_TEST_MODE": "True", "STRIPE_SECRET_KEY": ""},
                clear=False,
            ),
        ):
            resp = Client().post(
                "/api/admin/stripe/connect/",
                content_type="application/json",
                HTTP_X_PD_STORE_SLUG=store.slug,
            )
        assert resp.status_code == 200
        assert resp.json()["configured"] is False

    def test_creates_account_when_none_exists(self, store):
        fake_account = mock.Mock(id="acct_new")
        fake_link = mock.Mock(url="https://stripe.test/onboard/abc")
        with (
            override_settings(STRIPE_SECRET_KEY="sk_test_x"),
            mock.patch("stripe.Account.create", return_value=fake_account) as account_create,
            mock.patch("stripe.AccountLink.create", return_value=fake_link),
        ):
            resp = Client().post(
                "/api/admin/stripe/connect/",
                content_type="application/json",
                HTTP_X_PD_STORE_SLUG=store.slug,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["onboarding_url"] == "https://stripe.test/onboard/abc"
        assert body["account_id"] == "acct_new"
        store.refresh_from_db()
        assert store.stripe_account_id == "acct_new"
        account_create.assert_called_once()

    def test_reuses_existing_account_id(self, store):
        store.stripe_account_id = "acct_existing"
        store.save()
        fake_link = mock.Mock(url="https://stripe.test/onboard/xyz")
        with (
            override_settings(STRIPE_SECRET_KEY="sk_test_x"),
            mock.patch("stripe.Account.create") as account_create,
            mock.patch("stripe.AccountLink.create", return_value=fake_link),
        ):
            resp = Client().post(
                "/api/admin/stripe/connect/",
                content_type="application/json",
                HTTP_X_PD_STORE_SLUG=store.slug,
            )
        assert resp.status_code == 200
        account_create.assert_not_called()
        assert resp.json()["account_id"] == "acct_existing"


@pytest.mark.django_db
class TestReturnEndpoint:
    def test_refreshes_charges_enabled(self, store):
        store.stripe_account_id = "acct_y"
        store.save()
        fake_account = mock.Mock(charges_enabled=True)
        with (
            override_settings(STRIPE_SECRET_KEY="sk_test_x"),
            mock.patch("stripe.Account.retrieve", return_value=fake_account) as retrieve,
        ):
            resp = Client().get(f"/api/admin/stripe/return/?store={store.slug}")
        assert resp.status_code in (301, 302)
        store.refresh_from_db()
        assert store.stripe_charges_enabled is True
        retrieve.assert_called_once_with("acct_y")


@pytest.mark.django_db
class TestStatusEndpoint:
    def test_returns_current_config(self, store):
        store.stripe_account_id = "acct_z"
        store.stripe_charges_enabled = True
        store.save()
        resp = Client().get("/api/admin/stripe/status/", HTTP_X_PD_STORE_SLUG=store.slug)
        assert resp.status_code == 200
        body = resp.json()
        assert body["account_id"] == "acct_z"
        assert body["charges_enabled"] is True


@pytest.mark.django_db
class TestSettingsUpdate:
    def test_patches_deposit_and_matrix(self, store):
        payload = {
            "deposit_mode": "percentage",
            "deposit_value": "30",
            "refund_matrix": [
                {"min_hours": 48, "refund_pct": 100},
                {"min_hours": 0, "refund_pct": 0},
            ],
        }
        resp = Client().patch(
            "/api/admin/stripe/settings/",
            data=payload,
            content_type="application/json",
            HTTP_X_PD_STORE_SLUG=store.slug,
        )
        assert resp.status_code == 200
        store.refresh_from_db()
        assert store.deposit_mode == "percentage"
        assert str(store.deposit_value) == "30.00"
        assert store.refund_matrix[0]["refund_pct"] == 100

    def test_rejects_bad_matrix(self, store):
        resp = Client().patch(
            "/api/admin/stripe/settings/",
            data={"refund_matrix": "not-a-list"},
            content_type="application/json",
            HTTP_X_PD_STORE_SLUG=store.slug,
        )
        assert resp.status_code == 400
