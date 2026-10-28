"""Share links: how one `protocol://...` line becomes one outbound.

A subscription hands out links, not configurations, so something has to translate. That
translation is the only part of the pipeline that has to know each protocol's quirks, and
it is kept here rather than in the capabilities so a protocol never sees a preset, a fact,
or another node.

Subclasses register on definition, the same way `Capability` does. The previous pipeline
kept a hand-written table of parsers, which meant adding a protocol required editing a
second file, and forgetting it produced "unsupported protocol" at runtime with nothing to
catch it. Here the protocol that exists is registered.

What a parser produces is deliberately small: the tag the node should carry and the
outbound body exactly as sing-box wants it. Everything the compiler does with nodes - the
deduplication key, the tag collision rules, the merge into a group - follows from those two
fields and needs no protocol knowledge at all.
"""

from __future__ import annotations

import base64
import binascii
import importlib
import json
import pkgutil
from dataclasses import dataclass
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qs, unquote

REGISTRY: dict[str, type["Protocol"]] = {}

_loaded = False


class LinkError(Exception):
    """A share link cannot be turned into an outbound."""


@dataclass(frozen=True)
class Node:
    """One outbound discovered in a subscription."""

    tag: str
    outbound: Mapping[str, Any]

    @property
    def dedup_key(self) -> str:
        """What makes two links the same node: the outbound body, tag aside.

        Protocol, host and port are not enough to tell nodes apart. A panel can front a
        whole list of exits through one host and one port and distinguish them only by the
        path of their WebSocket transport; on a live subscription of 41 links there were
        two hosts, one port and 41 paths, so keying on the triple kept two nodes and
        dropped 39 that sing-box would happily have used.

        Two links are the same node exactly when sing-box would treat them as the same
        outbound, so the comparison is the body itself, canonicalised. Credentials are part
        of it for the same reason: a second password on one server is a second account, not
        a repeat of the first.
        """
        return json.dumps(self.outbound, sort_keys=True, default=str, separators=(",", ":"))

    def as_dict(self) -> dict[str, Any]:
        """The node in the nodes.json form: the outbound body with its tag folded in."""
        return {"tag": self.tag, **self.outbound}


class Protocol:
    """A share-link scheme. Subclasses register themselves on definition."""

    #: the scheme this parser answers to, written without "://"
    scheme: str = ""
    #: other schemes that produce the same outbound
    aliases: tuple[str, ...] = ()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for name in (cls.scheme, *cls.aliases):
            if not name:
                continue
            existing = REGISTRY.get(name)
            if existing is not None and existing is not cls:
                raise LinkError(
                    f"duplicate link scheme {name!r}: "
                    f"{existing.__module__}.{existing.__name__} and "
                    f"{cls.__module__}.{cls.__name__}"
                )
            REGISTRY[name] = cls

    def parse(self, payload: str) -> Node:
        """Turn the part after `scheme://` into a node."""
        raise NotImplementedError

    def node(self, tag: str, body: Mapping[str, Any]) -> Node:
        """Build a node, refusing one that sing-box or the dedup key could not use.

        Every outbound needs these three fields, and a parser that omits one produces a
        configuration that only fails at startup, on the device. Checking here names the
        protocol instead.

        The message names the missing fields but never echoes the body: it holds the
        password or UUID, and this text ends up in build logs.
        """
        missing = [
            name
            for name in ("type", "server", "server_port")
            if body.get(name) in (None, "", 0)
        ]
        if missing:
            raise LinkError(f"{self.scheme} link has no usable {', '.join(missing)}")
        if not isinstance(body.get("server_port"), int):
            raise LinkError(f"{self.scheme} link has a non-numeric server_port")
        if not tag.strip():
            tag = f"{body['type']}-{body['server']}:{body['server_port']}"
        return Node(tag=tag.strip(), outbound=dict(body))


def decode_base64(text: str) -> str | None:
    """Decode base64, tolerating missing padding, whitespace and the URL-safe alphabet.

    Subscriptions are pasted by hand and re-encoded by whoever runs the panel, so all three
    variations turn up. Anything that does not decode returns None: callers use this to ask
    "is this base64?", not to validate input, and an exception would make that awkward.
    """
    compact = "".join(text.split())
    if not compact:
        return None
    padding = len(compact) % 4
    if padding:
        compact += "=" * (4 - padding)
    try:
        if "-" in compact or "_" in compact:
            raw = base64.urlsafe_b64decode(compact)
        else:
            raw = base64.b64decode(compact, validate=True)
        return raw.decode("utf-8")
    except (binascii.Error, ValueError):
        return None


def split_tag(payload: str) -> tuple[str, str]:
    """Separate the `#fragment` that a share link uses as its display name."""
    if "#" not in payload:
        return payload, ""
    body, _, fragment = payload.rpartition("#")
    return body, unquote(fragment).strip()


def query_parameters(query: str) -> dict[str, str]:
    """First value of every query parameter, with blank ones dropped."""
    return {
        key: values[0].strip()
        for key, values in parse_qs(query, keep_blank_values=False).items()
        if values
    }


def discover(package: str = "sing_presets.protocols") -> list[str]:
    """Import every module in the protocols package so its parsers register.

    Importing the package once is enough and is idempotent; the modules it imports are
    cached by the interpreter, so calling this on every parse costs a dict lookup.
    """
    global _loaded
    imported: list[str] = []
    try:
        root = importlib.import_module(package)
    except ModuleNotFoundError:
        return imported
    for module in pkgutil.iter_modules(root.__path__):
        if module.name.startswith("_"):
            continue
        importlib.import_module(f"{package}.{module.name}")
        imported.append(module.name)
    _loaded = True
    return sorted(imported)


def parse_link(link: str) -> Node:
    """Parse one share link, or raise LinkError saying why it cannot be used."""
    if not _loaded:
        discover()

    text = link.strip()
    scheme, separator, payload = text.partition("://")
    scheme = scheme.strip().lower()
    if not separator:
        raise LinkError(f"not a share link: {text[:40]!r}")
    parser = REGISTRY.get(scheme)
    if parser is None:
        known = ", ".join(sorted(REGISTRY)) or "(none)"
        raise LinkError(f"no parser for scheme {scheme!r}; known: {known}")
    if not payload.strip():
        raise LinkError(f"{scheme} link has no payload")

    try:
        return parser().parse(payload)
    except LinkError:
        raise
    except (ValueError, TypeError, KeyError) as error:
        # urlparse and int() raise for malformed links. A subscription is full of them, and
        # one bad link must not take the whole build down, so it is reported as a skip.
        raise LinkError(f"{scheme} link cannot be parsed: {error}") from error


def parse_links(links: Iterable[str]) -> tuple[list[Node], list[str]]:
    """Parse many links, collecting the failures instead of stopping at the first."""
    nodes: list[Node] = []
    problems: list[str] = []
    for link in links:
        try:
            nodes.append(parse_link(link))
        except LinkError as error:
            problems.append(str(error))
    return nodes, problems
