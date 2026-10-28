"""Folding neighbouring rules that share an outcome.

The fold is presentation, but its unit is the rule: two rules become one logical rule, so
every test here pins the shape of the result rather than the effect of some later stage.
"""

from __future__ import annotations

import pytest

from sing_presets import rules
from sing_presets.surface import Surface


@pytest.fixture(scope="module")
def surface() -> Surface:
    return Surface.load()


def test_neighbouring_rules_with_one_action_become_one_group(surface: Surface) -> None:
    """Two rules that differ only in what they match are one decision written twice."""
    config = {
        "route": {
            "rules": [
                {"action": "sniff"},
                {"outbound": "direct", "rule_set": ["geosite-cn"]},
                {"outbound": "direct", "rule_set": ["geoip-cn"]},
                {"action": "reject", "rule_set": ["ads"]},
            ]
        }
    }
    assert rules.merge_adjacent_rules(surface, config)["route"]["rules"] == [
        {"action": "sniff"},
        {
            "outbound": "direct",
            "type": "logical",
            "mode": "or",
            "rules": [{"rule_set": ["geosite-cn"]}, {"rule_set": ["geoip-cn"]}],
        },
        {"action": "reject", "rule_set": ["ads"]},
    ]


def test_a_rule_between_the_two_keeps_them_apart(surface: Surface) -> None:
    """First match wins, so only neighbours can be folded: the order is the semantics."""
    config = {
        "route": {
            "rules": [
                {"outbound": "direct", "rule_set": ["geosite-cn"]},
                {"action": "reject", "rule_set": ["ads"]},
                {"outbound": "direct", "rule_set": ["geoip-cn"]},
            ]
        }
    }
    original = [dict(rule) for rule in config["route"]["rules"]]
    assert rules.merge_adjacent_rules(surface, config)["route"]["rules"] == original


def test_a_different_action_is_not_folded(surface: Surface) -> None:
    """Adjacency is not enough: the outcome has to be the same one."""
    config = {
        "dns": {
            "rules": [
                {"server": "dns-direct", "rule_set": ["geosite-cn"]},
                {"server": "dns-remote", "clash_mode": "global"},
            ]
        }
    }
    original = [dict(rule) for rule in config["dns"]["rules"]]
    assert rules.merge_adjacent_rules(surface, config)["dns"]["rules"] == original


def test_identical_neighbours_collapse_to_one_rule(surface: Surface) -> None:
    """The duplicate a capability listed twice leaves behind, folded into one."""
    rule = {"outbound": "direct", "rule_set": ["geosite-cn"]}
    config = {"route": {"rules": [dict(rule), dict(rule), {"action": "sniff"}]}}
    assert rules.merge_adjacent_rules(surface, config)["route"]["rules"] == [
        rule,
        {"action": "sniff"},
    ]


def test_a_dial_option_is_part_of_the_action(surface: Surface) -> None:
    """A branch holds conditions only, so everything else is hoisted and must agree first.

    `tls_fragment` is a field of the action, which the surface says by not offering it to a
    nested rule. Rules that differ in it are not the same decision.
    """
    config = {
        "route": {
            "rules": [
                {"outbound": "direct", "rule_set": ["a"], "tls_fragment": True},
                {"outbound": "direct", "rule_set": ["b"], "tls_fragment": True},
                {"outbound": "direct", "rule_set": ["c"], "tls_fragment": False},
            ]
        }
    }
    assert rules.merge_adjacent_rules(surface, config)["route"]["rules"] == [
        {
            "outbound": "direct",
            "tls_fragment": True,
            "type": "logical",
            "mode": "or",
            "rules": [{"rule_set": ["a"]}, {"rule_set": ["b"]}],
        },
        {"outbound": "direct", "rule_set": ["c"], "tls_fragment": False},
    ]


def test_a_group_is_never_nested_inside_another(surface: Surface) -> None:
    """A logical rule is already a group, and a group of one costs a level for nothing."""
    grouped = {
        "type": "logical",
        "mode": "or",
        "outbound": "direct",
        "rules": [{"rule_set": ["b"]}],
    }
    config = {
        "route": {
            "rules": [
                {"outbound": "direct", "rule_set": ["a"]},
                grouped,
                {"outbound": "direct", "rule_set": ["c"]},
            ]
        }
    }
    original = [dict(rule) for rule in config["route"]["rules"]]
    assert rules.merge_adjacent_rules(surface, config)["route"]["rules"] == original


def test_the_condition_fields_come_from_the_schema(surface: Surface) -> None:
    """The surface, not a list in the code, decides what a branch may hold."""
    conditions = rules._condition_fields(surface, "route.rules[].rules[]")
    assert {"rule_set", "domain", "invert", "port"} <= conditions
    assert conditions.isdisjoint({"outbound", "action", "strategy", "tls_fragment"})
