# Sing-box Configuration Preset Repository

Compiles **presets** into sing-box configurations. A preset describes one device — what
kind it is, whether it has public IPv6, whether its control panel should be reachable —
and the build turns that into a complete, verified configuration file.

The point of the design is that the number of presets does not multiply the amount of
policy you maintain. A second device adds a few lines of facts; a new feature adds one
capability module. Neither requires touching the other.

## Quick start

```bash
# 1. Turn the subscription into a node list
uv run sing-presets fetch --urls subscription.txt

# 2. List the presets this repository defines
uv run sing-presets list

# 3. Build them, verifying each output with the sing-box binary
uv run sing-presets build --nodes nodes.json

# 4. Inspect the result
ls build/
```

Output is one file per preset, `build/<preset>.json`. Nothing else is written.

Neighbouring rules that share an outcome are written as one rule. The domestic name, the
domestic address and the BitTorrent rules all mean "direct", so they ship as a single
`logical` rule with `mode: or` instead of three in a row; no other rule could have matched
between them, so this changes what the file says rather than what it does.

## Single file

For a machine that should not grow a virtualenv, build one archive:

```bash
python tools/build_pyz.py                     # dist/sing-presets.pyz, about 100 KiB
python dist/sing-presets.pyz fetch --urls subscription.txt
python dist/sing-presets.pyz build --nodes nodes.json
```

The archive carries the package, its generated field surface and PyYAML, so it runs on any
Python 3.10 or newer with nothing installed — which is the condition its own tests run it
under. It is not a standalone binary: an interpreter is still required. Its default paths are
in the working directory, because there is no checkout beside an archive.

## Concepts

**Fact** — an observed property of the environment, such as `device.mtu` or
`network.allow_lan`. Facts are data, so the same capability works on every device.

**Capability** — one intent, as code. `dns-split` decides resolvers and the rules that pick
between them; `ipv4-only` answers AAAA queries with an empty response wherever the answer
would come from this machine, on a network without public IPv6. A capability reads facts
and emits contributions; it never assembles JSON and never knows which preset uses it.

A capability must be one intent (a group of fields always decided together), switchable
independently (disable it and its fields vanish, leaving no residue), and must not write
fields another capability owns. The last two are enforced by `sing_presets/compile.py`
and the audit in `sing_presets/ir.py`, not by convention.

**Preset** — a capability list plus fact values. This is the file you edit.

**Field surface** — the set of objects sing-box accepts, generated from `sing-box schema`
into `sing_presets/data/surface.json`. Every contribution is checked against it, so a
misspelled field fails the build instead of failing on the device. It lives inside the
package because an installed copy and the single-file archive both have to carry it.

## Editing presets

`presets.yaml` is the whole interface:

```yaml
defaults:
  facts:
    log.level: info
  capabilities:
    - logging
    - tun-inbound
    - dns-split
    - outbound-groups
    - route-baseline
    - china-split
    - block-ads
    - clash-api
    - cache-file

presets:
  desktop:
    facts:
      device.tun_address: ["172.18.0.1/30", "fc00::172:18:0:1/126"]
      device.mtu: 9000

  desktop-no-v6:
    extends: desktop
    capabilities_add: [ipv4-only]

  router:
    extends: desktop
    facts:
      device.tun_address: ["10.10.0.1/30", "fc00::10:10:0:1/126"]
      network.allow_lan: true
```

`extends` inherits facts and capabilities from another preset, then applies the overrides.
`capabilities` replaces the list outright; `capabilities_add` and `capabilities_remove`
adjust it. Unknown keys, unknown capability names, and undotted fact names are rejected —
a preset document that silently ignores a setting is worse than one that refuses to load.

Build output for the three presets above differs only where the presets differ: the
no-IPv6 one gains exactly one DNS rule, which answers AAAA queries with an empty response
where the answer would come from this machine — the direct mode and the domestic names —
and leaves the queries that resolve through the tunnel alone; the router changes exactly
its TUN addresses and its control panel binding.

## Adding a capability

Create a module in `sing_presets/capabilities/`, subclass `Capability`, and it registers
itself on import — there is no table to update:

```python
class LanDirect(Capability):
    """Settle `.lan` names locally, so the router answers them, not the tunnel."""

    id = "lan-direct"

    def contribute(self, facts: Facts) -> Iterable[Contribution]:
        yield self.entry(
            "route.rules",
            {"outbound": "direct", "domain_suffix": [".lan"]},
            Position.at(RouteRank.PRIVATE_DIRECT),
        )
```

Then list its id in a preset. Ranks for the shared ordered lists live in
`sing_presets/capabilities/ordering.py`, so rule order stays visible in one place.

`owns` is deliberately absent here, and that is the rule rather than an omission: it names
addresses a capability claims exclusively — a tagged member such as `outbounds{proxy}`, or a
scalar path such as `log.level`. An entry into a shared ordered list claims nothing; where it
lands is decided by the rank, and two capabilities writing to `route.rules` is the normal
case.

A build fails loudly if a capability writes a path outside the field surface, writes into
someone else's member without declaring `depends_on`, leaves a reference dangling, or
leaves a collection empty.

## Nodes

sing-box has no node provider mechanism, so nodes must be inline and the configuration has
to be regenerated when the subscription changes. That is why this belongs in CI.

There are two steps. `fetch` reads subscriptions and writes a node list:

```bash
uv run sing-presets fetch --url https://example.net/api/v1/client/subscribe?token=...
uv run sing-presets fetch --urls subscription.txt   # one source per line
```

A source may be a URL or a local file, and its body may be a plain list of links or the same
list in base64 - panels hand out both and the URL does not say which. `nodes.json` holds the
outbound bodies; `build --nodes nodes.json` consumes them.

`fetch` reports what it lost instead of silently returning fewer nodes:

```
3 nodes, 1 duplicates dropped, 2 links skipped from 1 sources -> nodes.json
  skipped 1x: vmess transport 'kcp' is not supported by sing-box
  skipped 1x: no parser for scheme 'trojan'; known: ss, vmess
```

- **Duplicates** are links that describe the same outbound: the key is the whole body, not
  just protocol, host and port. A panel can front a list of exits through one host and one
  port and tell them apart only by the path of their WebSocket transport, and a subscription
  of that shape loses all but one node under a host-and-port key. Another password on the
  same server is another account, so it is kept for the same reason.
- **Skipped links** are counted with the reason. One unusable link never costs the others.
- **Tags** come from the link's display name. A duplicate name gains a suffix, because
  sing-box refuses a configuration with two outbounds sharing a tag; a name that collides
  with a tag the compiler writes itself (`direct`, `auto`, `proxy`) is renamed the same way.
- A source that cannot be read is reported and skipped. Pass `--strict` to fail instead,
  which is what CI should do: otherwise a dead subscription quietly halves the node list.

`nodes.json` contains credentials. It is ignored by git, and it should stay that way. The
`sources` it records are reduced to scheme and host: a subscription URL carries its token, and
the file and the failure lines both end up in a CI log.

Supported link schemes live in `sing_presets/protocols/`, one module per scheme. Adding one
is adding a file: it registers itself, and nothing else has to be told about it.

A parser converts the fields a link actually carries and does not rewrite them. The previous
generator replaced the `host` of tcp and h2 nodes with a fixed image-hosting domain, which was
a deployment-specific disguise rather than part of the protocol; a subscription that relied on
it has to say so in its own `host` now.

## Verifying

The build validates itself, in increasing cost:

| Check | Where | Catches |
|---|---|---|
| no conflicting contributions | `compile.py` | two capabilities claiming the same scalar |
| fields exist in the surface | `compile.py` | misspelled or invented field names |
| values are ones the schema lists | `compile.py` | `log.level: verbose`, `type: shadowsock` |
| references resolve | `compile.py` | a selector pointing at a node that is not there |
| no empty collections | `compile.py` | an empty subscription, or a missing capability |
| `sing-box check` | `cli.py` | anything the binary disagrees with |
| capability isolation | `build --audit` | a capability that quietly depends on another |

`build` runs `sing-box check` when a binary is available (set `SING_BOX`, or put
`sing-box` on `PATH`) and exits non-zero if any output is rejected.

## Repository layout

```
presets.yaml                 the file to edit
sing_presets/
  surface.py                 the field surface: what may be written
  ir.py                      contributions and the merge algebra
  capability.py              base class, automatic registration
  capabilities/              the library, one intent per module
  protocol.py                share-link base class, registration, node identity
  protocols/                 one module per link scheme
  nodes.py                   subscriptions -> nodes.json, with deduplication
  presets.py                 preset document loading and validation
  compile.py                 preset + nodes -> checked configuration
  cli.py                     command line entry point
  data/surface.json          generated field surface and slot classification
schema/
  sing-box-<version>.json    raw `sing-box schema` output
tools/gen_surface.py         regenerates the surface from a binary
tools/build_pyz.py           packs the command line into one runnable archive
tests/                       unit, integration, and binary verification
```

## Regenerating the field surface

When targeting a newer sing-box, regenerate rather than editing by hand:

```bash
sing-box schema > schema/sing-box-<version>.json
uv run python tools/gen_surface.py schema/sing-box-<version>.json \
    -o sing_presets/data/surface.json --binary-version <version> --strict
```

`--strict` makes the declared tag-namespace table fail the run when upstream renames or
removes a reference kind, so the classification cannot drift silently.

## Requirements

- Python 3.10 or higher
- PyYAML
