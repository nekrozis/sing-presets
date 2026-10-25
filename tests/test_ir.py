"""Tests for the IR merge algebra and the capability model.

These pin down the semantics that the whole design rests on: merging by tag, ordering by
anchor, conflict resolution by priority, and the refusal to write outside the field
surface.
"""

from __future__ import annotations

import pytest

from sing_presets import capability as cap
from sing_presets.facts import Facts, FactsError
from sing_presets.ir import (
    Anchor,
    Builder,
    Entry,
    IRError,
    Member,
    Position,
    Setting,
    compile_config,
    flatten,
)
from sing_presets.surface import Surface, SurfaceError


@pytest.fixture(scope="module")
def surface() -> Surface:
    return Surface.load()


# ------------------------------------------------------------------ field surface


def test_surface_loads_and_records_version(surface: Surface) -> None:
    assert len(surface) > 1000
    assert surface.binary_version == "1.14.4"
    assert "outbounds" in surface.top_level()


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        ("outbounds", "map_tag"),
        ("inbounds", "map_tag"),
        ("dns.servers", "map_tag"),
        ("route.rule_set", "map_tag"),
        ("route.rules", "seq"),
        ("dns.rules", "seq_tagged"),
        ("outbounds{tag}.outbounds", "seq"),
        ("dns.strategy", "scalar"),
        ("inbounds{tag}.mtu", "scalar"),
        ("inbounds{tag}.address", "scalar_list"),
    ],
)
def test_slot_kinds(surface: Surface, path: str, kind: str) -> None:
    assert surface.kind_of(path) == kind


def test_dns_rules_is_ordered_not_keyed(surface: Surface) -> None:
    """dns.rules elements carry a tag, but it is a response label, not an identity.

    The criterion is the reference namespace, not the presence of a tag, so dns.rules
    must stay ordered.
    """
    assert surface.kind_of("dns.rules") == "seq_tagged"
    slot = surface.get("dns.rules")
    assert slot is not None
    assert slot.is_ordered


def test_normalize_folds_concrete_tags(surface: Surface) -> None:
    """A concrete tag folds onto the placeholder, so the same slot serves every member."""
    assert surface.kind_of("outbounds{proxy}") == "object"
    assert surface.kind_of("outbounds{proxy}.outbounds") == "seq"
    assert surface.kind_of("dns.servers{dns-direct}.tag") == "scalar"


# ------------------------------------------------------------------ members


def test_members_merge_by_tag_instead_of_duplicating(surface: Surface) -> None:
    builder = Builder(surface)
    builder.add(Member("outbounds", "proxy", {"type": "selector"}, owner="a"))
    builder.add(Member("outbounds", "proxy", {"default": "auto"}, owner="b"))
    config = builder.materialize()
    assert config["outbounds"] == [{"tag": "proxy", "type": "selector", "default": "auto"}]


def test_same_key_with_other_value_is_a_conflict(surface: Surface) -> None:
    builder = Builder(surface)
    builder.add(Member("outbounds", "proxy", {"default": "auto"}, owner="a"))
    builder.add(Member("outbounds", "proxy", {"default": "direct"}, owner="b"))
    (conflict,) = builder.report.conflicts
    assert conflict.path == "outbounds{proxy}.default"
    assert {conflict.existing_owner, conflict.incoming_owner} == {"a", "b"}
    assert builder.materialize()["outbounds"][0]["default"] == "auto"


def test_nested_bodies_merge_recursively(surface: Surface) -> None:
    builder = Builder(surface)
    builder.add(
        Member("outbounds", "n", {"tls": {"enabled": True}}, owner="a")
    )
    builder.add(Member("outbounds", "n", {"tls": {"server_name": "example.com"}}, owner="b"))
    assert builder.materialize()["outbounds"][0]["tls"] == {
        "enabled": True,
        "server_name": "example.com",
    }


# ------------------------------------------------------------------ ordering


def test_positions_are_resolved_with_anchors(surface: Surface) -> None:
    builder = Builder(surface)
    builder.add(Anchor("route.rules", "ads", 200))
    builder.add(Entry("route.rules", "sniff", Position.first(), owner="a"))
    builder.add(Entry("route.rules", "ads-reject", Position.at(200), owner="a"))
    builder.add(Entry("route.rules", "after-ads", Position.after("ads"), owner="a"))
    builder.add(Entry("route.rules", "before-ads", Position.before("ads"), owner="a"))
    builder.add(Entry("route.rules", "fallback", Position.last(), owner="a"))
    assert builder.materialize()["route"]["rules"] == [
        "sniff",
        "before-ads",
        "ads-reject",
        "after-ads",
        "fallback",
    ]


def test_equal_positions_keep_insertion_order(surface: Surface) -> None:
    builder = Builder(surface)
    for name in ("first-added", "second-added", "third-added"):
        builder.add(Entry("route.rules", name, Position.at(10), owner="a"))
    assert builder.materialize()["route"]["rules"] == [
        "first-added",
        "second-added",
        "third-added",
    ]


def test_undeclared_anchor_is_rejected(surface: Surface) -> None:
    builder = Builder(surface)
    builder.add(Entry("route.rules", "x", Position.after("nope"), owner="a"))
    with pytest.raises(IRError, match="undeclared anchor"):
        builder.materialize()


def test_seq_inside_a_member_can_be_extended_from_another_owner(surface: Surface) -> None:
    """This is the slot the old _PROXY_TAGS_ macro was standing in for."""
    builder = Builder(surface)
    builder.add(Member("outbounds", "auto", {"type": "urltest", "outbounds": []}, owner="a"))
    builder.add(Entry("outbounds{auto}.outbounds", "node-jp", owner="nodes"))
    builder.add(Entry("outbounds{auto}.outbounds", "node-sg", owner="nodes"))
    auto = builder.materialize()["outbounds"][0]
    assert auto["outbounds"] == ["node-jp", "node-sg"]


# ------------------------------------------------------------------ scalars


def test_higher_priority_wins_a_scalar(surface: Surface) -> None:
    builder = Builder(surface)
    builder.add(Setting("dns.strategy", "ipv4_only", priority=20, owner="a"))
    builder.add(Setting("dns.strategy", "prefer_ipv6", priority=30, owner="b"))
    assert builder.materialize()["dns"]["strategy"] == "prefer_ipv6"
    assert builder.report.conflicts == []


def test_equal_priority_with_different_values_conflicts(surface: Surface) -> None:
    builder = Builder(surface)
    builder.add(Setting("route.final", "proxy", priority=10, owner="a"))
    builder.add(Setting("route.final", "direct", priority=10, owner="b"))
    assert len(builder.report.conflicts) == 1
    assert builder.materialize()["route"]["final"] == "proxy"


def test_identical_values_do_not_conflict(surface: Surface) -> None:
    builder = Builder(surface)
    builder.add(Setting("route.final", "proxy", priority=10, owner="a"))
    builder.add(Setting("route.final", "proxy", priority=10, owner="b"))
    assert builder.report.conflicts == []


def test_scalar_list_accepts_entries(surface: Surface) -> None:
    builder = Builder(surface)
    builder.add(Member("inbounds", "tun-in", {"type": "tun"}, owner="a"))
    builder.add(Entry("inbounds{tun-in}.address", "172.18.0.1/30", owner="a"))
    builder.add(Entry("inbounds{tun-in}.address", "fc00::1/126", owner="b"))
    assert builder.materialize()["inbounds"][0]["address"] == [
        "172.18.0.1/30",
        "fc00::1/126",
    ]


# ------------------------------------------------------------------ boundaries


def test_unknown_path_is_rejected(surface: Surface) -> None:
    builder = Builder(surface)
    with pytest.raises(SurfaceError, match="not part of the field surface"):
        builder.add(Setting("dns.no_such_field", 1, owner="a"))


def test_wrong_slot_kind_is_rejected(surface: Surface) -> None:
    builder = Builder(surface)
    with pytest.raises(SurfaceError, match="slot kind"):
        builder.add(Member("route.rules", "not-a-collection", {}, owner="a"))


def test_check_config_flags_a_typo(surface: Surface) -> None:
    unknown = surface.check_config({"dns": {"stratgy": "ipv4_only"}})
    assert unknown == ["dns.stratgy"]


def test_check_config_accepts_a_real_config(surface: Surface) -> None:
    config = {
        "log": {"level": "info"},
        "dns": {"strategy": "ipv4_only", "servers": [{"tag": "d", "type": "tls"}]},
        "inbounds": [{"tag": "tun-in", "type": "tun", "mtu": 9000}],
        "outbounds": [{"tag": "p", "type": "selector", "outbounds": ["auto"]}],
        "route": {"rules": [{"action": "sniff"}], "final": "p"},
    }
    assert surface.check_config(config) == []


# ------------------------------------------------------------------ isolation


def test_isolation_passes_for_independent_capabilities(surface: Surface) -> None:
    contributions = [
        Member("inbounds", "tun-in", {"type": "tun"}, owner="tun-base"),
        Setting("route.final", "proxy", priority=10, owner="proxy-group"),
        Entry("route.rules", {"action": "sniff"}, Position.first(), owner="proxy-group"),
    ]
    assert Builder(surface).verify_isolation(contributions) == []


def test_isolation_detects_a_dependency(surface: Surface) -> None:
    contributions = [
        Member("outbounds", "auto", {"type": "urltest", "outbounds": []}, owner="proxy-group"),
        Entry("outbounds{auto}.outbounds", "node", owner="nodes"),
    ]
    problems = Builder(surface).verify_isolation(contributions)
    assert any("depend" in problem for problem in problems)


def test_isolation_detects_shadowing(surface: Surface) -> None:
    """A low-priority contributor is silently shadowed until the high one is disabled."""
    contributions = [
        Setting("route.final", "proxy", priority=30, owner="strong"),
        Setting("route.final", "direct", priority=10, owner="weak"),
    ]
    problems = Builder(surface).verify_isolation(contributions)
    assert any("change value" in problem for problem in problems)


# ------------------------------------------------------------------ capabilities


class _Sample(cap.Capability):
    abstract = True
    id = "sample"


def test_capability_registers_itself() -> None:
    class Registered(cap.Capability):
        id = "test-registers-itself"

        def contribute(self, facts: Facts):
            return []

    assert cap.REGISTRY["test-registers-itself"] is Registered


def test_duplicate_capability_id_is_rejected() -> None:
    with pytest.raises(cap.CapabilityError, match="duplicate capability id"):

        class Duplicate(cap.Capability):
            id = "test-registers-itself"

            def contribute(self, facts: Facts):
                return []


def test_abstract_bases_do_not_register() -> None:
    assert "sample" not in cap.REGISTRY


def test_owner_is_stamped_automatically() -> None:
    class Stamped(cap.Capability):
        id = "test-owner-stamp"

        def contribute(self, facts: Facts):
            yield self.setting("route.final", "proxy")

    (contribution,) = Stamped().contributions(Facts())
    assert contribution.owner == "test-owner-stamp"


def test_missing_fact_fails_loudly() -> None:
    class NeedsFact(cap.Capability):
        id = "test-needs-fact"
        requires = ("network.has_public_ipv6",)

        def contribute(self, facts: Facts):
            yield self.setting("route.final", facts.require_bool("network.has_public_ipv6"))

    with pytest.raises(FactsError, match="undeclared facts"):
        NeedsFact().contributions(Facts())


def test_unknown_capability_id_is_reported() -> None:
    with pytest.raises(cap.CapabilityError, match="unknown capability"):
        cap.build_registry(["nope"])


def test_ownership_and_trespass_checks() -> None:
    class Owner(cap.Capability):
        id = "test-owner-a"
        owns = ("outbounds{shared}",)

        def contribute(self, facts: Facts):
            yield self.member("outbounds", "shared", {"type": "selector"})

    class Intruder(cap.Capability):
        id = "test-owner-b"

        def contribute(self, facts: Facts):
            yield self.member("outbounds", "shared", {"default": "x"})

    owner, intruder = Owner(), Intruder()
    assert cap.check_ownership([owner, intruder]) == []
    (problem,) = cap.check_trespass([owner.contributions(Facts())[0],
                                     intruder.contributions(Facts())[0]])
    assert "outbounds{shared}" in problem


def test_flatten_exposes_leaves_for_diffing() -> None:
    leaves = flatten({"route": {"rules": [{"action": "sniff"}, {"action": "reject"}]}})
    assert leaves == {
        "route.rules[0].action": "sniff",
        "route.rules[1].action": "reject",
    }


def test_compile_config_is_a_thin_wrapper(surface: Surface) -> None:
    config, report = compile_config(surface, [Setting("route.final", "proxy", owner="a")])
    assert config == {"route": {"final": "proxy"}}
    assert report.contributions == 1
