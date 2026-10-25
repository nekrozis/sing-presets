# Sing-box Configuration Preset Repository

Compiles **presets** into sing-box configurations. A preset describes one device — what
kind it is, whether it has public IPv6, whether its control panel should be reachable —
and the build turns that into a complete, verified configuration file.

The point of the design is that the number of presets does not multiply the amount of
policy you maintain. A second device adds a few lines of facts; a new feature adds one
capability module. Neither requires touching the other.

## Quick start

```bash
# 1. List the presets this repository defines
uv run sing-presets list

# 2. Build them, verifying each output with the sing-box binary
uv run sing-presets build --nodes nodes.json

# 3. Inspect the result
ls build/
```

Output is one file per preset, `build/<preset>.json`. Nothing else is written.

## Concepts

**Fact** — an observed property of the environment, such as `device.mtu` or
`network.allow_lan`. Facts are data, so the same capability works on every device.

**Capability** — one intent, as code. `dns-split` decides resolvers and the rules that pick
between them; `ipv4-only` stops AAAA lookups on a network without public IPv6. A
capability reads facts and emits contributions; it never assembles JSON and never knows
which preset uses it.

A capability must be one intent (a group of fields always decided together), switchable
independently (disable it and its fields vanish, leaving no residue), and must not write
fields another capability owns. The last two are enforced by `sing_presets/compile.py`
and the audit in `sing_presets/ir.py`, not by convention.

**Preset** — a capability list plus fact values. This is the file you edit.

**Field surface** — the set of objects sing-box accepts, generated from `sing-box schema`
into `schema/surface.json`. Every contribution is checked against it, so a misspelled
field fails the build instead of failing on the device.

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
no-IPv6 one gains exactly `dns.strategy`, the router changes exactly its TUN addresses and
its control panel binding.

## Adding a capability

Create a module in `sing_presets/capabilities/`, subclass `Capability`, and it registers
itself on import — there is no table to update:

```python
class BittorrentDirect(Capability):
    id = "bittorrent-direct"
    owns = ("route.rules",)

    def contribute(self, facts: Facts) -> Iterable[Contribution]:
        yield self.entry(
            "route.rules",
            {"outbound": "direct", "protocol": "bittorrent"},
            Position.at(RouteRank.BITTORRENT_DIRECT),
        )
```

Then list its id in a preset. Ranks for the shared ordered lists live in
`sing_presets/capabilities/ordering.py`, so rule order stays visible in one place.

A build fails loudly if a capability writes a path outside the field surface, writes into
someone else's member without declaring `depends_on`, leaves a reference dangling, or
leaves a collection empty.

## Nodes

sing-box has no node provider mechanism, so nodes must be inline and the configuration has
to be regenerated when the subscription changes. That is why this belongs in CI.

`--nodes` takes a JSON list of sing-box outbound objects, each with a `tag`:

```json
[{"tag": "jp-tokyo", "type": "shadowsocks", "server": "198.51.100.10",
  "server_port": 8388, "method": "aes-128-gcm", "password": "..."}]
```

Duplicate tags are rejected here rather than at startup, because a subscription is free to
contain two entries with the same display name and sing-box refuses to start on a
duplicate.

The subscription parser has not been migrated to this pipeline yet: `scripts/` still does
that job end to end. Producing `nodes.json` from a subscription is the next step, and until
then the file has to come from elsewhere.

## Verifying

The build validates itself, in increasing cost:

| Check | Where | Catches |
|---|---|---|
| no conflicting contributions | `compile.py` | two capabilities claiming the same scalar |
| fields exist in the surface | `compile.py` | misspelled or invented field names |
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
  presets.py                 preset document loading and validation
  compile.py                 preset + nodes -> checked configuration
  cli.py                     command line entry point
schema/
  sing-box-<version>.json    raw `sing-box schema` output
  surface.json               generated field surface and slot classification
tools/gen_surface.py         regenerates surface.json from a binary
tests/                       unit, integration, and binary verification
```

## Regenerating the field surface

When targeting a newer sing-box, regenerate rather than editing by hand:

```bash
sing-box schema > schema/sing-box-<version>.json
uv run python tools/gen_surface.py schema/sing-box-<version>.json \
    -o schema/surface.json --binary-version <version> --strict
```

`--strict` makes the declared tag-namespace table fail the run when upstream renames or
removes a reference kind, so the classification cannot drift silently.

## Legacy pipeline

`scripts/` and `base.yaml` are the previous generator: a base YAML template plus
`_PROXY_NODES_` and `_PROXY_TAGS_` placeholders, run from inside `scripts/` as
`python main.py`. It still produces the configuration this repository used before, and is
kept until the capability library covers the same ground.

It is excluded from type checking and is not developed further.

## Requirements

- Python 3.10 or higher
- PyYAML, requests
