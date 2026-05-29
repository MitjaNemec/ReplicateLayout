#!/usr/bin/env python
# -*- coding: utf-8 -*-
#  test_replicate_layout.py
#
#  Headless test-suite for the ReplicateLayout plugin, driven entirely through
#  the pcbnew scripting (SWIG) API so it can be run without the GUI:
#
#      <KiCad python> test_replicate_layout.py
#
#  e.g. on macOS:
#      /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/\
#          Versions/3.9/bin/python3.9 test_replicate_layout.py
#
#  Each scenario:
#    1. loads a test project,
#    2. runs a replication with a particular set of options,
#    3. checks that the result is geometrically correct (every replicated
#       section keeps the same internal geometry as the source section), and
#    4. if a committed reference signature exists in test_refs/, checks that the
#       produced geometry matches it (this reference was captured from KiCad 9,
#       so a passing run proves the KiCad 10 behaviour matches KiCad 9).
#
#  Run with  --gen-refs  to (re)generate the reference signatures from the
#  current KiCad, e.g. to capture a fresh KiCad 9 baseline.
import json
import os
import sys
import unittest

import pcbnew

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)

from replicate_layout import Replicator, Settings  # noqa: E402
import test_helpers  # noqa: E402

REF_DIR = os.path.join(HERE, "test_refs")

TP = "replicate_layout_test_project/replicate_layout_test_project.kicad_pcb"
FT = "replicate_layout_fp_text/replicate_layout_fp_text.kicad_pcb"

_GROUP = dict(group_layouts=True, group_footprints=True, group_tracks=True,
              group_zones=True, group_text=True, group_drawings=True)

# name, pcb, anchor, level index, sheet indices, settings overrides
SCENARIOS = [
    ("baseline_inner",     TP, "U701",  1, [1, 3, 7],      {}),
    ("inner_all",          TP, "U701",  1, list(range(9)), {}),
    ("flipped_anchor_alt", TP, "U1501", 0, [2, 4, 8],      {}),
    ("outer_level",        TP, "U701",  0, [0, 1],         {}),
    ("containing",         TP, "U701",  1, [1, 3, 7],      dict(intersecting=False)),
    ("remove_existing",    TP, "U701",  1, [1, 3, 7],      dict(remove=True)),
    ("groups",             TP, "U701",  1, [1, 3, 7],      _GROUP),
    ("no_tracks_zones",    TP, "U701",  1, [1, 3, 7],      dict(rep_tracks=False, rep_zones=False)),
    ("fp_text",            FT, "R364",  0, [0, 1],         {}),
]


def _settings(overrides):
    d = dict(rep_tracks=True, rep_zones=True, rep_text=True, rep_drawings=True,
             group_layouts=False, group_footprints=False, group_tracks=False,
             group_zones=False, group_text=False, group_drawings=False,
             rep_locked_tracks=True, rep_locked_zones=True, rep_locked_text=True,
             rep_locked_drawings=True, intersecting=True, group_items=True,
             group_only=False, locked_fps=False, remove=False)
    d.update(overrides)
    return Settings(**d)


def run_scenario(pcb_rel, anchor, level, sheets, overrides):
    """Run one replication; return (board, anchor, src_refs, dst_sections)."""
    board = pcbnew.LoadBoard(os.path.join(HERE, pcb_rel))

    def prog(stage, pct, msg=None):
        pass

    rep = Replicator(board, anchor, prog)
    src = rep.get_fp_by_ref(anchor)
    sheet_list = rep.get_sheets_to_replicate(src, src.sheet_id[level])
    dst = [sheet_list[i] for i in sheets]
    settings = _settings(overrides)
    lvl = src.sheet_id[0:level + 1]

    # exercise the highlight code paths too
    fps, items = rep.highlight_set_level(lvl, settings)
    rep.highlight_clear_level(fps, items)

    rep.replicate_layout(src, lvl, dst, settings, rm_duplicates=True)

    src_refs = [f.ref for f in rep.src_footprints]
    dst_sections = []
    for sheet in dst:
        sheet_fps = rep.get_footprints_on_sheet(sheet)
        dst_sections.append([rep.match_fp_in_list(sfp, sheet_fps).ref
                             for sfp in rep.src_footprints])
    return board, anchor, src_refs, dst_sections


class ReplicateLayoutTests(unittest.TestCase):
    pass


def _make_test(name, pcb, anchor, level, sheets, overrides):
    def test(self):
        board, a, src_refs, dst_sections = run_scenario(pcb, anchor, level, sheets, overrides)

        # 1. convention-independent geometric correctness
        ok, problems = test_helpers.geometric_consistency(board, a, src_refs, dst_sections)
        self.assertTrue(ok, "geometric check failed:\n" + "\n".join(problems[:20]))

        # 2. regression against committed (KiCad 9) reference signature
        ref_path = os.path.join(REF_DIR, name + ".json")
        if os.path.exists(ref_path):
            sig = test_helpers.board_signature(board)
            with open(ref_path) as fh:
                ref = json.load(fh)["signature"]
            diffs = test_helpers.compare_signatures(ref, sig)
            self.assertEqual(diffs, [], "signature differs from reference:\n"
                             + "\n".join(diffs[:20]))
    return test


for _scn in SCENARIOS:
    setattr(ReplicateLayoutTests, "test_" + _scn[0], _make_test(*_scn))


class Issue86Tests(unittest.TestCase):
    """Regression for issue #86: destination footprints that are already in the
    matching 'Replicated Group ...' group (e.g. on a re-run) must not make the
    plugin raise. The original code compared the PCB_GROUP object to a string,
    which is always unequal, so any grouped destination footprint aborted the run."""

    def _setup(self):
        board = pcbnew.LoadBoard(os.path.join(HERE, TP))
        rep = Replicator(board, "U701", lambda *a, **k: None)
        src = rep.get_fp_by_ref("U701")
        sheet_list = rep.get_sheets_to_replicate(src, src.sheet_id[1])
        dst = [sheet_list[i] for i in [1, 3, 7]]
        lvl = src.sheet_id[0:2]
        return board, rep, src, dst, lvl

    def test_matching_group_does_not_raise(self):
        board, rep, src, dst, lvl = self._setup()
        first = dst[0]
        grp = pcbnew.PCB_GROUP(None)
        grp.SetName("Replicated Group {}".format(first))
        board.Add(grp)
        for fp in rep.get_footprints_on_sheet(first):
            grp.AddItem(fp.fp)
        settings = _settings({})  # group_layouts off, so the group is not recreated
        try:
            rep.replicate_layout(src, lvl, dst, settings, rm_duplicates=True)
        except LookupError as e:
            self.fail("replication wrongly raised for a correctly grouped "
                      "destination footprint (issue #86): %s" % e)

    def test_foreign_group_still_raises(self):
        # the guard must still fire for a footprint in an unrelated group
        board, rep, src, dst, lvl = self._setup()
        first = dst[0]
        grp = pcbnew.PCB_GROUP(None)
        grp.SetName("Some Unrelated Group")
        board.Add(grp)
        for fp in rep.get_footprints_on_sheet(first):
            grp.AddItem(fp.fp)
        settings = _settings({})
        with self.assertRaises(LookupError):
            rep.replicate_layout(src, lvl, dst, settings, rm_duplicates=True)


def gen_refs():
    os.makedirs(REF_DIR, exist_ok=True)
    for (name, pcb, anchor, level, sheets, overrides) in SCENARIOS:
        board, a, src_refs, dst_sections = run_scenario(pcb, anchor, level, sheets, overrides)
        ok, problems = test_helpers.geometric_consistency(board, a, src_refs, dst_sections)
        sig = test_helpers.board_signature(board)
        out = {"build": pcbnew.GetBuildVersion(), "geometric_ok": ok, "signature": sig}
        with open(os.path.join(REF_DIR, name + ".json"), "w") as fh:
            json.dump(out, fh, indent=1)
        print("wrote ref %-20s geo_ok=%s (%s)" % (name, ok, pcbnew.GetBuildVersion()))


if __name__ == "__main__":
    print("KiCad build:", pcbnew.GetBuildVersion(), "| python:", sys.version.split()[0])
    if "--gen-refs" in sys.argv:
        gen_refs()
    else:
        unittest.main(verbosity=2)
