"""Turning subscription sources into the node list a build consumes.

The three steps are kept apart on purpose. Reading a source is network, extracting links is
text, parsing is pure. Only the first can fail for reasons nobody controls, so the other two
are testable without a server, and a fetch can report exactly what it lost instead of
leaving a shorter node list to be noticed later.

The output is what `sing-presets build --nodes` reads: a JSON document holding outbound
bodies, which is the same shape the subscription capability turns into members.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.request import Request, urlopen

from .capabilities.outbounds import AUTO, DIRECT, PROXY
from .protocol import LinkError, Node, decode_base64, parse_link

#: Sent with every request. A panel decides which format to return from this, and a client
#: it does not recognise gets the plain list of share links, which is what is parsed here.
#: Deliberately not a browser's: pretending to be one asks for a format this code cannot read.
USER_AGENT = "sing-presets/0.1"

#: A share link: a scheme at the start of the line, then at least one more character.
#: Deliberately permissive about which scheme, so an unsupported protocol is reported as
#: "no parser for X" rather than vanishing from a line that used to work. Spaces are allowed
#: after the scheme because the fragment holds the display name, and names like "Tokyo 01"
#: are the norm - requiring a line without spaces silently drops half a subscription.
LINK = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://\S")

#: Tags the compiler writes itself. A node must not take one of these, or the build ends up
#: with two outbounds sharing a tag and sing-box refuses to start.
RESERVED_TAGS = frozenset({DIRECT, AUTO, PROXY})


@dataclass
class Feed:
    """What a fetch produced, and what did not make it through."""

    nodes: list[Node] = field(default_factory=list)
    #: links that parsed to an endpoint already seen, keyed by nothing: only counted
    duplicates: int = 0
    #: reason -> how many links it cost
    skipped: Counter[str] = field(default_factory=Counter)
    sources: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    def payload(self) -> dict[str, Any]:
        return {
            "version": 1,
            "sources": list(self.sources),
            "nodes": [node.as_dict() for node in self.nodes],
        }

    def summary(self) -> str:
        parts = [f"{len(self.nodes)} nodes"]
        if self.duplicates:
            parts.append(f"{self.duplicates} duplicates dropped")
        if self.skipped:
            parts.append(f"{sum(self.skipped.values())} links skipped")
        return ", ".join(parts)


def extract_links(text: str) -> list[str]:
    """Every line that is a share link, in the order it appeared."""
    return [line.strip() for line in text.splitlines() if LINK.match(line.strip())]


def read_source(source: str, timeout: float = 10.0) -> str:
    """Read one source, unwrapping a base64-encoded body.

    Panels hand out subscriptions both as a plain list of links and as the same list in
    base64, and the choice is not visible from the URL, so both are accepted. A local path
    is read as a file, which is how a hand-made list and the tests work.
    """
    if source.startswith(("http://", "https://")):
        request = Request(source, headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8", errors="replace")
    else:
        text = Path(source).read_text(encoding="utf-8")

    text = text.strip()
    decoded = decode_base64(text)
    return decoded if decoded is not None else text


def unique_tags(nodes: Iterable[Node]) -> list[Node]:
    """Give every node a tag no other node uses.

    A subscription is free to contain the same display name twice, and sing-box refuses a
    configuration with two outbounds sharing a tag, so the collision is resolved here rather
    than failing the build. The tags the compiler writes itself are reserved: a node called
    "proxy" would otherwise shadow the selector and take the whole group down with it.
    """
    used: set[str] = set(RESERVED_TAGS)
    result: list[Node] = []
    for node in nodes:
        base = node.tag
        tag = base
        suffix = 2
        while tag in used:
            tag = f"{base} ({suffix})"
            suffix += 1
        used.add(tag)
        result.append(replace(node, tag=tag))
    return result


def collect(texts: Iterable[str], feed: Feed | None = None) -> Feed:
    """Parse every link in the given texts, dropping duplicates.

    First one wins for a duplicate key: subscriptions list their preferred entry first often
    enough that the alternative - last wins - would be arbitrary.
    """
    feed = Feed() if feed is None else feed
    seen: set[tuple[str, str, int]] = set()
    collected: list[Node] = []

    for text in texts:
        for link in extract_links(text):
            try:
                node = parse_link(link)
            except LinkError as error:
                feed.skipped[str(error)] += 1
                continue
            if node.dedup_key in seen:
                feed.duplicates += 1
                continue
            seen.add(node.dedup_key)
            collected.append(node)

    feed.nodes = unique_tags(collected)
    return feed


def fetch(sources: Sequence[str], timeout: float = 10.0) -> Feed:
    """Read every source and turn their links into nodes.

    A source that cannot be read is recorded and skipped rather than raised: one dead
    subscription of several should not cost the others, and the caller decides whether the
    loss is acceptable.
    """
    feed = Feed(sources=list(sources))
    texts: list[str] = []
    for source in sources:
        try:
            texts.append(read_source(source, timeout=timeout))
        except OSError as error:
            # URLError, HTTPError and socket timeouts are all OSError, and so is a missing
            # file, so one clause covers a source that could not be read for any reason.
            feed.failures.append(f"{source}: {error}")
    return collect(texts, feed)


def write(feed: Feed, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(feed.payload(), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path
