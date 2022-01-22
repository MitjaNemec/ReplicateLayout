# -*- coding: utf-8 -*-
#  replicate_layout.py
#
# Copyright (C) 2019-2022 Mitja Nemec
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#
import pcbnew
from collections import namedtuple
import os
import logging
import itertools
import math
from remove_duplicates import remove_duplicates

Footprint = namedtuple('Footprint', ['ref', 'fp', 'fp_id', 'sheet_id', 'filename'])
logger = logging.getLogger(__name__)


def rotate_around_center(coordinates, angle):
    """ rotate coordinates for a defined angle in degrees around coordinate center"""
    new_x = coordinates[0] * math.cos(2 * math.pi * angle / 360) \
            - coordinates[1] * math.sin(2 * math.pi * angle / 360)
    new_y = coordinates[0] * math.sin(2 * math.pi * angle / 360) \
            + coordinates[1] * math.cos(2 * math.pi * angle / 360)
    return new_x, new_y


def rotate_around_point(old_position, point, angle):
    """ rotate coordinates for a defined angle in degrees around a point """
    # get relative position to point
    rel_x = old_position[0] - point[0]
    rel_y = old_position[1] - point[1]
    # rotate around
    new_rel_x, new_rel_y = rotate_around_center((rel_x, rel_y), angle)
    # get absolute position
    new_position = (new_rel_x + point[0], new_rel_y + point[1])
    return new_position


def get_index_of_tuple(list_of_tuples, index, value):
    for pos, t in enumerate(list_of_tuples):
        if t[index] == value:
            return pos


def update_progress(stage, percentage, message=None):
    if message is not None:
        print(message)
    print(percentage)


class Replicator:
    def __init__(self, board, update_func=update_progress):
        self.board = board
        self.stage = 1
        self.max_stages = 0
        self.update_progress = update_func

        self.level = None
        self.src_anchor_fp = None
        self.replicate_locked_items = None
        self.dst_sheets = []
        self.src_footprints = []
        self.other_footprints = []
        self.src_local_nets = []
        self.src_bounding_box = None
        self.src_tracks = []
        self.src_zones = []
        self.src_text = []
        self.src_drawings = []

        self.pcb_filename = os.path.abspath(board.GetFileName())
        self.sch_filename = self.pcb_filename.replace(".kicad_pcb", ".sch")
        self.project_folder = os.path.dirname(self.pcb_filename)

        # construct a list of footprints with all pertinent data
        logger.info('getting a list of all footprints on board')
        footprints = board.GetFootprints()
        self.footprints = []

        # get dict_of_sheets from layout data only (through footprint Sheetfile and Sheetname properties)
        self.dict_of_sheets = {}
        for fp in footprints:
            sheet_id = self.get_sheet_id(fp)
            sheet_file = fp.GetProperty('Sheetfile')
            sheet_name = fp.GetProperty('Sheetname')
            # footprint is in the schematics and has Sheetfile propertiy
            if sheet_file and sheet_id:
                self.dict_of_sheets[sheet_id] = [sheet_name, sheet_file]
            # footprint is in the schematics but has no Sheetfile properties
            elif sheet_id:
                logger.info("Footprint " + fp.GetReference() + " does not have Sheetfile property")
                raise LookupError("Footprint " + str(
                    fp.GetReference()) + " doesn't have Sheetfile and Sheetname properties. "
                                         "You need to update the layout from schematics")
            # footprint is only in the layout
            else:
                logger.debug("Footprint " + fp.GetReference() + " is only in layout")

        # construct a list of all the footprints
        for fp in footprints:
            fp_tuple = Footprint(fp=fp,
                                        fp_id=self.get_footprint_id(fp),
                                        sheet_id=self.get_sheet_path(fp)[0],
                                        filename=self.get_sheet_path(fp)[1],
                                        ref=fp.GetReference())
            self.footprints.append(fp_tuple)
        pass

    @staticmethod
    def get_footprint_id(footprint):
        path = footprint.GetPath().AsString().upper().replace('00000000-0000-0000-0000-0000', '').split("/")
        if len(path) != 1:
            fp_id = path[-1]
        # if path is empty, then footprint is not part of schematics
        else:
            fp_id = None
        return fp_id

    @staticmethod
    def get_sheet_id(footprint):
        path = footprint.GetPath().AsString().upper().replace('00000000-0000-0000-0000-0000', '').split("/")
        if len(path) != 1:
            sheet_id = path[-2]
        # if path is empty, then footprint is not part of schematics
        else:
            sheet_id = None
        return sheet_id

    def get_sheet_path(self, footprint):
        """ get sheet id """
        path = footprint.GetPath().AsString().upper().replace('00000000-0000-0000-0000-0000', '').split("/")
        if len(path) != 1:
            sheet_path = path[0:-1]
            sheet_names = [self.dict_of_sheets[x][0] for x in sheet_path if x in self.dict_of_sheets]
            sheet_files = [self.dict_of_sheets[x][1] for x in sheet_path if x in self.dict_of_sheets]
            sheet_path = [sheet_names, sheet_files]
        else:
            sheet_path = ["", ""]
        return sheet_path

    def get_fp_by_ref(self, ref):
        for fp in self.footprints:
            if fp.ref == ref:
                return fp
        return None

    def get_list_of_footprints_with_same_id(self, fp_id):
        footprints_with_same_id = []
        for fp in self.footprints:
            if fp.fp_id == fp_id:
                footprints_with_same_id.append(fp)
        return footprints_with_same_id

    def get_sheets_to_replicate(self, reference_footprint, level):
        sheet_id = reference_footprint.sheet_id
        sheet_file = reference_footprint.filename
        # find level_id
        level_file = sheet_file[sheet_id.index(level)]
        logger.info('constructing a list of sheets suitable for replication on level:'
                    + repr(level) + ", file:" + repr(level_file))

        # construct complete hierarchy path up to the level of reference footprint
        sheet_id_up_to_level = []
        for i in range(len(sheet_id)):
            sheet_id_up_to_level.append(sheet_id[i])
            if sheet_id[i] == level:
                break

        # get all footprints with same ID
        footprints_with_same_id = self.get_list_of_footprints_with_same_id(reference_footprint.fp_id)
        # if hierarchy is deeper, match only the sheets with same hierarchy from root to -1
        sheets_on_same_level = []

        # go through all the footprints
        for fp in footprints_with_same_id:
            # if the footprint is on selected level, it's sheet is added to the list of sheets on this level
            if level_file in fp.filename:
                sheet_id_list = []
                # create a hierarchy path only up to the level
                for i in range(len(fp.filename)):
                    sheet_id_list.append(fp.sheet_id[i])
                    if fp.filename[i] == level_file:
                        break
                sheets_on_same_level.append(sheet_id_list)

        # remove duplicates
        sheets_on_same_level.sort()
        sheets_on_same_level = list(k for k, _ in itertools.groupby(sheets_on_same_level))

        # remove the sheet path for reference footprint
        for sheet in sheets_on_same_level:
            if sheet == sheet_id_up_to_level:
                index = sheets_on_same_level.index(sheet)
                del sheets_on_same_level[index]
                break
        logger.info("suitable sheets are:" + repr(sheets_on_same_level))
        return sheets_on_same_level

    def get_footprints_on_sheet(self, level):
        footprints_on_sheet = []
        level_depth = len(level)
        for fp in self.footprints:
            if level == fp.sheet_id[0:level_depth]:
                footprints_on_sheet.append(fp)
        return footprints_on_sheet

    def get_footprints_not_on_sheet(self, level):
        footprints_not_on_sheet = []
        level_depth = len(level)
        for fp in self.footprints:
            if level != fp.sheet_id[0:level_depth]:
                footprints_not_on_sheet.append(fp)
        return footprints_not_on_sheet

    @staticmethod
    def get_nets_from_footprints(footprints):
        # go through all footprints and their pads and get the nets they are connected to
        nets = []
        for fp in footprints:
            # get their pads
            pads = fp.fp.Pads()
            # get net
            for pad in pads:
                nets.append(pad.GetNetname())

        # remove duplicates
        nets_clean = []
        for i in nets:
            if i not in nets_clean:
                nets_clean.append(i)
        return nets_clean

    def get_local_nets(self, src_footprints, other_footprints):
        # get nets other footprints are connected to
        other_nets = self.get_nets_from_footprints(other_footprints)
        # get nets only source footprints are connected to
        src_nets = self.get_nets_from_footprints(src_footprints)

        src_local_nets = []
        for net in src_nets:
            if net not in other_nets:
                src_local_nets.append(net)

        return src_local_nets

    @staticmethod
    def get_footprints_bounding_box(footprints):
        # get first footprint bounding box
        bounding_box = footprints[0].fp.GetBoundingBox()
        top = bounding_box.GetTop()
        bottom = bounding_box.GetBottom()
        left = bounding_box.GetLeft()
        right = bounding_box.GetRight()
        # iterate through the rest of the footprints and resize bounding box accordingly
        for fp in footprints:
            fp_box = fp.fp.GetBoundingBox()
            top = min(top, fp_box.GetTop())
            bottom = max(bottom, fp_box.GetBottom())
            left = min(left, fp_box.GetLeft())
            right = max(right, fp_box.GetRight())

        position = pcbnew.wxPoint(left, top)
        size = pcbnew.wxSize(right - left, bottom - top)
        bounding_box = pcbnew.EDA_RECT(position, size)
        return bounding_box

    def get_tracks(self, bounding_box, local_nets, containing):
        # get_all tracks
        all_tracks = self.board.GetTracks()
        tracks = []
        # keep only tracks that are within our bounding box
        for track in all_tracks:
            track_bb = track.GetBoundingBox()
            # if track is contained or intersecting the bounding box
            if (containing and bounding_box.Contains(track_bb)) or \
                    (not containing and bounding_box.Intersects(track_bb)):
                tracks.append(track)
            # even if track is not within the bounding box
            else:
                # check if it on a local net
                if track.GetNetname() in local_nets:
                    # and add it to the
                    tracks.append(track)
        return tracks

    def get_zones(self, bounding_box, containing):
        # get all zones
        all_zones = []
        for zoneid in range(self.board.GetAreaCount()):
            all_zones.append(self.board.GetArea(zoneid))
        # find all zones which are within the bounding box
        zones = []
        for zone in all_zones:
            zone_bb = zone.GetBoundingBox()
            if (containing and bounding_box.Contains(zone_bb)) or \
                    (not containing and bounding_box.Intersects(zone_bb)):
                zones.append(zone)
        return zones

    def get_text_items(self, bounding_box, containing):
        # get all text objects in bounding box
        all_text = []
        for drawing in self.board.GetDrawings():
            if not isinstance(drawing, pcbnew.PCB_TEXT):
                continue
            text_bb = drawing.GetBoundingBox()
            if containing:
                if bounding_box.Contains(text_bb):
                    all_text.append(drawing)
            else:
                if bounding_box.Intersects(text_bb):
                    all_text.append(drawing)
        return all_text

    def get_drawings(self, bounding_box, containing):
        # get all drawings in source bounding box
        all_drawings = []
        # Drawings are:
        #   Shapes (line, arc, circle, rect, polygon), dimensions, text, layer align target.
        # For Drawings typenames see KICAD_T in include/core/typeinfo.h in KiCad source
        # and m_drawings in pcbnew/board.cpp.
        # If SHAPE type needs to be differentiated:
        #   pcbnew.PCB_SHAPE_TYPE_T_asString(someshapeobject.Type()) (see include/board_item.h)
        for drawing in self.board.GetDrawings():
            if isinstance(drawing, pcbnew.PCB_TEXT):
                # text items are handled separately
                continue
            dwg_bb = drawing.GetBoundingBox()
            if containing:
                if bounding_box.Contains(dwg_bb):
                    all_drawings.append(drawing)
            else:
                if bounding_box.Intersects(dwg_bb):
                    all_drawings.append(drawing)
        return all_drawings

    @staticmethod
    def get_footprint_text_items(footprint):
        """ get all text item belonging to a footprint """
        list_of_items = [footprint.fp.Reference(), footprint.fp.Value()]

        footprint_items = footprint.fp.GraphicalItems()
        for item in footprint_items:
            if type(item) is pcbnew.FP_TEXT:
                list_of_items.append(item)
        return list_of_items

    def get_sheet_anchor_footprint(self, sheet):
        # get all footprints on this sheet
        sheet_footprints = self.get_footprints_on_sheet(sheet)
        # get anchor footprint
        list_of_possible_anchor_footprints = []
        for fp in sheet_footprints:
            if fp.fp_id == self.src_anchor_fp.fp_id:
                list_of_possible_anchor_footprints.append(fp)

        # if there is only one
        if len(list_of_possible_anchor_footprints) == 1:
            sheet_anchor_fp = list_of_possible_anchor_footprints[0]
        # if there are more then one, we're dealing with multiple hierarchy
        # the correct one is the one who's path is the best match to the sheet path
        else:
            list_of_matches = []
            for fp in list_of_possible_anchor_footprints:
                index = list_of_possible_anchor_footprints.index(fp)
                matches = 0
                for item in self.src_anchor_fp.sheet_id:
                    if item in fp.sheet_id:
                        matches = matches + 1
                list_of_matches.append((index, matches))
            # select the one with most matches
            index, _ = max(list_of_matches, key=lambda item: item[1])
            sheet_anchor_fp = list_of_possible_anchor_footprints[index]
        return sheet_anchor_fp

    def get_net_pairs(self, sheet):
        """ find all net pairs between source sheet and current sheet"""
        # find all footprints, pads and nets on this sheet
        sheet_footprints = self.get_footprints_on_sheet(sheet)

        # find all net pairs via same footprint pads,
        net_pairs = []
        net_dict = {}
        # construct footprint pairs
        fp_matches = []
        for s_fp in self.src_footprints:
            fp_matches.append([s_fp.fp, s_fp.fp_id, s_fp.sheet_id])

        for d_fp in sheet_footprints:
            for fp in fp_matches:
                if fp[1] == d_fp.fp_id:
                    index = fp_matches.index(fp)
                    fp_matches[index].append(d_fp.fp)
                    fp_matches[index].append(d_fp.fp_id)
                    fp_matches[index].append(d_fp.sheet_id)
        # find closest match
        fp_pairs = []
        fp_pairs_by_reference = []
        for index in range(len(fp_matches)):
            fp = fp_matches[index]
            # get number of matches
            matches = (len(fp) - 3) // 3
            # if more than one match, get the most likely one
            # this is when replicating a sheet which consist of two or more identical subsheets (multiple hierachy)
            # todo might want to find common code with code in "get_sheet_anchor_footprint"
            if matches > 1:
                match_len = []
                for index in range(0, matches):
                    match_len.append(len(set(fp[2]) & set(fp[2 + 3 * (index + 1)])))
                index = match_len.index(max(match_len))
                fp_pairs.append((fp[0], fp[3 * (index + 1)]))
                fp_pairs_by_reference.append((fp[0].GetReference(), fp[3 * (index + 1)].GetReference()))
            # if only one match
            elif matches == 1:
                fp_pairs.append((fp[0], fp[3]))
                fp_pairs_by_reference.append((fp[0].GetReference(), fp[3].GetReference()))
            # can not find at least one matching footprint
            elif matches == 0:
                raise LookupError("Could not find at least one matching footprint for: " + fp[0].GetReference() +
                                  ".\nPlease make sure that schematics and layout are in sync.")

        # prepare the list of pad pairs
        pad_pairs = []
        for x in range(len(fp_pairs)):
            pad_pairs.append([])

        for pair in fp_pairs:
            index = fp_pairs.index(pair)
            # get all footprint pads
            src_fp_pads = pair[0].Pads()
            dst_fp_pads = pair[1].Pads()
            # create a list of padsnames and pads
            s_pads = []
            d_pads = []
            for pad in src_fp_pads:
                s_pads.append((pad.GetName(), pad))
            for pad in dst_fp_pads:
                d_pads.append((pad.GetName(), pad))
            # sort by padnames
            s_pads.sort(key=lambda tup: tup[0])
            d_pads.sort(key=lambda tup: tup[0])
            # extract pads and append them to pad pairs list
            pad_pairs[index].append([x[1] for x in s_pads])
            pad_pairs[index].append([x[1] for x in d_pads])

        for pair in fp_pairs:
            index = fp_pairs.index(pair)
            # get their pads
            src_fp_pads = pad_pairs[index][0]
            dst_fp_pads = pad_pairs[index][1]
            # I am going to assume pads are in the same order
            s_nets = []
            d_nets = []
            # get netlists for each pad
            for p_pad in src_fp_pads:
                pad_name = p_pad.GetName()
                s_nets.append((pad_name, p_pad.GetNetname()))
            for s_pad in dst_fp_pads:
                pad_name = s_pad.GetName()
                d_nets.append((pad_name, s_pad.GetNetname()))
                net_dict[s_pad.GetNetname()] = s_pad.GetNet()
            # sort both lists by pad name
            # so that they have the same order - needed in some cases
            # as the iterator through the pads list does not return pads always in the proper order
            s_nets.sort(key=lambda tup: tup[0])
            d_nets.sort(key=lambda tup: tup[0])
            # build list of net tuples
            for net in s_nets:
                index = get_index_of_tuple(s_nets, 1, net[1])
                net_pairs.append((s_nets[index][1], d_nets[index][1]))

        # remove duplicates
        net_pairs_clean = list(set(net_pairs))

        return net_pairs_clean, net_dict

    def prepare_for_replication(self, level, containing):
        # get a list of source footprints for replication
        logger.info("Getting the list of source footprints")
        self.update_progress(self.stage, 0 / 8, None)
        self.src_footprints = self.get_footprints_on_sheet(level)
        # get the rest of the footprints
        logger.info("Getting the list of all the remaining footprints")
        self.update_progress(self.stage, 1 / 8, None)
        self.other_footprints = self.get_footprints_not_on_sheet(level)
        # get nets local to source footprints
        logger.info("Getting nets local to source footprints")
        self.update_progress(self.stage, 2 / 8, None)
        self.src_local_nets = self.get_local_nets(self.src_footprints, self.other_footprints)
        # get source bounding box
        logger.info("Getting source bounding box")
        self.update_progress(self.stage, 3 / 8, None)
        self.src_bounding_box = self.get_footprints_bounding_box(self.src_footprints)
        # get source tracks
        logger.info("Getting source tracks")
        self.update_progress(self.stage, 4 / 8, None)
        self.src_tracks = self.get_tracks(self.src_bounding_box, self.src_local_nets, containing)
        # get source zones
        logger.info("Getting source zones")
        self.update_progress(self.stage, 5 / 8, None)
        self.src_zones = self.get_zones(self.src_bounding_box, containing)
        # get source text items
        logger.info("Getting source text items")
        self.update_progress(self.stage, 6 / 8, None)
        self.src_text = self.get_text_items(self.src_bounding_box, containing)
        # get source drawings
        logger.info("Getting source text items")
        self.update_progress(self.stage, 7 / 8, None)
        self.src_drawings = self.get_drawings(self.src_bounding_box, containing)
        self.update_progress(self.stage, 8 / 8, None)

    def replicate_footprints(self):
        logger.info("Replicating footprints")
        nr_sheets = len(self.dst_sheets)
        for st_index in range(nr_sheets):
            sheet = self.dst_sheets[st_index]
            progress = st_index / nr_sheets
            self.update_progress(self.stage, progress, None)
            logger.info("Replicating footprints on sheet " + repr(sheet))
            # get anchor footprints
            dst_anchor_fp = self.get_sheet_anchor_footprint(sheet)
            # get anchor angle with respect to source footprint
            dst_anchor_fp_angle = dst_anchor_fp.fp.GetOrientationDegrees()
            # get exact anchor position
            dst_anchor_fp_position = dst_anchor_fp.fp.GetPosition()

            anchor_delta_angle = self.src_anchor_fp.fp.GetOrientationDegrees() - dst_anchor_fp_angle
            anchor_delta_pos = dst_anchor_fp_position - self.src_anchor_fp.fp.GetPosition()

            # go through all footprints
            dst_footprints = self.get_footprints_on_sheet(sheet)
            nr_footprints = len(dst_footprints)
            for fp_index in range(nr_footprints):
                dst_fp = dst_footprints[fp_index]

                progress = progress + (1 / nr_sheets) * (1 / nr_footprints)
                self.update_progress(self.stage, progress, None)

                # skip locked footprints
                if dst_fp.fp.IsLocked() is True and self.replicate_locked_items is False:
                    continue

                # find proper match in source footprints
                src_fp = None
                list_of_possible_src_footprints = []
                for s_fp in self.src_footprints:
                    if s_fp.fp_id == dst_fp.fp_id:
                        list_of_possible_src_footprints.append(s_fp)

                # if there is more than one possible anchor, select the correct one
                if len(list_of_possible_src_footprints) == 1:
                    src_fp = list_of_possible_src_footprints[0]
                else:
                    list_of_matches = []
                    for fp in list_of_possible_src_footprints:
                        index = list_of_possible_src_footprints.index(fp)
                        matches = 0
                        for item in dst_fp.sheet_id:
                            if item in fp.sheet_id:
                                matches = matches + 1
                        list_of_matches.append((index, matches))
                    # check if list is empty, if it is, then it is highly likely that shematics and pcb are not in sync
                    if not list_of_matches:
                        raise LookupError("Can not find anchor (source) footprint for footprint: " + repr(dst_fp.ref)
                                          + "\n" + "Most likely, schematics and PCB are not in sync")
                    # select the one with most matches
                    index, _ = max(list_of_matches, key=lambda item: item[1])
                    src_fp = list_of_possible_src_footprints[index]

                # get footprint to clone position
                src_fp_orientation = src_fp.fp.GetOrientationDegrees()
                src_fp_pos = src_fp.fp.GetPosition()
                # get relative position with respect to source anchor
                src_anchor_pos = self.src_anchor_fp.fp.GetPosition()
                src_fp_flipped = src_fp.fp.IsFlipped()
                src_fp_delta_pos = src_fp_pos - src_anchor_pos

                # new orientation is simple
                new_orientation = src_fp_orientation - anchor_delta_angle
                old_pos = src_fp_delta_pos + dst_anchor_fp_position
                new_pos = rotate_around_point(old_pos, dst_anchor_fp_position, anchor_delta_angle)

                # convert to tuple of integers
                new_pos = [int(x) for x in new_pos]
                # place current footprint - only if current footprint is not also the anchor
                if dst_fp.ref != dst_anchor_fp.ref:
                    dst_fp.fp.SetPosition(pcbnew.wxPoint(*new_pos))

                    if dst_fp.fp.IsFlipped() != src_fp_flipped:
                        dst_fp.fp.Flip(dst_fp.fp.GetPosition(), False)
                    dst_fp.fp.SetOrientationDegrees(new_orientation)

                # Copy local settings.
                dst_fp.fp.SetLocalClearance(src_fp.fp.GetLocalClearance())
                dst_fp.fp.SetLocalSolderMaskMargin(src_fp.fp.GetLocalSolderMaskMargin())
                dst_fp.fp.SetLocalSolderPasteMargin(src_fp.fp.GetLocalSolderPasteMargin())
                dst_fp.fp.SetLocalSolderPasteMarginRatio(src_fp.fp.GetLocalSolderPasteMarginRatio())
                dst_fp.fp.SetZoneConnection(src_fp.fp.GetZoneConnection())

                # flip if dst anchor is flipped with regards to src anchor
                if self.src_anchor_fp.fp.IsFlipped() != dst_anchor_fp.fp.IsFlipped():
                    # ignore anchor fp
                    if dst_anchor_fp != dst_fp:
                        dst_fp.fp.Flip(dst_anchor_fp_position, False)
                        # also need to change the angle
                        new_pos = rotate_around_point(dst_fp.fp.GetPosition(), dst_anchor_fp_position, anchor_delta_angle - dst_anchor_fp_angle)
                        dst_fp.fp.SetPosition(pcbnew.wxPoint(*new_pos))
                        new_orientation = dst_fp.fp.GetOrientationDegrees() - (anchor_delta_angle - dst_anchor_fp_angle)
                        dst_fp.fp.SetOrientationDegrees(new_orientation)

                dst_fp_orientation = dst_fp.fp.GetOrientationDegrees()
                dst_fp_flipped = dst_fp.fp.IsFlipped()

                # replicate also text layout - also for anchor footprint. I am counting that the user is lazy and will
                # just position the anchors and will not edit them
                # get footprint text
                src_fp_text_items = self.get_footprint_text_items(src_fp)
                dst_fp_text_items = self.get_footprint_text_items(dst_fp)
                # check if both footprints (source and the one for replication) have the same number of text items
                if len(src_fp_text_items) != len(dst_fp_text_items):
                    raise LookupError(
                        "Source footprint: " + src_fp.ref + " has different number of text items (" + repr(
                            len(src_fp_text_items))
                        + ")\nthan footprint for replication: " + dst_fp.ref + " (" + repr(
                            len(dst_fp_text_items)) + ")")

                # replicate each text item
                src_text: pcbnew.FP_TEXT
                dst_text: pcbnew.FP_TEXT
                for src_text in src_fp_text_items:
                    txt_index = src_fp_text_items.index(src_text)
                    src_txt_pos = src_text.GetPosition()
                    src_txt_rel_pos = src_txt_pos - src_fp.fp.GetBoundingBox(False, False).Centre()
                    src_txt_orientation = src_text.GetTextAngle()
                    delta_angle = dst_fp_orientation - src_fp_orientation

                    dst_fp_pos = dst_fp.fp.GetBoundingBox(False, False).Centre()
                    dst_text = dst_fp_text_items[txt_index]

                    dst_text.SetLayer(src_text.GetLayer())
                    # properly set position
                    if src_fp_flipped != dst_fp_flipped:
                        if dst_fp.ref == "R302":
                            a = 2
                        dst_text.Flip(dst_anchor_fp_position, False)
                        dst_txt_rel_pos = [-src_txt_rel_pos[0], src_txt_rel_pos[1]]
                        angle = anchor_delta_angle - 180
                        dst_txt_rel_pos_rot = rotate_around_center(dst_txt_rel_pos, angle)
                        dst_txt_pos = dst_fp_pos + pcbnew.wxPoint(dst_txt_rel_pos_rot[0], dst_txt_rel_pos_rot[1])
                        dst_text.SetPosition(dst_txt_pos)
                        dst_text.SetTextAngle(-src_txt_orientation)
                        dst_text.SetMirrored(not src_text.IsMirrored())
                    else:
                        dst_txt_rel_pos = rotate_around_center(src_txt_rel_pos, delta_angle)
                        dst_txt_pos = dst_fp_pos + pcbnew.wxPoint(dst_txt_rel_pos[0], dst_txt_rel_pos[1])
                        dst_text.SetPosition(dst_txt_pos)
                        dst_text.SetTextAngle(src_txt_orientation - delta_angle * 10)
                        dst_text.SetMirrored(src_text.IsMirrored())

                    # set text parameters
                    dst_text.SetTextThickness(src_text.GetTextThickness())
                    dst_text.SetTextWidth(src_text.GetTextWidth())
                    dst_text.SetTextHeight(src_text.GetTextHeight())
                    dst_text.SetItalic(src_text.IsItalic())
                    dst_text.SetBold(src_text.IsBold())
                    dst_text.SetMultilineAllowed(src_text.IsMultilineAllowed())
                    dst_text.SetHorizJustify(src_text.GetHorizJustify())
                    dst_text.SetVertJustify(src_text.GetVertJustify())
                    dst_text.SetKeepUpright(src_text.IsKeepUpright())
                    dst_text.SetVisible(src_text.IsVisible())

    def replicate_tracks(self):
        logger.info("Replicating tracks")
        nr_sheets = len(self.dst_sheets)
        for st_index in range(nr_sheets):
            sheet = self.dst_sheets[st_index]
            progress = st_index / nr_sheets
            self.update_progress(self.stage, progress, None)
            logger.info("Replicating tracks on sheet " + repr(sheet))

            # get anchor footprint
            dst_anchor_fp = self.get_sheet_anchor_footprint(sheet)
            # get anchor angle with respect to source anchor footprint
            dst_anchor_fp_angle = dst_anchor_fp.fp.GetOrientation()
            # get exact anchor position
            dst_anchor_fp_position = dst_anchor_fp.fp.GetPosition()

            src_anchor_fp_angle = self.src_anchor_fp.fp.GetOrientation()
            src_anchor_fp_position = self.src_anchor_fp.fp.GetPosition()

            move_vector = dst_anchor_fp_position - src_anchor_fp_position
            delta_orientation = dst_anchor_fp_angle - src_anchor_fp_angle

            net_pairs, net_dict = self.get_net_pairs(sheet)

            # go through all the tracks
            nr_tracks = len(self.src_tracks)
            for track_index in range(nr_tracks):
                track = self.src_tracks[track_index]
                progress = progress + (1 / nr_sheets) * (1 / nr_tracks)
                self.update_progress(self.stage, progress, None)
                # get from which net we are cloning
                from_net_name = track.GetNetname()
                # find to net
                tup = [item for item in net_pairs if item[0] == from_net_name]
                # if net was not found, then the track is not part of this sheet and should not be cloned
                if not tup:
                    pass
                else:
                    to_net_name = tup[0][1]
                    to_net_code = net_dict[to_net_name].GetNetCode()
                    to_net_item = net_dict[to_net_name]

                    # make a duplicate, move it, rotate it, select proper net and add it to the board
                    new_track = track.Duplicate()
                    new_track.Rotate(src_anchor_fp_position, delta_orientation)
                    new_track.Move(move_vector)
                    new_track.SetNetCode(to_net_code)
                    new_track.SetNet(to_net_item)
                    if self.src_anchor_fp.fp.IsFlipped() != dst_anchor_fp.fp.IsFlipped():
                        new_track.Flip(dst_anchor_fp_position, False)
                        new_track.Rotate(dst_anchor_fp_position, 2*delta_orientation - 3600)
                    self.board.Add(new_track)

    def replicate_zones(self):
        """ method which replicates zones"""
        logger.info("Replicating zones")
        # start cloning
        nr_sheets = len(self.dst_sheets)
        for st_index in range(nr_sheets):
            sheet = self.dst_sheets[st_index]
            progress = st_index / nr_sheets
            self.update_progress(self.stage, progress, None)
            logger.info("Replicating zones on sheet " + repr(sheet))

            # get anchor footprint
            dst_anchor_fp = self.get_sheet_anchor_footprint(sheet)
            # get anchor angle with respect to source anchor footprint
            dst_anchor_fp_angle = dst_anchor_fp.fp.GetOrientation()
            # get exact anchor position
            dst_anchor_fp_position = dst_anchor_fp.fp.GetPosition()

            src_anchor_fp_angle = self.src_anchor_fp.fp.GetOrientation()
            src_anchor_fp_position = self.src_anchor_fp.fp.GetPosition()

            move_vector = dst_anchor_fp_position - src_anchor_fp_position
            delta_orientation = dst_anchor_fp_angle - src_anchor_fp_angle

            net_pairs, net_dict = self.get_net_pairs(sheet)
            # go through all the zones
            nr_zones = len(self.src_zones)
            for zone_index in range(nr_zones):
                zone = self.src_zones[zone_index]
                progress = progress + (1 / nr_sheets) * (1 / nr_zones)
                self.update_progress(self.stage, progress, None)

                # get from which net we are cloning
                from_net_name = zone.GetNetname()
                # if zone is not on copper layer it does not matter on which net it is
                if not zone.IsOnCopperLayer():
                    tup = [('', '')]
                else:
                    if from_net_name:
                        tup = [item for item in net_pairs if item[0] == from_net_name]
                    else:
                        tup = [('', '')]

                # there is no net
                if not tup:
                    # Allow keepout zones to be cloned.
                    if not zone.IsOnCopperLayer():
                        tup = [('', '')]

                # start the clone
                to_net_name = tup[0][1]
                if to_net_name == u'':
                    to_net_code = 0
                    to_net_item = self.board.FindNet(0)
                else:
                    to_net_code = net_dict[to_net_name].GetNetCode()
                    to_net_item = net_dict[to_net_name]

                # make a duplicate, move it, rotate it, select proper net and add it to the board
                new_zone = zone.Duplicate()
                new_zone.Rotate(src_anchor_fp_position, delta_orientation)
                new_zone.Move(move_vector)
                new_zone.SetNetCode(to_net_code)
                new_zone.SetNet(to_net_item)
                if self.src_anchor_fp.fp.IsFlipped() != dst_anchor_fp.fp.IsFlipped():
                    new_zone.Flip(dst_anchor_fp_position, False)
                    new_zone.Rotate(dst_anchor_fp_position, 2 * delta_orientation - 3600)
                self.board.Add(new_zone)

    def replicate_text(self):
        logger.info("Replicating text")
        # start cloning
        nr_sheets = len(self.dst_sheets)
        for st_index in range(nr_sheets):
            sheet = self.dst_sheets[st_index]
            progress = st_index / nr_sheets
            self.update_progress(self.stage, progress, None)
            logger.info("Replicating text on sheet " + repr(sheet))

            # get anchor footprint
            dst_anchor_fp = self.get_sheet_anchor_footprint(sheet)

            # get exact anchor position
            dst_anchor_fp_position = dst_anchor_fp.fp.GetPosition()
            dst_anchor_fp_angle = dst_anchor_fp.fp.GetOrientation()

            src_anchor_fp_angle = self.src_anchor_fp.fp.GetOrientation()
            src_anchor_fp_position = self.src_anchor_fp.fp.GetPosition()

            move_vector = dst_anchor_fp_position - src_anchor_fp_position
            delta_orientation = dst_anchor_fp_angle - src_anchor_fp_angle

            nr_text = len(self.src_text)
            for text_index in range(nr_text):
                text = self.src_text[text_index]
                progress = progress + (1 / nr_sheets) * (1 / nr_text)
                self.update_progress(self.stage, progress, None)

                new_text = text.Duplicate()
                new_text.Move(move_vector)
                new_text.Rotate(dst_anchor_fp_position, delta_orientation)
                if self.src_anchor_fp.fp.IsFlipped() != dst_anchor_fp.fp.IsFlipped():
                    new_text.Flip(dst_anchor_fp_position, False)
                    new_text.Rotate(dst_anchor_fp_position, 2 * delta_orientation - 3600)
                self.board.Add(new_text)

    def replicate_drawings(self):
        logger.info("Replicating drawings")
        nr_sheets = len(self.dst_sheets)
        for st_index in range(nr_sheets):
            sheet = self.dst_sheets[st_index]
            progress = st_index / nr_sheets
            self.update_progress(self.stage, progress, None)
            logger.info("Replicating drawings on sheet " + repr(sheet))

            # get anchor footprint
            dst_anchor_fp = self.get_sheet_anchor_footprint(sheet)
            # get exact anchor position
            dst_anchor_fp_position = dst_anchor_fp.fp.GetPosition()
            dst_anchor_fp_angle = dst_anchor_fp.fp.GetOrientation()

            src_anchor_fp_angle = self.src_anchor_fp.fp.GetOrientation()
            src_anchor_fp_position = self.src_anchor_fp.fp.GetPosition()

            move_vector = dst_anchor_fp_position - src_anchor_fp_position
            delta_orientation = dst_anchor_fp_angle - src_anchor_fp_angle

            # go through all the drawings
            nr_drawings = len(self.src_drawings)
            for dw_index in range(nr_drawings):
                drawing = self.src_drawings[dw_index]
                progress = progress + (1 / nr_sheets) * (1 / nr_drawings)
                self.update_progress(self.stage, progress, None)

                new_drawing = drawing.Duplicate()
                new_drawing.Move(move_vector)
                new_drawing.Rotate(dst_anchor_fp_position, delta_orientation)

                if self.src_anchor_fp.fp.IsFlipped() != dst_anchor_fp.fp.IsFlipped():
                    new_drawing.Flip(dst_anchor_fp_position, False)
                    new_drawing.Rotate(dst_anchor_fp_position, 2 * delta_orientation - 3600)
                self.board.Add(new_drawing)

    def remove_zones_tracks(self, containing):
        for index in range(len(self.dst_sheets)):
            sheet = self.dst_sheets[index]
            self.update_progress(self.stage, index / len(self.dst_sheets), None)
            # get footprints on a sheet
            fp_sheet = self.get_footprints_on_sheet(sheet)
            # get bounding box
            bounding_box = self.get_footprints_bounding_box(fp_sheet)
            # remove the tracks that are not on nets contained in this sheet
            nets_on_sheet = self.get_nets_from_footprints(fp_sheet)

            # remove tracks
            for track in self.get_tracks(bounding_box, nets_on_sheet, containing):
                # minus the tracks in source bounding box
                if track not in self.src_tracks:
                    self.board.RemoveNative(track)

            # remove zones
            for zone in self.get_zones(bounding_box, containing):
                self.board.RemoveNative(zone)

            # remove text items
            for text_item in self.get_text_items(bounding_box, containing):
                self.board.RemoveNative(text_item)

            for drawing in self.get_drawings(bounding_box, containing):
                self.board.RemoveNative(drawing)

    def removing_duplicates(self):
        remove_duplicates(self.board)

    def replicate_layout(self, src_anchor_fp, level, dst_sheets,
                         containing, remove, tracks, zones, text, drawings, rm_duplicates, rep_locked):
        logger.info("Starting replication of sheets: " + repr(dst_sheets)
                    + "\non level: " + repr(level)
                    + "\nwith tracks=" + repr(tracks) + ", zone=" + repr(zones) + ", text=" + repr(text)
                    + ", containing=" + repr(containing) + ", remove=" + repr(remove) + ", locked=" + repr(rep_locked))

        self.level = level
        self.src_anchor_fp = src_anchor_fp
        self.dst_sheets = dst_sheets
        self.replicate_locked_items = rep_locked

        if remove:
            self.max_stages = 2
        else:
            self.max_stages = 0
        if tracks:
            self.max_stages = self.max_stages + 1
        if zones:
            self.max_stages = self.max_stages + 1
        if text:
            self.max_stages = self.max_stages + 1
        if drawings:
            self.max_stages = self.max_stages + 1
        if rm_duplicates:
            self.max_stages = self.max_stages + 1

        self.update_progress(self.stage, 0.0, "Preparing for replication")
        self.prepare_for_replication(level, containing)
        if remove:
            logger.info("Removing tracks and zones, before footprint placement")
            self.stage = 2
            self.update_progress(self.stage, 0.0, "Removing zones and tracks")
            self.remove_zones_tracks(containing)
        self.stage = 3
        self.update_progress(self.stage, 0.0, "Replicating footprints")
        self.replicate_footprints()
        if remove:
            logger.info("Removing tracks and zones, after footprint placement")
            self.stage = 4
            self.update_progress(self.stage, 0.0, "Removing zones and tracks")
            self.remove_zones_tracks(containing)
        if tracks:
            self.stage = 5
            self.update_progress(self.stage, 0.0, "Replicating tracks")
            self.replicate_tracks()
        if zones:
            self.stage = 6
            self.update_progress(self.stage, 0.0, "Replicating zones")
            self.replicate_zones()
        if text:
            self.stage = 7
            self.update_progress(self.stage, 0.0, "Replicating text")
            self.replicate_text()
        if drawings:
            self.stage = 8
            self.update_progress(self.stage, 0.0, "Replicating drawings")
            self.replicate_drawings()
        if rm_duplicates:
            self.stage = 9
            self.update_progress(self.stage, 0.0, "Removing duplicates")
            self.removing_duplicates()
        # finally at the end refill the zones
        filler = pcbnew.ZONE_FILLER(self.board)
        filler.Fill(self.board.Zones())


