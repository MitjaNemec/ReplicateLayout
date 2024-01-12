# -*- coding: utf-8 -*-
#  replicate_layout.py
#
# Copyright (C) 2019-2023 Mitja Nemec
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
from collections import defaultdict
import os
import logging
import itertools
import math
from difflib import SequenceMatcher
try:
    from .remove_duplicates import remove_duplicates
except:
    from remove_duplicates import remove_duplicates

Footprint = namedtuple('Footprint', ['ref', 'fp', 'fp_id', 'sheet_id', 'filename'])
logger = logging.getLogger(__name__)

Settings = namedtuple('Settings', ['rep_tracks', 'rep_zones', 'rep_text', 'rep_drawings',
                                   'group_layouts', 'group_footprints', 'group_tracks', 'group_zones', 'group_text', 'group_drawings',
                                   'rep_locked_tracks', 'rep_locked_zones', 'rep_locked_text', 'rep_locked_drawings',
                                   'intersecting', 'group_items', 'group_only', 'locked_fps', 'remove'],
                         defaults=[True, True, True, True,
                                   False, False, False, False, False, False,
                                   True, True, True, True,
                                   False, False, False, False, False])


def rotate_around_center(coordinates, angle):
    """ rotate coordinates for a defined angle in degrees around coordinate center"""
    new_x = coordinates[0] * math.cos(2 * math.pi * angle / 360) \
            - coordinates[1] * math.sin(2 * math.pi * angle / 360)
    new_y = coordinates[0] * math.sin(2 * math.pi * angle / 360) \
            + coordinates[1] * math.cos(2 * math.pi * angle / 360)
    return int(new_x), int(new_y)


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


def flipped_angle(angle):
    if angle > 0:
        return 180 - angle
    else:
        return -180 - angle


class Replicator:
    def __init__(self, board, src_anchor_fp_ref, update_func=update_progress):
        self.board = board
        self.stage = 1
        self.max_stages = 0
        self.update_progress = update_func

        self.level = None
        self.settings = Settings
        self.src_anchor_fp = None
        self.src_anchor_fp_group = None
        self.replicate_locked_footprints = None
        self.src_sheet = None
        self.dst_sheets = []
        self.dst_groups = []
        self.src_footprints = []
        self.other_footprints = []
        self.src_bounding_box = None
        self.src_tracks = []
        self.src_zones = []
        self.src_text = []
        self.src_drawings = []

        self.connectivity_issues = set()

        self.pcb_filename = os.path.abspath(board.GetFileName())
        self.sch_filename = self.pcb_filename.replace(".kicad_pcb", ".kicad_sch")
        self.project_folder = os.path.dirname(self.pcb_filename)

        # construct a list of footprints with all pertinent data
        logger.info('getting a list of all footprints on board')
        footprints = board.GetFootprints()
        self.footprints = []

        # get dict_of_sheets from layout data only (through footprint Sheetfile and Sheetname properties)
        self.dict_of_sheets = {}
        unique_sheet_ids = set()
        for fp in footprints:
            # construct a set of unique sheets from footprint properties
            path = fp.GetPath().AsString().upper().replace('00000000-0000-0000-0000-0000', '').split("/")
            sheet_path = path[0:-1]
            for x in sheet_path:
                unique_sheet_ids.add(x)

            sheet_id = self.get_sheet_id(fp)
            try:
                sheet_file = fp.GetSheetfile()
                sheet_name = fp.GetSheetname()
            except KeyError:
                logger.info("Footprint " + fp.GetReference() +
                            " does not have Sheetfile property, it will not be replicated."
                            " Most likely it is only in layout")
                continue
            # footprint is in the schematics and has Sheetfile property
            if sheet_file and sheet_id:
                self.dict_of_sheets[sheet_id] = [sheet_name, sheet_file]
            # footprint is in the schematics but has empty Sheetfile properties
            elif sheet_id:
                logger.info("Footprint " + fp.GetReference() + " has empty Sheetfile property")
                raise LookupError("Footprint " + str(
                    fp.GetReference()) + " has empty Sheetfile and Sheetname properties. "
                                         "You need to update the layout from schematics")
            # footprint is on root level
            else:
                logger.debug("Footprint " + fp.GetReference() + " on root level")
                continue
        # catch corner cases with nested hierarchy, where some hierarchical pages don't have any footprints
        unique_sheet_ids.remove("")
        if len(unique_sheet_ids) > len(self.dict_of_sheets):
            # open root schematics file and parse for other schematics files
            # This might be prone to errors regarding path discovery
            # thus it is used only in corner cases
            schematic_found = {}
            self.parse_schematic_files(self.sch_filename, schematic_found)
            self.dict_of_sheets = schematic_found

        # construct a list of all the footprints
        for fp in footprints:
            try:
                sheet_file = fp.GetSheetfile()
                sheet_name = fp.GetSheetname()
                fp_tuple = Footprint(fp=fp,
                                     fp_id=self.get_footprint_id(fp),
                                     sheet_id=self.get_sheet_path(fp)[0],
                                     filename=self.get_sheet_path(fp)[1],
                                     ref=fp.GetReference())
                self.footprints.append(fp_tuple)
            except KeyError:
                pass

        # find anchor footprint and it's group
        self.src_anchor_fp = self.get_fp_by_ref(src_anchor_fp_ref)
        if self.src_anchor_fp.fp.GetParentGroup():
            self.src_anchor_fp_group = self.src_anchor_fp.fp.GetParentGroup().GetName()
        else:
            self.src_anchor_fp_group = None
        # TODO check if there is any other footprint with same ID as anchor footprint

        # get net-dict
        # you get the netcode by self.netdict.GetNetItem("netname")
        self.netdict = self.board.GetNetInfo()

    def parse_schematic_files(self, filename, dict_of_sheets):
        filename_dir = os.path.dirname(filename)

        with open(filename, encoding='utf-8') as f:
            contents = f.read()

        indexes = []
        level = []
        sheet_definitions = []
        new_lines = []
        lvl = 0
        # get the nesting levels at index
        for idx in range(len(contents) - 20):
            if contents[idx] == "(":
                lvl = lvl + 1
                level.append(lvl)
                indexes.append(idx)
            if contents[idx] == ")":
                lvl = lvl - 1
                level.append(lvl)
                indexes.append(idx)
            if contents[idx] == "\n":
                new_lines.append(idx)
            a = contents[idx:idx + 20]
            if a.startswith("(sheet\n") or a.startswith("(sheet "):
                sheet_definitions.append(idx)

        start_idx = sheet_definitions
        end_idx = sheet_definitions[1:]
        end_idx.append(len(contents))
        braces = list(zip(indexes, level))
        # parse individual sheet definitions (if any)
        for start, end in zip(start_idx, end_idx):
            def next_bigger(l, v):
                for m in l:
                    if m > v:
                        return m

            uuid_loc = contents[start:end].find('(uuid') + start
            uuid_loc_end = next_bigger(new_lines, uuid_loc)
            uuid_complete_string = contents[uuid_loc:uuid_loc_end]
            uuid = uuid_complete_string.strip("(uuid").strip(")").replace("\"", '').upper().lstrip()

            v8encoding = contents[start:end].find('(property "Sheetname\"')
            v7encoding = contents[start:end].find('(property "Sheet name\"')
            if v8encoding != -1:
                offset = v8encoding
            elif v7encoding != -1:
                offset = v7encoding
            else:
                logger.info(f'Did not found sheetname properties in the schematic file '
                            f'in {filename} line:{str(i)}')
                raise LookupError(f'Did not found sheetname properties in the schematic file '
                                  f'in {filename} line:{str(i)}. Unsupported schematics file format')
            sheetname_loc = offset + start
            sheetname_loc_end = next_bigger(new_lines, sheetname_loc)
            sheetname_complete_string = contents[sheetname_loc:sheetname_loc_end]
            sheetname = sheetname_complete_string.strip("(property").split('"')[1::2][1]

            v8encoding = contents[start:end].find('(property "Sheetfile\"')
            v7encoding = contents[start:end].find('(property "Sheet file\"')
            if v8encoding != -1:
                offset = v8encoding
            elif v7encoding != -1:
                offset = v7encoding
            else:
                logger.info(f'Did not found sheetfile properties in the schematic file '
                            f'in {filename}.')
                raise LookupError(f'Did not found sheetfile properties in the schematic file '
                                  f'in {filename}. Unsupported schematics file format')
            sheetfile_loc = offset + start
            sheetfile_loc_end = next_bigger(new_lines, sheetfile_loc)
            sheetfile_complete_string = contents[sheetfile_loc:sheetfile_loc_end]
            sheetfile = sheetfile_complete_string.strip("(property").split('"')[1::2][1]

            sheetfilepath = os.path.join(filename_dir, sheetfile)
            dict_of_sheets[uuid] = [sheetname, sheetfile]

            # test if newfound file can be opened
            if not os.path.exists(sheetfilepath):
                raise LookupError(f'File {sheetfilepath} does not exists. This is either due to error in parsing'
                                  f' schematics files, missing schematics file or an error within the schematics')
            # open a newfound file and look for nested sheets
            self.parse_schematic_files(sheetfilepath, dict_of_sheets)
            pass
        return

    def replicate_layout(self, src_anchor_fp, level, dst_sheets,
                         settings, rm_duplicates):
        logger.info("Starting replication of sheets: " + repr(dst_sheets)
                    + "\non level: " + repr(level)
                    + "\nwith tracks=" + repr(settings.rep_tracks) + ", zone=" + repr(settings.rep_zones)
                    + ", text=" + repr(settings.rep_text) + ", text=" + repr(settings.rep_drawings)
                    + ", intersecting=" + repr(settings.intersecting) + ", remove=" + repr(settings.remove)
                    + ", locked footprints=" + repr(settings.locked_fps) + ", group_only=" + repr(settings.group_only))

        self.level = level
        self.src_anchor_fp = src_anchor_fp
        self.dst_sheets = dst_sheets
        self.replicate_locked_footprints = settings.locked_fps

        self.src_sheet = level

        if settings.remove:
            self.max_stages = 2
        else:
            self.max_stages = 0
        if settings.rep_tracks:
            self.max_stages = self.max_stages + 1
        if settings.rep_zones:
            self.max_stages = self.max_stages + 1
        if settings.rep_text:
            self.max_stages = self.max_stages + 1
        if settings.rep_drawings:
            self.max_stages = self.max_stages + 1
        if rm_duplicates:
            self.max_stages = self.max_stages + 1

        self.update_progress(self.stage, 0.0, "Preparing for replication")
        self.prepare_for_replication(level, settings)
        if settings.remove:
            logger.info("Removing tracks and zones, before footprint placement")
            self.stage = 2
            self.update_progress(self.stage, 0.0, "Removing zones and tracks")
            self.remove_zones_tracks(settings.intersecting)
        self.stage = 3
        self.update_progress(self.stage, 0.0, "Replicating footprints")
        self.replicate_footprints(settings)
        if settings.remove:
            logger.info("Removing tracks and zones, after footprint placement")
            self.stage = 4
            self.update_progress(self.stage, 0.0, "Removing zones and tracks")
            self.remove_zones_tracks(settings.intersecting)
        if settings.rep_tracks:
            self.stage = 5
            self.update_progress(self.stage, 0.0, "Replicating tracks")
            self.replicate_tracks(settings)
        if settings.rep_zones:
            self.stage = 6
            self.update_progress(self.stage, 0.0, "Replicating zones")
            self.replicate_zones(settings)
        if settings.rep_text:
            self.stage = 7
            self.update_progress(self.stage, 0.0, "Replicating text")
            self.replicate_text(settings)
        if settings.rep_drawings:
            self.stage = 8
            self.update_progress(self.stage, 0.0, "Replicating drawings")
            self.replicate_drawings(settings)
        if rm_duplicates:
            self.stage = 9
            self.update_progress(self.stage, 0.0, "Removing duplicates")
            self.removing_duplicates()
        # finally at the end refill the zones
        filler = pcbnew.ZONE_FILLER(self.board)
        filler.Fill(self.board.Zones())

    def prepare_for_replication(self, level, settings):
        # get a list of source footprints for replication
        logger.info("Getting the list of source footprints")
        self.update_progress(self.stage, 0 / 8, None)

        # if needed filter them by group
        anchor_sheet_footprints = self.get_footprints_on_sheet(level)
        self.src_bounding_box = self.get_footprints_bounding_box(anchor_sheet_footprints)
        self.src_footprints = self.get_footprints_for_replication(level, self.src_bounding_box, settings)
        excluded_footprints = [fp for fp in anchor_sheet_footprints if fp not in self.src_footprints]

        # get the rest of the footprints
        logger.info("Getting the list of all the remaining footprints")
        self.update_progress(self.stage, 1 / 6, None)
        self.other_footprints = self.get_footprints_not_on_sheet(level)
        self.other_footprints.extend(excluded_footprints)
        # TODO we might need to recalculate bounding box - if so, this has to be ported to highlighting code

        # get source tracks
        logger.info("Getting source tracks")
        self.update_progress(self.stage, 2 / 6, None)
        self.src_tracks = self.get_tracks_for_replication(level, self.src_bounding_box, settings)
        # get source zones
        logger.info("Getting source zones")
        self.update_progress(self.stage, 3 / 6, None)
        self.src_zones = self.get_zones_for_replication(level, self.src_bounding_box, settings)
        # get source text items
        logger.info("Getting source text items")
        self.update_progress(self.stage, 4 / 6, None)
        self.src_text = self.get_text_for_replication(self.src_bounding_box, settings)
        # get source drawings
        logger.info("Getting source drawing items")
        self.update_progress(self.stage, 5 / 6, None)
        self.src_drawings = self.get_drawings_for_replication(level, self.src_bounding_box, settings)

        # get all the existing groups
        groups = self.board.Groups()
        g_names = []
        for g in groups:
            g_names.append(g.GetName())

        # create groups for each destination layout if selected
        if settings.group_layouts:
            for sheet in self.dst_sheets:
                dst_group_name = "Replicated Group {}".format(sheet)
                # check if this group already exists
                # TODO this should no be an issue as existing group can/should be used for deletion of items
                if dst_group_name in g_names:
                    raise LookupError(f"Destination group {dst_group_name} already exists")
                dst_group = pcbnew.PCB_GROUP(None)
                dst_group.SetName(dst_group_name)
                self.board.Add(dst_group)
                # store destination lauouts' groups
                self.dst_groups.append(dst_group)

        # check if any destination footprints are already members of some groups
        for sheet in self.dst_sheets:
            dst_sheet_fps = self.get_footprints_on_sheet(sheet)
            for fp in dst_sheet_fps:
                fp_group = fp.fp.GetParentGroup()
                dst_group = "Replicated Group {}".format(sheet)
                if (fp_group is not None) and (fp_group != dst_group):
                    raise LookupError(f"Destination footprint {fp} is a member of a different group ({fp_group}). "
                                      f"All destination plugin have either have to be members of destination group ({dst_group})"
                                      f" or no group at all.")

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

    @staticmethod
    def filter_items_by_group(items, group):
        items_in_group = []
        for item in items:
            item_group = item.GetParentGroup()
            if item_group and group == item_group.GetName():
                items_in_group.append(item)
        return items_in_group

    @staticmethod
    def filter_footprints_by_group(footprints, group):
        items_in_group = []
        for fp in footprints:
            fp_group = fp.fp.GetParentGroup()
            if hasattr(fp_group, 'GetName'):
                if group and fp_group.GetName():
                    items_in_group.append(fp)
        return items_in_group

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
        bounding_box = footprints[0].fp.GetBoundingBox(False, False)
        top = bounding_box.GetTop()
        bottom = bounding_box.GetBottom()
        left = bounding_box.GetLeft()
        right = bounding_box.GetRight()
        # iterate through the rest of the footprints and resize bounding box accordingly
        for fp in footprints:
            fp_box = fp.fp.GetBoundingBox(False, False)
            top = min(top, fp_box.GetTop())
            bottom = max(bottom, fp_box.GetBottom())
            left = min(left, fp_box.GetLeft())
            right = max(right, fp_box.GetRight())

        position = pcbnew.VECTOR2I(left, top)
        size = pcbnew.VECTOR2I(right - left, bottom - top)
        bounding_box = pcbnew.BOX2I(position, size)
        return bounding_box

    def get_tracks(self, bounding_box, containing, exclusive_nets=None):
        # get_all tracks
        if exclusive_nets is None:
            exclusive_nets = []
        all_tracks = self.board.GetTracks()
        tracks = []
        # keep only tracks that are within our bounding box
        for track in all_tracks:
            track_bb = track.GetBoundingBox()
            # if track is contained or intersecting the bounding box
            if (containing and bounding_box.Contains(track_bb)) or \
                    (not containing and bounding_box.Intersects(track_bb)):
                tracks.append(track)
            # even if track is not within the bounding box, but is on the completely local net
            else:
                # check if it on a local net
                if track.GetNetname() in exclusive_nets:
                    # and add it to the
                    tracks.append(track)
        return tracks

    def get_zones(self, bounding_box, containing, exclusive_nets=None):
        if exclusive_nets is None:
            exclusive_nets = []
        # get all zones
        all_zones = []
        for zone_id in range(self.board.GetAreaCount()):
            all_zones.append(self.board.GetArea(zone_id))
        # find all zones which are within the bounding box
        zones = []
        for zone in all_zones:
            zone_bb = zone.GetBoundingBox()
            if (containing and bounding_box.Contains(zone_bb)) or \
                    (not containing and bounding_box.Intersects(zone_bb)):
                zones.append(zone)
            # even if track is not within the bounding box, but is on the completely local net
            else:
                if zone.GetNetname() in exclusive_nets:
                    # and add it to the
                    zones.append(zone)
        return zones

    def get_text_items(self, bounding_box, containing, outside=False):
        # get all text objects in bounding box
        all_text = []
        for drawing in self.board.GetDrawings():
            if not isinstance(drawing, pcbnew.PCB_TEXT):
                continue
            if not outside:
                text_bb = drawing.GetBoundingBox()
                if containing:
                    if bounding_box.Contains(text_bb):
                        all_text.append(drawing)
                else:
                    if bounding_box.Intersects(text_bb):
                        all_text.append(drawing)
            else:
                text_bb = drawing.GetBoundingBox()
                if not bounding_box.Contains(text_bb):
                    all_text.append(drawing)
        return all_text

    def get_drawings(self, bounding_box, containing, outside=False):
        # get all drawings in source bounding box
        all_drawings = []
        for drawing in self.board.GetDrawings():
            if isinstance(drawing, pcbnew.PCB_TEXT):
                # text items are handled separately
                continue
            if not outside:
                dwg_bb = drawing.GetBoundingBox()
                if containing:
                    if bounding_box.Contains(dwg_bb):
                        all_drawings.append(drawing)
                else:
                    if bounding_box.Intersects(dwg_bb):
                        all_drawings.append(drawing)
            else:
                dwg_bb = drawing.GetBoundingBox()
                if not bounding_box.Contains(dwg_bb):
                    all_drawings.append(drawing)
        return all_drawings

    @staticmethod
    def get_footprint_text_items(footprint):
        """ get all text item belonging to a footprint """
        list_of_items = [footprint.fp.Reference(), footprint.fp.Value()]

        footprint_items = footprint.fp.GraphicalItems()
        for item in footprint_items:
            if type(item) is pcbnew.PCB_TEXT:
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
            index, _ = max(list_of_matches, key=lambda x: x[1])
            sheet_anchor_fp = list_of_possible_anchor_footprints[index]
        return sheet_anchor_fp

    def get_net_pairs(self, sheet):
        """ find all net pairs between source sheet and current sheet"""
        # find all footprints, pads and nets on this sheet
        sheet_footprints = self.get_footprints_on_sheet(sheet)

        # find all net pairs via same footprint pads,
        # first find footprint matches
        fp_matches = defaultdict(list)
        for d_fp in sheet_footprints:
            for s_fp in self.src_footprints:
                if d_fp.fp_id == s_fp.fp_id:
                    fp_matches[s_fp.ref].append((s_fp, d_fp))

        # from matching footprints find closest match if needed
        fp_pairs = defaultdict(list)
        for key, value in fp_matches.items():
            matches = len(value)
            if matches == 0:
                raise LookupError("Could not find at least one matching footprint for: " + key +
                                  ".\nPlease make sure that schematics and layout are in sync.")
            if matches == 1:
                fp_pairs[key] = value[0]
            # if more than one match, get the most likely one
            # this is when replicating a sheet which consist of two or more identical subsheets (multiple hierachy)
            # the closest match is the one where most of the sheet_id matches
            if matches > 1:
                match_len = []
                for match in value:
                    match_len.append(len(set(match[0].sheet_id) & set(match[1].sheet_id)))
                index = match_len.index(max(match_len))
                fp_pairs[key] = value[index]

        # For each pad pair get the net pair, and check if it makes sense
        connectivity_issues = []
        net_pairs = []
        for fp_ref, fp_pair in fp_pairs.items():
            src_fp_pads = fp_pair[0].fp.Pads()
            dst_fp_pads = fp_pair[1].fp.Pads()
            # create a list of pads names and pads
            s_pads = []
            d_pads = []
            for pad in src_fp_pads:
                s_pads.append((pad.GetName(), pad))
            for pad in dst_fp_pads:
                d_pads.append((pad.GetName(), pad))
            # sort by pad names
            s_pads.sort(key=lambda tup: tup[0])
            d_pads.sort(key=lambda tup: tup[0])
            # add to dict
            fp_net_pairs = dict(zip([x[0] for x in d_pads] ,list(zip([x[1].GetNetname() for x in s_pads], [x[1].GetNetname() for x in d_pads]))))
            # go through all net pairs
            for pad_nr, net_pair in fp_net_pairs.items():
                # if net names match
                if net_pair[0] == net_pair[1]:
                    net_pairs.append(net_pair)
                    continue
                # get netname depth
                src_net_path = net_pair[0].split("/")
                dst_net_path = net_pair[1].split("/")
                src_net_depth = len(src_net_path)
                dst_net_depth = len(dst_net_path)
                net_delta_depth = src_net_depth-dst_net_depth
                src_fp_depth = len(fp_pair[0].sheet_id)
                dst_fp_depth = len(fp_pair[1].sheet_id)
                fp_delta_depth = src_fp_depth - dst_fp_depth
                # if both nets are local, they should match
                if (src_net_depth == 1) and (dst_net_depth == 1):
                    net_pairs.append(net_pair)
                    continue
                # otherwise  just look at the net name similarity. And if they are pretty similar be content
                match_level = self.find_match_level(src_net_path, dst_net_path)
                if match_level > 0.8:
                    net_pairs.append(net_pair)
                    continue

                # if I didn't find proper pair, append it anyway but addit to the list for reporting a warnning
                net_pairs.append(net_pair)
                logger.warning(f"Significant difference between src net: {src_net_path} and dst net: {dst_net_path}, "
                               f"with src_net_depth={src_net_depth}, dst_net_depth={dst_net_depth}, "
                               f"src_fp_depth={src_fp_depth}, dst_fp_depth={dst_fp_depth}, match level {match_level:.2f}")
                connectivity_issues.append((fp_pair[1].ref, pad_nr))
        if connectivity_issues:
            """
            report_string = ""
            for item in connectivity_issues:
                report_string = report_string + f"Footprint {item[0]}, pad {item[1]}\n"
            logger.info(f"Looks like the design has an exotic connectivity that is not supported by the plugin\n"
                        f"Make sure that you check the connectivity around:\n" + report_string)
            """
            self.connectivity_issues.update(connectivity_issues)

        # remove duplicates
        net_pairs_clean = list(set(net_pairs))
        logger.info("Net pairs for sheet " + repr(sheet) + " :" + repr(net_pairs_clean))

        return net_pairs_clean

    @staticmethod
    def find_match_level(netname_a, netname_b):
        len_nets_1 = len(netname_a)
        len_nets_2 = len(netname_b)
        # if both lengths are the same
        if len_nets_1 == len_nets_2:
            good_match_count = 0
            for i in range(len_nets_1):
                for j in range(len_nets_2):
                    a = netname_a[i]
                    b = netname_b[j]
                    match_ratio = SequenceMatcher(a=netname_a[i], b=netname_b[j]).ratio()
                    good_match_count = good_match_count + match_ratio
            # normalize for the lenght
            return good_match_count / len_nets_1
        # otherwise match all of the shortest ones with all of the longest ones
        else:
            good_match_count = 0
            if len_nets_1 < len_nets_2:
                for i in range(len_nets_1):
                    for j in range(len_nets_2):
                        a = netname_a[i]
                        b = netname_b[j]
                        match_ratio = SequenceMatcher(a=netname_a[i], b=netname_b[j]).ratio()
                        good_match_count = good_match_count + match_ratio
                return good_match_count / len_nets_1
            else:
                for i in range(len_nets_2):
                    for j in range(len_nets_1):
                        a = netname_b[i]
                        b = netname_a[j]
                        match_ratio = SequenceMatcher(a=netname_b[i], b=netname_a[j]).ratio()
                        good_match_count = good_match_count + match_ratio
                return good_match_count / len_nets_2

    def replicate_footprints(self, settings):
        logger.info("Replicating footprints")
        nr_sheets = len(self.dst_sheets)
        for st_index in range(nr_sheets):
            sheet = self.dst_sheets[st_index]

            progress = st_index / nr_sheets
            self.update_progress(self.stage, progress, None)
            logger.info("Replicating footprints on sheet " + repr(sheet))
            # get anchor footprint
            dst_anchor_fp = self.get_sheet_anchor_footprint(sheet)
            dst_anchor_fp_angle = dst_anchor_fp.fp.GetOrientationDegrees()
            dst_anchor_fp_position = dst_anchor_fp.fp.GetPosition()

            src_anchor_fp_angle = self.src_anchor_fp.fp.GetOrientationDegrees()

            anchor_delta_angle = src_anchor_fp_angle - dst_anchor_fp_angle

            # go through all footprints
            src_footprints = self.src_footprints
            dst_footprints = self.get_footprints_on_sheet(sheet)

            nr_footprints = len(src_footprints)
            for fp_index in range(nr_footprints):
                src_fp = src_footprints[fp_index]

                progress = progress + (1 / nr_sheets) * (1 / nr_footprints)
                self.update_progress(self.stage, progress, None)

                # find proper match in source footprints
                list_of_possible_dst_footprints = []
                for d_fp in dst_footprints:
                    if d_fp.fp_id == src_fp.fp_id:
                        list_of_possible_dst_footprints.append(d_fp)

                # if there is more than one possible anchor, select the correct one
                if len(list_of_possible_dst_footprints) == 1:
                    dst_fp = list_of_possible_dst_footprints[0]
                else:
                    list_of_matches = []
                    for fp in list_of_possible_dst_footprints:
                        index = list_of_possible_dst_footprints.index(fp)
                        matches = 0
                        for item in src_fp.sheet_id:
                            if item in fp.sheet_id:
                                matches = matches + 1
                        list_of_matches.append((index, matches))
                    # check if list is empty, if it is, then it is highly likely that schematics and pcb are not in sync
                    if not list_of_matches:
                        raise LookupError("Can not find destination footprint for source footprint: " + repr(src_fp.ref)
                                          + "\n" + "Most likely, schematics and PCB are not in sync")
                    # select the one with most matches
                    index, _ = max(list_of_matches, key=lambda item: item[1])
                    dst_fp = list_of_possible_dst_footprints[index]

                # skip locked footprints
                if dst_fp.fp.IsLocked() is True and self.replicate_locked_footprints is False:
                    continue

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
                dst_fp_pos = pcbnew.VECTOR2I(*new_pos)
                # place current footprint - only if current footprint is not also the anchor
                if dst_fp.ref != dst_anchor_fp.ref:
                    dst_fp.fp.SetPosition(dst_fp_pos)

                    if dst_fp.fp.IsFlipped() != src_fp_flipped:
                        dst_fp.fp.Flip(dst_fp.fp.GetPosition(), False)
                    dst_fp.fp.SetOrientationDegrees(new_orientation)

                # Copy local settings.
                dst_fp.fp.SetLocalClearance(src_fp.fp.GetLocalClearance())
                dst_fp.fp.SetLocalSolderMaskMargin(src_fp.fp.GetLocalSolderMaskMargin())
                dst_fp.fp.SetLocalSolderPasteMargin(src_fp.fp.GetLocalSolderPasteMargin())
                dst_fp.fp.SetLocalSolderPasteMarginRatio(src_fp.fp.GetLocalSolderPasteMarginRatio())
                dst_fp.fp.SetZoneConnection(src_fp.fp.GetZoneConnection())

                # add footprints to corresponding layout groups if selected
                # and if footprint is not already member of this group
                if settings.group_footprints and dst_fp.fp.GetParentGroup() != self.dst_groups[st_index].GetName():
                    self.dst_groups[st_index].AddItem(dst_fp.fp)
                    
                # flip if dst anchor is flipped in regard to src anchor
                if self.src_anchor_fp.fp.IsFlipped() != dst_anchor_fp.fp.IsFlipped():
                    # ignore anchor fp
                    if dst_anchor_fp != dst_fp:
                        dst_fp.fp.Flip(dst_anchor_fp_position, False)
                        #
                        src_fp_rel_pos = src_anchor_pos - src_fp_pos
                        delta_angle = dst_anchor_fp_angle + src_anchor_fp_angle
                        dst_fp_rel_pos_rot = rotate_around_center([-src_fp_rel_pos[0], src_fp_rel_pos[1]],
                                                                  -delta_angle)
                        dst_fp_pos = dst_anchor_fp_position + pcbnew.VECTOR2I(dst_fp_rel_pos_rot[0],
                                                                                  dst_fp_rel_pos_rot[1])
                        # also need to change the angle
                        dst_fp.fp.SetPosition(dst_fp_pos)
                        src_fp_flipped_orientation = flipped_angle(src_fp_orientation)
                        flipped_delta = flipped_angle(src_anchor_fp_angle) - dst_anchor_fp_angle
                        new_orientation = src_fp_flipped_orientation - flipped_delta
                        dst_fp.fp.SetOrientationDegrees(new_orientation)

                dst_fp_orientation = dst_fp.fp.GetOrientationDegrees()
                dst_fp_flipped = dst_fp.fp.IsFlipped()

                # replicate also text layout - also for anchor footprint. I am counting that the user is lazy and will
                # just position the destination anchors and will not edit them
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
                src_text: pcbnew.PCB_TEXT
                dst_text: pcbnew.PCB_TEXT
                for src_text in src_fp_text_items:
                    txt_index = src_fp_text_items.index(src_text)
                    src_txt_pos = src_text.GetPosition()
                    src_txt_rel_pos = src_txt_pos - src_fp_pos
                    src_txt_orientation = src_text.GetTextAngleDegrees()
                    delta_angle = dst_fp_orientation - src_fp_orientation
                    dst_text = dst_fp_text_items[txt_index]

                    dst_text.SetLayer(src_text.GetLayer())
                    # set text parameters
                    dst_text.SetAttributes(src_text.GetAttributes())
                    # properly set position
                    if src_fp_flipped != dst_fp_flipped:
                        dst_text.Flip(dst_anchor_fp_position, False)
                        dst_txt_rel_pos = [-src_txt_rel_pos[0], src_txt_rel_pos[1]]
                        delta_angle = flipped_angle(src_anchor_fp_angle) - dst_anchor_fp_angle
                        dst_txt_rel_pos_rot = rotate_around_center(dst_txt_rel_pos, delta_angle)
                        dst_txt_pos = dst_fp_pos + pcbnew.VECTOR2I(dst_txt_rel_pos_rot[0], dst_txt_rel_pos_rot[1])
                        dst_text.SetPosition(dst_txt_pos)
                        dst_text.SetTextAngleDegrees(-src_txt_orientation - anchor_delta_angle)
                        dst_text.SetMirrored(not src_text.IsMirrored())
                    else:
                        dst_txt_rel_pos = rotate_around_center(src_txt_rel_pos, -delta_angle)
                        dst_txt_pos = dst_fp_pos + pcbnew.VECTOR2I(dst_txt_rel_pos[0], dst_txt_rel_pos[1])
                        dst_text.SetPosition(dst_txt_pos)
                        dst_text.SetTextAngleDegrees(src_txt_orientation - anchor_delta_angle)
                        dst_text.SetMirrored(src_text.IsMirrored())

    def replicate_tracks(self, settings):
        logger.info("Replicating tracks")
        nr_sheets = len(self.dst_sheets)
        for st_index in range(nr_sheets):
            sheet = self.dst_sheets[st_index]
            progress = st_index / nr_sheets
            self.update_progress(self.stage, progress, None)
            logger.info("Replicating tracks on sheet " + repr(sheet))

            # get anchor footprint
            dst_anchor_fp = self.get_sheet_anchor_footprint(sheet)

            # get source group from source footprint
            source_group = self.src_anchor_fp.fp.GetParentGroup()

            dst_anchor_fp_angle = dst_anchor_fp.fp.GetOrientation().AsDegrees()
            dst_anchor_fp_position = dst_anchor_fp.fp.GetPosition()

            src_anchor_fp_angle = self.src_anchor_fp.fp.GetOrientation().AsDegrees()
            src_anchor_fp_position = self.src_anchor_fp.fp.GetPosition()

            move_vector = dst_anchor_fp_position - src_anchor_fp_position
            delta_orientation = dst_anchor_fp_angle - src_anchor_fp_angle

            net_pairs = self.get_net_pairs(sheet)

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
                    to_net_code = self.netdict.GetNetItem(to_net_name).GetNetCode()
                    #to_net_item = self.netdict.GetNetItem(to_net_name)

                    # make a duplicate, move it, rotate it, select proper net and add it to the board
                    new_track = track.Duplicate().Cast()
                    new_track.SetNetCode(to_net_code)
                    #new_track.SetNet(to_net_item)
                    new_track.Move(move_vector)
                    if self.src_anchor_fp.fp.IsFlipped() != dst_anchor_fp.fp.IsFlipped():
                        new_track.Flip(dst_anchor_fp_position, False)
                        delta_angle = flipped_angle(src_anchor_fp_angle) - dst_anchor_fp_angle
                        rot_angle = delta_angle - 180
                        new_track.Rotate(dst_anchor_fp_position, pcbnew.EDA_ANGLE(-rot_angle, pcbnew.DEGREES_T))
                    else:
                        new_track.Rotate(dst_anchor_fp_position, pcbnew.EDA_ANGLE(delta_orientation, pcbnew.DEGREES_T))

                    # prevent tracks from being added into source group
                    if source_group is not None:
                        source_group.RemoveItem(new_track)                    

                    # add tracks to corresponding layout groups if selected
                    if settings.group_tracks:
                        self.dst_groups[st_index].AddItem(new_track)

                    self.board.Add(new_track)

    def replicate_zones(self, settings):
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
            dst_anchor_fp_angle = dst_anchor_fp.fp.GetOrientation().AsDegrees()
            dst_anchor_fp_position = dst_anchor_fp.fp.GetPosition()

            # get source group from source footprint
            source_group = self.src_anchor_fp.fp.GetParentGroup()

            src_anchor_fp_angle = self.src_anchor_fp.fp.GetOrientation().AsDegrees()
            src_anchor_fp_position = self.src_anchor_fp.fp.GetPosition()

            move_vector = dst_anchor_fp_position - src_anchor_fp_position
            delta_orientation = dst_anchor_fp_angle - src_anchor_fp_angle

            net_pairs = self.get_net_pairs(sheet)
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
                        # With proper layout I don't see why this should happen
                        # TODO find a case when this happens in order to log it with proper message
                        if len(tup) == 0:
                            logger.info("When replicating zone from source net " + repr(from_net_name) +
                                        " we did not find matching destination net")
                            tup = [('', '')]
                    # if source zone does not have a netname defined then destination zone also does not need it
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
                    to_net_code = self.netdict.GetNetItem(to_net_name).GetNetCode()
                    #to_net_item = self.netdict.GetNetItem(to_net_name)

                # make a duplicate, move it, rotate it, select proper net and add it to the board
                new_zone = zone.Duplicate().Cast()
                new_zone.Move(move_vector)
                new_zone.SetNetCode(to_net_code)
                #new_zone.SetNet(to_net_item)
                if self.src_anchor_fp.fp.IsFlipped() != dst_anchor_fp.fp.IsFlipped():
                    new_zone.Flip(dst_anchor_fp_position, False)
                    delta_angle = flipped_angle(src_anchor_fp_angle) - dst_anchor_fp_angle
                    rot_angle = delta_angle - 180
                    new_zone.Rotate(dst_anchor_fp_position, pcbnew.EDA_ANGLE(-rot_angle, pcbnew.DEGREES_T))
                else:
                    new_zone.Rotate(dst_anchor_fp_position, pcbnew.EDA_ANGLE(delta_orientation, pcbnew.DEGREES_T))

                # prevent zones from being added into source group
                if source_group is not None:
                        source_group.RemoveItem(new_zone)

                # add zones to corresponding layout groups if selected
                if settings.group_zones:
                    self.dst_groups[st_index].AddItem(new_zone)

                self.board.Add(new_zone)

    def replicate_text(self, settings):
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
            dst_anchor_fp_position = dst_anchor_fp.fp.GetPosition()
            dst_anchor_fp_angle = dst_anchor_fp.fp.GetOrientation().AsDegrees()

            # get source group from source footprint
            source_group = self.src_anchor_fp.fp.GetParentGroup()

            src_anchor_fp_angle = self.src_anchor_fp.fp.GetOrientation().AsDegrees()
            src_anchor_fp_position = self.src_anchor_fp.fp.GetPosition()

            move_vector = dst_anchor_fp_position - src_anchor_fp_position
            delta_orientation = dst_anchor_fp_angle - src_anchor_fp_angle

            nr_text = len(self.src_text)
            for text_index in range(nr_text):
                text = self.src_text[text_index]

                progress = progress + (1 / nr_sheets) * (1 / nr_text)
                self.update_progress(self.stage, progress, None)

                new_text = text.Duplicate().Cast()
                new_text.Move(move_vector)
                if self.src_anchor_fp.fp.IsFlipped() != dst_anchor_fp.fp.IsFlipped():
                    new_text.Flip(dst_anchor_fp_position, False)
                    delta_angle = flipped_angle(src_anchor_fp_angle) - dst_anchor_fp_angle
                    rot_angle = delta_angle - 180
                    new_text.Rotate(dst_anchor_fp_position, pcbnew.EDA_ANGLE(-rot_angle, pcbnew.DEGREES_T))
                else:
                    new_text.Rotate(dst_anchor_fp_position, pcbnew.EDA_ANGLE(delta_orientation, pcbnew.DEGREES_T))

                # prevent text from being added into source group
                if source_group is not None:
                        source_group.RemoveItem(new_text)

                # add text to corresponding layout groups if selected
                if settings.group_text:
                    self.dst_groups[st_index].AddItem(new_text)

                self.board.Add(new_text)

    def replicate_drawings(self, settings):
        logger.info("Replicating drawings")
        nr_sheets = len(self.dst_sheets)
        for st_index in range(nr_sheets):
            sheet = self.dst_sheets[st_index]
            progress = st_index / nr_sheets
            self.update_progress(self.stage, progress, None)
            logger.info("Replicating drawings on sheet " + repr(sheet))

            # get anchor footprint
            dst_anchor_fp = self.get_sheet_anchor_footprint(sheet)
            dst_anchor_fp_position = dst_anchor_fp.fp.GetPosition()
            dst_anchor_fp_angle = dst_anchor_fp.fp.GetOrientation().AsDegrees()

            # get source group from source footprint
            source_group = self.src_anchor_fp.fp.GetParentGroup()

            src_anchor_fp_angle = self.src_anchor_fp.fp.GetOrientation().AsDegrees()
            src_anchor_fp_position = self.src_anchor_fp.fp.GetPosition()

            move_vector = dst_anchor_fp_position - src_anchor_fp_position
            delta_orientation = dst_anchor_fp_angle - src_anchor_fp_angle

            # go through all the drawings
            nr_drawings = len(self.src_drawings)
            for dw_index in range(nr_drawings):
                drawing = self.src_drawings[dw_index]
                progress = progress + (1 / nr_sheets) * (1 / nr_drawings)
                self.update_progress(self.stage, progress, None)

                new_drawing = drawing.Duplicate().Cast()
                new_drawing.Move(move_vector)

                if self.src_anchor_fp.fp.IsFlipped() != dst_anchor_fp.fp.IsFlipped():

                    new_drawing.Flip(dst_anchor_fp_position, False)
                    delta_angle = flipped_angle(src_anchor_fp_angle) - dst_anchor_fp_angle
                    rot_angle = delta_angle - 180
                    new_drawing.Rotate(dst_anchor_fp_position, pcbnew.EDA_ANGLE(-rot_angle, pcbnew.DEGREES_T))
                else:
                    new_drawing.Rotate(dst_anchor_fp_position, pcbnew.EDA_ANGLE(delta_orientation, pcbnew.DEGREES_T))

                # prevent drawings from being added into source group
                if source_group is not None:
                        source_group.RemoveItem(new_drawing)
                # add drawings to corresponding layout groups if selected
                if settings.group_drawings:
                    self.dst_groups[st_index].AddItem(new_drawing)

                self.board.Add(new_drawing)

    def remove_zones_tracks(self, intersecting):
        for index in range(len(self.dst_sheets)):
            sheet = self.dst_sheets[index]
            self.update_progress(self.stage, index / len(self.dst_sheets), None)
            # get footprints on a sheet
            fp_sheet = self.get_footprints_on_sheet(sheet)
            # get bounding box
            bounding_box = self.get_footprints_bounding_box(fp_sheet)
            logger.info(f"Remove bounding box top:{bounding_box.GetTop()}, bottom:{bounding_box.GetBottom()}, "
                        f"Left:{bounding_box.GetLeft()}, Right:{bounding_box.GetRight()}")
            # remove only tracks which are within the bounding box
            # or they are connected to a net that is completely local to the sheet
            nets_on_sheet = self.get_nets_from_footprints(fp_sheet)
            fp_not_on_sheet = self.get_footprints_not_on_sheet(sheet)
            other_nets = self.get_nets_from_footprints(fp_not_on_sheet)
            nets_exclusively_on_sheet = [net for net in nets_on_sheet if net not in other_nets]

            # remove items
            # TODO refactor out the old selection code
            tracks_for_removal = self.get_tracks(bounding_box, not intersecting, nets_exclusively_on_sheet)
            for track in tracks_for_removal:
                # minus the tracks in source bounding box
                if track not in self.src_tracks:
                    self.board.RemoveNative(track)
            zones_for_removal = self.get_zones(bounding_box, not intersecting, nets_exclusively_on_sheet)
            for zone in zones_for_removal:
                # minus the zones in source bounding box
                if zone not in self.src_zones:
                    self.board.RemoveNative(zone)
            for text_item in self.get_text_items(bounding_box, not intersecting):
                self.board.RemoveNative(text_item)
            for drawing in self.get_drawings(bounding_box, not intersecting):
                self.board.RemoveNative(drawing)

    def removing_duplicates(self):
        remove_duplicates(self.board)

    def get_footprints_for_replication(self, level, bounding_box, settings):
        src_fps = self.get_footprints_on_sheet(level)
        fps_for_replication = []
        for fp in src_fps:
            if not fp.fp.IsLocked() or settings.rep_locked_drawings:
                if settings.group_only:
                    if fp.fp.GetParentGroup():
                        if fp.fp.GetParentGroup().GetName() == self.src_anchor_fp_group:
                            fps_for_replication.append(fp)
                else:
                    fps_for_replication.append(fp)
        return fps_for_replication

    def get_tracks_for_replication(self, level, bounding_box, settings):
        tracks_for_replication = []
        # get all tracks
        all_tracks = self.board.GetTracks()

        src_fps = self.get_footprints_on_sheet(level)
        nets_on_sheet = self.get_nets_from_footprints(src_fps)
        fp_not_on_sheet = self.get_footprints_not_on_sheet(level)
        other_nets = self.get_nets_from_footprints(fp_not_on_sheet)
        nets_exclusively_on_sheet = [net for net in nets_on_sheet if net not in other_nets]
        common_nets_on_sheet = [net for net in nets_on_sheet if net not in nets_exclusively_on_sheet]

        logger.info(f"Filtering list of tracks")
        if settings.group_only:
            # get all tracks that are in the group and on sheet nets (including common)
            for t in all_tracks:
                if not t.IsLocked() or settings.rep_locked_tracks:
                    if t.GetParentGroup():
                        logger.info(f"Track group: {t.GetParentGroup().GetName()}, src group:{self.src_anchor_fp_group}")
                        if t.GetParentGroup().GetName() == self.src_anchor_fp_group:
                            if t.GetNetname() in nets_on_sheet:
                                tracks_for_replication.append(t)
        else:
            for t in all_tracks:
                if not t.IsLocked() or settings.rep_locked_tracks:
                    t_bb = t.GetBoundingBox()
                    if (settings.intersecting and bounding_box.Intersects(t_bb)) or \
                            (not settings.intersecting and bounding_box.Contains(t_bb)):
                        # append those tracks which are inside bounding box and on sheet nets (including common)
                        if t.GetNetname() in nets_on_sheet:
                            tracks_for_replication.append(t)
                    # outside tracks
                    else:
                        # append those which are on sheet exclusive nets
                        if t.GetNetname() in nets_exclusively_on_sheet:
                            tracks_for_replication.append(t)
                        # those which are on other nets, append only if they are in group and if the user wants to
                        else:
                            if settings.group_items and t.GetNetname() in nets_on_sheet:
                                if t.GetParentGroup():
                                    if self.src_anchor_fp_group == t.GetParentGroup().GetName():
                                        tracks_for_replication.append(t)
        return tracks_for_replication

    def get_zones_for_replication(self, level, bounding_box, settings):
        zones_for_replication = []
        # get all zones
        all_zones = []
        for zone_id in range(self.board.GetAreaCount()):
            all_zones.append(self.board.GetArea(zone_id))

        src_fps = self.get_footprints_on_sheet(level)
        nets_on_sheet = self.get_nets_from_footprints(src_fps)
        fp_not_on_sheet = self.get_footprints_not_on_sheet(level)
        other_nets = self.get_nets_from_footprints(fp_not_on_sheet)
        nets_exclusively_on_sheet = [net for net in nets_on_sheet if net not in other_nets]
        common_nets_on_sheet = [net for net in nets_on_sheet if net not in nets_exclusively_on_sheet]

        if settings.group_only:
            # get all zones that are in the group and on sheet nets (including common)
            for z in all_zones:
                if not z.IsLocked() or settings.rep_locked_zones:
                    if z.GetParentGroup():
                        if z.GetParentGroup().GetName() == self.src_anchor_fp_group:
                            if z.GetNetname() in nets_on_sheet:
                                zones_for_replication.append(z)
        else:
            for z in all_zones:
                if not z.IsLocked() or settings.rep_locked_zones:
                    z_bb = z.GetBoundingBox()
                    if (settings.intersecting and bounding_box.Intersects(z_bb)) or \
                            (not settings.intersecting and bounding_box.Contains(z_bb)):
                        # append those zones which are inside bounding box and on sheet nets (including common)
                        if z.GetNetname() in nets_on_sheet or z.GetIsRuleArea():
                            zones_for_replication.append(z)
                    # outside zones
                    else:
                        # append those which are on sheet exclusive nets
                        if z.GetNetname() in nets_exclusively_on_sheet:
                            zones_for_replication.append(z)
                        # those which are on other nets, append only if they are in group and if the user wants to
                        else:
                            if settings.group_items and (z.GetNetname() in nets_on_sheet or z.GetIsRuleArea()):
                                if z.GetParentGroup():
                                    if self.src_anchor_fp_group == z.GetParentGroup().GetName():
                                        zones_for_replication.append(z)
        return zones_for_replication

    def get_text_for_replication(self, bounding_box, settings):
        text_items_for_replication = []
        # get all drawings on PCB
        text_items = []
        for t_i in self.board.GetDrawings():
            if isinstance(t_i, pcbnew.PCB_TEXT):
                # text items are handled separately
                text_items.append(t_i)

        # if group only
        if settings.group_only:
            # get all drawings, and select only those belonging to group
            for t_i in text_items:
                if t_i.GetParentGroup():
                    if self.src_anchor_fp_group == t_i.GetParentGroup().GetName():
                        if not t_i.IsLocked() or settings.rep_locked_text:
                            text_items_for_replication.append(t_i)
        else:
            for t_i in text_items:
                t_i_bb = t_i.GetBoundingBox()
                if settings.intersecting:
                    # append those drawings which are inside bounding box
                    if bounding_box.Intersects(t_i_bb):
                        if not t_i.IsLocked() or settings.rep_locked_text:
                            text_items_for_replication.append(t_i)
                    # append outside drawings append only if required
                    else:
                        if settings.group_items:
                            if t_i.GetParentGroup():
                                if self.src_anchor_fp_group == t_i.GetParentGroup().GetName():
                                    if not t_i.IsLocked() or settings.rep_locked_drawings:
                                        text_items_for_replication.append(t_i)
                else:
                    if bounding_box.Contains(t_i_bb):
                        if not t_i.IsLocked() or settings.rep_locked_drawings:
                            text_items_for_replication.append(t_i)
                    else:
                        if settings.group_items:
                            if t_i.GetParentGroup():
                                if self.src_anchor_fp_group == t_i.GetParentGroup().GetName():
                                    if not t_i.IsLocked() or settings.rep_locked_drawings:
                                        text_items_for_replication.append(t_i)
        return text_items_for_replication

    def get_drawings_for_replication(self, level, bounding_box, settings):
        drawings_for_replication = []
        # get all drawings on PCB
        drawings = []
        for d in self.board.GetDrawings():
            if not isinstance(d, pcbnew.PCB_TEXT):
                # text items are handled separately
                drawings.append(d)

        src_fps = self.get_footprints_on_sheet(level)
        nets_on_sheet = self.get_nets_from_footprints(src_fps)
        fp_not_on_sheet = self.get_footprints_not_on_sheet(level)
        other_nets = self.get_nets_from_footprints(fp_not_on_sheet)
        nets_exclusively_on_sheet = [net for net in nets_on_sheet if net not in other_nets]

        # if group only
        if settings.group_only:
            # get all drawings, and select only those belonging to group
            for d in drawings:
                if d.GetParentGroup():
                    if self.src_anchor_fp_group == d.GetParentGroup().GetName():
                        if not d.IsLocked() or settings.rep_locked_drawings:
                            drawings_for_replication.append(d)
        else:
            for d in drawings:
                d_bb = d.GetBoundingBox()
                if settings.intersecting:
                    # append those drawings which are inside bounding box
                    if bounding_box.Intersects(d_bb):
                        if not d.IsLocked() or settings.rep_locked_drawings:
                            drawings_for_replication.append(d)
                    # append outside drawings append only if required
                    else:
                        # either drawing is in the group
                        if settings.group_items:
                            if d.GetParentGroup():
                                if self.src_anchor_fp_group == d.GetParentGroup().GetName():
                                    if not d.IsLocked() or settings.rep_locked_drawings:
                                        drawings_for_replication.append(d)
                        # or it might be connected to internal net
                        if d.IsConnected():
                            if d.GetNetname() in nets_exclusively_on_sheet:
                                drawings_for_replication.append(d)
                else:
                    if bounding_box.Contains(d_bb):
                        if not d.IsLocked() or settings.rep_locked_drawings:
                            drawings_for_replication.append(d)
                    else:
                        if settings.group_items:
                            if d.GetParentGroup():
                                if self.src_anchor_fp_group == d.GetParentGroup().GetName():
                                    if not d.IsLocked() or settings.rep_locked_drawings:
                                        drawings_for_replication.append(d)
        return drawings_for_replication

    def highlight_set_level(self, level, settings):
        logger.info(f"Level selected: {repr(level)}")
        # find level bounding box
        src_fps = self.get_footprints_on_sheet(level)
        fps_bb = self.get_footprints_bounding_box(src_fps)

        # set highlight on all the footprints
        fps = self.get_footprints_for_replication(level, fps_bb, settings)
        for fp in fps:
            self.fp_set_highlight(fp.fp)

        # set highlight on other items
        highlighted_items = []
        if settings.rep_tracks:
            tracks = self.get_tracks_for_replication(level, fps_bb, settings)
            for t in tracks:
                t.SetBrightened()
                highlighted_items.append(t)

        if settings.rep_zones:
            zones = self.get_zones_for_replication(level, fps_bb, settings)
            for z in zones:
                z.SetBrightened()
                highlighted_items.append(z)

        if settings.rep_text:
            text_items = self.get_text_for_replication(fps_bb, settings)
            for t in text_items:
                t.SetBrightened()
                highlighted_items.append(t)

        if settings.rep_drawings:
            drawings = self.get_drawings_for_replication(level, fps_bb, settings)
            for d in drawings:
                d.SetBrightened()
                highlighted_items.append(d)

        return fps, highlighted_items

    def highlight_clear_level(self, fps, items):
        # set highlight on all the footprints
        for fp in fps:
            self.fp_clear_highlight(fp.fp)

        # set highlight on other items
        for item in items:
            item.ClearBrightened()

    @staticmethod
    def fp_set_highlight(fp):
        pads_list = fp.Pads()
        for pad in pads_list:
            pad.SetBrightened()
        drawings = fp.GraphicalItems()
        for item in drawings:
            item.SetBrightened()

    @staticmethod
    def fp_clear_highlight(fp):
        pads_list = fp.Pads()
        for pad in pads_list:
            pad.ClearBrightened()
        drawings = fp.GraphicalItems()
        for item in drawings:
            item.ClearBrightened()
