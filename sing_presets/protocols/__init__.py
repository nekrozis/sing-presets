"""Share-link parsers, one module per scheme.

A module here only defines a `Protocol` subclass; it registers itself on import. The
package is imported in full by `sing_presets.protocol.discover()`, so adding a protocol is
adding a file.
"""
