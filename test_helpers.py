# -*- coding: utf-8 -*-
#  test_helpers.py
#
#  Helpers for the headless ReplicateLayout test-suite.
#
#  Two independent ways of checking a replication result:
#
#  * geometric_consistency() - a convention-independent correctness check. The
#    defining property of "replicate layout" is that every replicated footprint
#    keeps the same spatial relationship to its destination anchor as the source
#    footprint has to the source anchor. Rigid motions and reflections preserve
#    pairwise distances, so we verify that the matrix of pairwise distances
#    between the footprints of a section is preserved in every replicated
#    section, and that relative flip / relative orientation are preserved. This
#    needs no assumption about KiCad's rotation sign convention.
#
#  * board_signature() / compare_signatures() - a canonical, version-independent
#    dump of all replicated geometry, used to compare the output of the current
#    KiCad against a committed reference (captured from KiCad 9) so the suite is
#    a true regression test that the KiCad 10 behaviour matches KiCad 9.
import math
import json

import pcbnew


# --------------------------------------------------------------------------- #
#  geometric correctness (convention independent)
# --------------------------------------------------------------------------- #

def _pose(fp):
    p = fp.GetPosition()
    return (p.x, p.y, round(fp.GetOrientationDegrees(), 4), bool(fp.IsFlipped()))


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _norm(a):
    return (a + 180.0) % 360.0 - 180.0


def geometric_consistency(board, anchor_ref, src_refs, dst_sections, tol_nm=2000):
    """Return (ok, problems). See module docstring."""
    problems = []
    by_ref = {fp.GetReference(): fp for fp in board.GetFootprints()}

    src_poses = [_pose(by_ref[r]) for r in src_refs]
    n = len(src_poses)
    a_idx = src_refs.index(anchor_ref)

    def pdm(poses):
        return [[_dist(poses[i], poses[j]) for j in range(len(poses))]
                for i in range(len(poses))]

    src_pdm = pdm(src_poses)

    for s_i, dst_refs in enumerate(dst_sections):
        if len(dst_refs) != n:
            problems.append("sheet %d: footprint count %d != %d" % (s_i, len(dst_refs), n))
            continue
        dst_poses = [_pose(by_ref[r]) for r in dst_refs]
        dst_pdm = pdm(dst_poses)

        # pairwise distances preserved
        for i in range(n):
            for j in range(n):
                dd = abs(src_pdm[i][j] - dst_pdm[i][j])
                if dd > tol_nm:
                    problems.append(
                        "sheet %d: distance %s-%s changed by %.0f nm"
                        % (s_i, src_refs[i], src_refs[j], dd))

        src_a_flip = src_poses[a_idx][3]
        dst_a_flip = dst_poses[a_idx][3]
        section_flipped = (src_a_flip != dst_a_flip)
        src_a_or = src_poses[a_idx][2]
        dst_a_or = dst_poses[a_idx][2]

        for i in range(n):
            # relative flip preserved
            if (src_poses[i][3] != src_a_flip) != (dst_poses[i][3] != dst_a_flip):
                problems.append("sheet %d: relative flip of %s not preserved"
                                % (s_i, src_refs[i]))
            # relative orientation preserved (mirrored for flipped sections)
            src_rel = _norm(src_poses[i][2] - src_a_or)
            dst_rel = _norm(dst_poses[i][2] - dst_a_or)
            if not section_flipped:
                err = abs(_norm(src_rel - dst_rel))
            else:
                err = min(abs(_norm(src_rel + dst_rel)), abs(_norm(src_rel - dst_rel)))
            if err > 0.05:
                problems.append(
                    "sheet %d: relative orientation of %s off by %.3f deg"
                    % (s_i, src_refs[i], err))

    return (len(problems) == 0, problems)


# --------------------------------------------------------------------------- #
#  canonical signature (version independent regression check)
# --------------------------------------------------------------------------- #

def board_signature(board):
    sig = {"footprints": {}, "tracks": [], "zones": [], "texts": [], "drawings": []}

    for fp in board.GetFootprints():
        p = fp.GetPosition()
        sig["footprints"][fp.GetReference()] = {
            "x": p.x, "y": p.y,
            "orient": round(fp.GetOrientationDegrees(), 4),
            "flip": bool(fp.IsFlipped()),
            "layer": fp.GetLayerName(),
        }

    tracks = []
    for t in board.GetTracks():
        s = t.GetStart(); e = t.GetEnd()
        is_via = (t.GetClass() == "PCB_VIA")
        if is_via:
            try:
                width = t.GetWidth(t.TopLayer())
            except Exception:
                width = t.GetDrillValue()
        else:
            width = t.GetWidth()
        rec = {"type": t.GetClass(), "start": [s.x, s.y], "end": [e.x, e.y],
               "width": width, "layer": board.GetLayerName(t.GetLayer()),
               "net": t.GetNetname()}
        if is_via:
            rec["drill"] = t.GetDrillValue()
            rec["top"] = board.GetLayerName(t.TopLayer())
            rec["bottom"] = board.GetLayerName(t.BottomLayer())
        tracks.append(rec)
    tracks.sort(key=lambda r: (r["type"], r["layer"], r["net"],
                               r["start"], r["end"], r["width"]))
    sig["tracks"] = tracks

    zones = []
    for i in range(board.GetAreaCount()):
        z = board.GetArea(i)
        rings = []
        outline = z.Outline()
        for oi in range(outline.OutlineCount()):
            o = outline.Outline(oi)
            rings.append([[o.CPoint(pi).x, o.CPoint(pi).y] for pi in range(o.PointCount())])
        zones.append({"net": z.GetNetname(),
                      "layers": sorted([board.GetLayerName(l) for l in z.GetLayerSet().Seq()]),
                      "outline": rings})
    zones.sort(key=lambda r: (r["net"], r["layers"], json.dumps(r["outline"])))
    sig["zones"] = zones

    texts = []
    for d in board.GetDrawings():
        if isinstance(d, pcbnew.PCB_TEXT):
            p = d.GetPosition()
            texts.append({"text": d.GetText(), "x": p.x, "y": p.y,
                          "angle": round(d.GetTextAngleDegrees(), 4),
                          "layer": board.GetLayerName(d.GetLayer()),
                          "mirror": bool(d.IsMirrored())})
    texts.sort(key=lambda r: (r["text"], r["x"], r["y"], r["layer"]))
    sig["texts"] = texts

    drawings = []
    for d in board.GetDrawings():
        if isinstance(d, pcbnew.PCB_TEXT):
            continue
        bb = d.GetBoundingBox()
        drawings.append({"type": d.GetClass(), "layer": board.GetLayerName(d.GetLayer()),
                         "bb": [bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom()]})
    drawings.sort(key=lambda r: (r["type"], r["layer"], r["bb"]))
    sig["drawings"] = drawings
    return sig


# --------------------------------------------------------------------------- #
#  signature comparison
# --------------------------------------------------------------------------- #

def _flat(x):
    out = []
    if isinstance(x, list):
        for e in x:
            out.extend(_flat(e))
    else:
        out.append(x)
    return out


def _match_list(la, lb, key_fields, pos_fields, name, diffs, pos_tol):
    from collections import defaultdict
    if len(la) != len(lb):
        diffs.append("%s count differs %d vs %d" % (name, len(la), len(lb)))
    ga, gb = defaultdict(list), defaultdict(list)
    for it in la:
        ga[tuple(str(it.get(k)) for k in key_fields)].append(it)
    for it in lb:
        gb[tuple(str(it.get(k)) for k in key_fields)].append(it)
    for k in set(ga) | set(gb):
        A, B = ga.get(k, []), gb.get(k, [])
        if len(A) != len(B):
            diffs.append("%s group %s count %d vs %d" % (name, k, len(A), len(B)))
        used = [False] * len(B)
        for a in A:
            best, bi = None, -1
            for i, b in enumerate(B):
                if used[i]:
                    continue
                d = 0.0
                for pf in pos_fields:
                    av, bv = a.get(pf), b.get(pf)
                    if isinstance(av, list):
                        d += sum((p - q) ** 2 for p, q in zip(_flat(av), _flat(bv))) ** 0.5
                    elif isinstance(av, (int, float)):
                        d += abs(av - bv)
                if best is None or d < best:
                    best, bi = d, i
            if bi >= 0:
                used[bi] = True
                if best > pos_tol:
                    diffs.append("%s item in group %s pos delta %.0f" % (name, k, best))


def compare_signatures(ref, test, pos_tol=1000, ang_tol=0.02):
    """Return list of human-readable differences (empty == equivalent)."""
    diffs = []
    fa, fb = ref["footprints"], test["footprints"]
    if set(fa) != set(fb):
        diffs.append("footprint refs differ")
    else:
        for r in fa:
            x, y = fa[r], fb[r]
            dd = math.hypot(x["x"] - y["x"], x["y"] - y["y"])
            if dd > pos_tol:
                diffs.append("fp %s pos delta %.0f nm" % (r, dd))
            if abs(_norm(x["orient"] - y["orient"])) > ang_tol:
                diffs.append("fp %s orient delta %.4f" % (r, abs(_norm(x["orient"] - y["orient"]))))
            if x["flip"] != y["flip"]:
                diffs.append("fp %s flip differs" % r)
            if x["layer"] != y["layer"]:
                diffs.append("fp %s layer differs %s/%s" % (r, x["layer"], y["layer"]))
    _match_list(ref["tracks"], test["tracks"], ["type", "layer", "net", "width"],
                ["start", "end"], "tracks", diffs, pos_tol)
    _match_list(ref["zones"], test["zones"], ["net"], ["outline"], "zones", diffs, pos_tol)
    _match_list(ref["texts"], test["texts"], ["text", "layer", "mirror"],
                ["x", "y"], "texts", diffs, pos_tol)
    _match_list(ref["drawings"], test["drawings"], ["type", "layer"], ["bb"],
                "drawings", diffs, pos_tol)
    return diffs
