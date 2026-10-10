"""Third-party code, vendored unmodified. Do not edit these files.

``text_unicode.py`` is Layer A of guillaumemeyer/watermarks-remover (MIT),
pinned at v0.5.0 (commit dc0ff78f39bedfe0a1986eef54efb297645372ba), path
``service/scripts/text_unicode.py``, sha256
c35e9118523679e109edb187bbcb6f9c19d4cf57c159469fb687a3dfcafc2253.

Vendored rather than depended on because upstream ships an agent skill and an
HTTP service, not a library: calling the service would put a network hop on
the render path that render.py deliberately keeps network-free (see _no_fetch).
The file is stdlib-only (unicodedata, collections, dataclasses) and performs no
network, subprocess or file I/O -- re-verify that before bumping the pin.

Only Layer A (invisible-Unicode hygiene) is used. Upstream's Layer B, a
paraphrase pass aimed at defeating statistical provenance watermarks, is
deliberately not vendored: `phased requirements.md` 4.2.3 permits text hygiene
and does not authorise defeating signals that a document was AI-assisted.

Kept byte-identical to upstream so the sha256 above stays checkable; provenance
lives here rather than as a header inside the file.
"""
