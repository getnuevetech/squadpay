"""Payment provider adapters (June 2025 — Phase 4+).

This package houses one adapter per integration. Each adapter implements the
contract defined in ``base.py`` (charge) or ``payout_base.py`` (payout).

Selection is dynamic — ``registry.get_charge_adapter()`` / ``get_payout_adapter()``
reads ``gateway_config._ACTIVE_BY_GROUP`` at request time and returns the
matching implementation. Switching providers becomes a single admin DB
flip; zero code change.
"""
