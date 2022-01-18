# -*- coding: utf-8 -*-
#  action_replicate_layout.py
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
#
import wx
import pcbnew
import os
import logging
import sys
from .replicate_layout_GUI import ReplicateLayoutGUI
from .replicate_layout import Replicator


def fp_set_highlight(fp):
    pads_list = fp.Pads()
    for pad in pads_list:
        pad.SetBrightened()
    drawings = fp.GraphicalItems()
    for item in drawings:
        item.SetBrightened()


def fp_clear_highlight(fp):
    pads_list = fp.Pads()
    for pad in pads_list:
        pad.ClearBrightened()
    drawings = fp.GraphicalItems()
    for item in drawings:
        item.ClearBrightened()


class ReplicateLayoutDialog(ReplicateLayoutGUI):
    def SetSizeHints(self, sz1, sz2):
        # DO NOTHING
        pass

    def __init__(self, parent, placer, ref_fp, user_units):
        super(ReplicateLayoutDialog, self).__init__(parent)
        pass

    def level_changed(self, event):
        pass
        event.Skip()

    def on_ok(self, event):
        pass
        event.Skip()

    def on_cancel(self, event):
        pass
        event.Skip()

    def update_progress(self):
        pass


class ReplicateLayout(pcbnew.ActionPlugin):
    def __init__(self):
        super(ReplicateLayout, self).__init__()

        self.frame = None

        self.name = "Replicate layout"
        self.category = "Replicate layout"
        self.description = "Replicates layout of one hierarchical sheet to other copies of the same sheet."
        self.icon_file_name = os.path.join(
            os.path.dirname(__file__), 'replicate_layout_light.png')
        self.dark_icon_file_name = os.path.join(
            os.path.dirname(__file__), 'replicate_layout_dark.png')

        self.debug_level = logging.INFO

        # plugin paths
        self.plugin_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)))
        self.version_file_path = os.path.join(self.plugin_folder, 'version.txt')

        # load the plugin version
        with open(self.version_file_path) as fp:
            self.version = fp.readline()

    def defaults(self):
        pass

    def Run(self):
        # grab PCB editor frame
        self.frame = wx.GetTopLevelParent(wx.GetActiveWindow())

        # load board
        board = pcbnew.GetBoard()
        pass

        # go to the project folder - so that log will be in proper place
        os.chdir(os.path.dirname(os.path.abspath(board.GetFileName())))

        # Remove all handlers associated with the root logger object.
        for handler in logging.root.handlers[:]:
            logging.root.removeHandler(handler)

        file_handler = logging.FileHandler(filename='replicate_layout.log', mode='w')
        handlers = [file_handler]

        # set up logger
        logging.basicConfig(level=logging.INFO,
                            format='%(asctime)s %(name)s %(lineno)d:%(message)s',
                            datefmt='%m-%d %H:%M:%S',
                            handlers=handlers)
        logger = logging.getLogger(__name__)
        logger.info("Plugin executed on: " + repr(sys.platform))
        logger.info("Plugin executed with python version: " + repr(sys.version))
        logger.info("KiCad build version: " + str(pcbnew.GetBuildVersion()))
        logger.info("Plugin version: " + self.version)
        logger.info("Frame repr: " + repr(self.frame))

        # check if there is exactly one footprints selected
        selected_footprints = [x.GetReference() for x in board.GetFootprints() if x.IsSelected()]

        # if more or less than one show only a message box
        if len(selected_footprints) != 1:
            caption = 'Place footprints'
            message = "More or less than 1 footprint selected. Please select exactly one footprint " \
                      "and run the script again"
            dlg = wx.MessageDialog(self.frame, message, caption, wx.OK | wx.ICON_INFORMATION)
            dlg.ShowModal()
            dlg.Destroy()
            return

        # this is the source anchor footprint reference
        src_anchor_fp_reference = selected_footprints[0]

        # prepare the replicator
        logger.info("Preparing replicator with " + src_anchor_fp_reference + " as a reference")

        try:
            replicator = Replicator(board)
        except LookupError as exception:
            caption = 'Replicate Layout'
            logger.exception("Fatal error when making an instance of replicator")
            message = str(exception)
            dlg = wx.MessageDialog(self.frame, message, caption, wx.OK | wx.ICON_ERROR)
            dlg.ShowModal()
            dlg.Destroy()
            logging.shutdown()
            return
        except Exception:
            logger.exception("Fatal error when making an instance of replicator")
            caption = 'Replicate Layout'
            message = "Fatal error when making an instance of replicator.\n" \
                      + "You can raise an issue on GiHub page.\n" \
                      + "Please attach the replicate_layout.log which you should find in the project folder."
            dlg = wx.MessageDialog(self.frame, message, caption, wx.OK | wx.ICON_ERROR)
            dlg.ShowModal()
            dlg.Destroy()
            logging.shutdown()
            return

        src_anchor_fp = replicator.get_fp_by_ref(src_anchor_fp_reference)

        logger.info(f'source anchor footprint is {repr(src_anchor_fp.ref)}\n'
                    f'Located on: {repr(src_anchor_fp.sheet_id)}\n'
                    f'With filenames: {repr(src_anchor_fp.filename)}\n'
                    f'With sheet_id:{repr(src_anchor_fp.sheet_id)}')

        list_of_footprints = replicator.get_list_of_footprints_with_same_id(src_anchor_fp.fp_id)
        nice_list = [(x.ref, x.sheet_id) for x in list_of_footprints]
        logger.info(f'Corresponding footprints are \n{repr(nice_list)}')

        if not list_of_footprints:
            caption = 'Replicate Layout'
            message = "Selected footprint is unique in the pcb (only one footprint with this ID)"
            dlg = wx.MessageDialog(self.frame, message, caption, wx.OK | wx.ICON_ERROR)
            dlg.ShowModal()
            dlg.Destroy()
            logging.shutdown()
            return

        # show dialog
        logger.info("Showing dialog")
        dlg = ReplicateLayoutDialog(self.frame, replicator, src_anchor_fp_reference, logger)

        # find pcbnew position
        pcbnew_pos = self.frame.GetScreenPosition()
        logger.info("Pcbnew position: " + repr(pcbnew_pos))

        # find all the display sizes
        display = list()
        for n in range(wx.Display.GetCount()):
            display.append(wx.Display(n).GetGeometry())
            logger.info("Display " + repr(n) + ": " + repr(wx.Display(n).GetGeometry()))

        # find position of right toolbar
        toolbar_pos = self.frame.FindWindowById(pcbnew.ID_V_TOOLBAR).GetScreenPosition()
        logger.info("Toolbar position: " + repr(toolbar_pos))

        # find site of dialog
        size = dlg.GetSize()
        # calculate the position
        dialog_position = wx.Point(toolbar_pos[0] - size[0], toolbar_pos[1])
        logger.info("Dialog position: " + repr(dialog_position))
        dlg.SetPosition(dialog_position)

        dlg.ShowModal()

        # clear highlight on all modules on selected level
        for fp in dlg.src_footprints:
            fp_clear_highlight(fp)
        pcbnew.Refresh()
