# KiCAD Replicate Layout Plugin

> [!NOTE]
> This change ports the plugin to **KiCad 10** (targets KiCad 10.0). KiCad 10
> removed the `pcbnew.ID_V_TOOLBAR` constant the dialog relied on, which made the
> plugin raise on every run (issue #87); this is fixed with a fallback that still
> works on KiCad 9. It has been verified to reproduce the KiCad 9 behaviour exactly
> (see *Testing* below). Similar functionality is also available in KiCad natively;
> see the [official KiCad multichannel documentation](https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html#multichannel).
> The plugin remains useful for replication driven by hierarchical sheets.

The repository includes code for KiCad Action plugin which replicates part of the PCB layout.

Replicate the PCB layout of one hierarchical sheet to other hierarchical sheets. This replication is based upon hierarchical sheets in Eeschema. The basic requirement for replication is that the section to be replicated (source) is completely contained within a single hierarchical sheet, and replicated sections (destination) are just copies of the same sheet. Complex hierarchies are supported and the replicated sheet can contain subsheets. The plugin replicates footprints, zones, tracks, text and drawings.

After the section for replication (source section) has been laid out (footprints, tracks, text objects and zones placed) you need to:
1. Place the anchor footprints for the destination sections you want to replicate. This defines the position and orientation of replicated sections. You can use [the PlaceFootprints action plugin](https://github.com/MitjaNemec/PlaceFootprints) for this.
2. Select the same anchor footprint within the source section.
3. Run the plugin.
4. Choose which hierarchical level you wish to replicate.
5. Select which sheets you want to replicate (default is all of them).
6. Select whether you want to also replicate tracks, zones and/or text objects.
7. Select whether you want to group replicated footprints/tracks/zones/text/drawings by hierarchical sheets.
8. Select whether you want to replicate tracks/zones/text which intersect the pivot bounding box or just those contained within the bounding box.
9. Select whether you want to delete already laid out tracks/zones/text (this is useful when updating an already replicated layout).
10. Hit OK.

By default, only objects which are fully contained in the bounding box constituted by all the footprints in the section will be replicated. You can select to also replicate zones and tracks which intersect this bounding box. Additionally, tracks, text and zones which are already laid out in the replicated bounding boxes can be removed (useful when updating). Note that bounding boxes are squares aligned with the x and y axis, regardless of section orientation.

## Installation

The preferred way to install the plugin is via KiCad's Plugin and Content Manager (PCM). Installation on non-networked devices can be done by downloading [the latest release](https://github.com/MitjaNemec/ReplicateLayout/releases/latest) and installing in the PCM using the `Install from file` option.

## Testing

The plugin ships with a headless, GUI-free test-suite driven entirely through the
pcbnew scripting API (`test_replicate_layout.py`). It runs a number of replication
scenarios (inner/outer hierarchy levels, flipped anchors, "contained" vs.
"intersecting" selection, removal of existing copper, grouping and footprint-text
replication), plus regression tests for issue #86 (already-grouped destination
footprints). Each replication result is checked for **geometric correctness**:
every replicated section must keep the same internal geometry (pairwise distances,
relative orientation and relative flip) as the source section. This check is
independent of any coordinate convention, so it validates the result on its own
merits.

Run it with the Python interpreter bundled with KiCad, for example on macOS:

```bash
/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3.9 test_replicate_layout.py
```

The suite can additionally compare output against committed reference signatures to
prove byte-for-byte parity with a previous KiCad version: run with `--gen-refs`
under that KiCad (writing `test_refs/*.json`), then a normal run under the new KiCad
verifies the output matches. This is how the KiCad 9 → 10 parity was confirmed.

**Author :** doc.dr. Mitja Nemec
**KiCad 10 port :** 2026
**Date :** 2025


