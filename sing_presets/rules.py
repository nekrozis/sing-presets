"""Fold neighbouring rules that share an outcome into one rule.

`route.rules` and `dns.rules` are matched first-match-wins, so two rules in a row that do the
same thing are one decision stated twice: the domestic name rule and the domestic address
rule both mean "direct", and saying it twice costs a second pass over a rule set. Folding
them changes nothing about what matches, because no other rule could have run in between.

Which fields are conditions is not listed here. A logical sub-rule accepts conditions and
nothing else, so the surface has already answered the question - `route.rules[].rules[]` and
`dns.rules{tag}.rules[]` are the schema saying exactly what a branch may hold - and that
answer follows the release when the surface is regenerated. Everything else in a rule is part
of its action and is hoisted unchanged, so a field the schema does not offer as a condition
keeps two rules apart instead of merging them on a guess.

The fold happens on the assembled configuration rather than on contributions, because
adjacency belongs to the finished list: two capabilities may each contribute one of the
rules, and the ranks decide whether they end up next to each other.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .surface import Surface

#: Each ordered rule list, and the path that describes one rule nested inside a rule. The
#: nested path is where the condition fields come from.
_NESTED_RULES = {
    "route.rules": "route.rules[].rules[]",
    "dns.rules": "dns.rules{tag}.rules[]",
}

#: Fields that describe the nesting itself rather than a condition of it.
_NESTING = frozenset({"type", "mode", "rules"})


def _condition_fields(surface: Surface, nested: str) -> frozenset[str]:
    return frozenset(surface.fields_below(nested)) - _NESTING


def _split(
    rule: Mapping[str, Any], conditions: frozenset[str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    action = {key: value for key, value in rule.items() if key not in conditions}
    condition = {key: value for key, value in rule.items() if key in conditions}
    return action, condition


def _splittable(rule: Any, conditions: frozenset[str]) -> bool:
    """Whether a rule can become one branch of an `or` group.

    A logical rule is already a group, and nesting one inside another buys nothing. A rule
    with no condition at all matches everything, so it would swallow the neighbours it was
    grouped with rather than branch beside them.
    """
    return (
        isinstance(rule, dict)
        and rule.get("type") != "logical"
        and "rules" not in rule
        and any(key in conditions for key in rule)
    )


def _group(rules: Sequence[dict[str, Any]], conditions: frozenset[str]) -> dict[str, Any]:
    """One rule for a run that shares an action.

    Rules stating the same condition collapse into one, which is the duplicate a capability
    listed twice leaves behind; distinct conditions become the branches of a logical `or`.
    The action is hoisted, because a branch holds conditions only.
    """
    if len(rules) == 1:
        return rules[0]
    branches: list[dict[str, Any]] = []
    for rule in rules:
        branch = _split(rule, conditions)[1]
        if branch not in branches:
            branches.append(branch)
    if len(branches) == 1:
        return rules[0]
    action = _split(rules[0], conditions)[0]
    return {**action, "type": "logical", "mode": "or", "rules": branches}


def _fold(rules: Sequence[Any], conditions: frozenset[str]) -> list[Any]:
    folded: list[Any] = []
    run: list[dict[str, Any]] = []

    def flush() -> None:
        if run:
            folded.append(_group(run, conditions))
            run.clear()

    for rule in rules:
        if not _splittable(rule, conditions):
            flush()
            folded.append(rule)
            continue
        if run and _split(run[-1], conditions)[0] != _split(rule, conditions)[0]:
            flush()
        run.append(rule)
    flush()
    return folded


def merge_adjacent_rules(surface: Surface, config: dict) -> dict:
    """Fold every run of neighbouring rules that share an action into one rule.

    The audit compares unmerged builds on purpose. It asks what a capability contributes and
    what is left once it is switched off; a rule that ships as a branch of someone else's
    group would answer that question about a shape the contribution never had.
    """
    for path, nested in _NESTED_RULES.items():
        section, _, name = path.partition(".")
        container = config.get(section)
        if not isinstance(container, dict):
            continue
        rules = container.get(name)
        if isinstance(rules, list):
            container[name] = _fold(rules, _condition_fields(surface, nested))
    return config
