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
import time
from .replicate_layout_GUI import ReplicateLayoutGUI
from .error_dialog_GUI import ErrorDialogGUI
from .replicate_layout import Replicator
from .replicate_layout import Settings
from .conn_issue_GUI import ConnIssueGUI


class ConnIssueDialog(ConnIssueGUI):
    def SetSizeHints(self, sz1, sz2):
        # DO NOTHING
        pass

    def __init__(self, parent, replicator):
        super(ConnIssueDialog, self).__init__(parent)

        self.list.InsertColumn(0, 'Footprint', width=100)
        self.list.InsertColumn(1, 'Pad', width=100)

        index = 0
        for issue in replicator.connectivity_issues:
            self.list.InsertItem(index, issue[0])
            self.list.SetItem(index, 1, issue[1])
            index = index + 1


class ErrorDialog(ErrorDialogGUI):
    def SetSizeHints(self, sz1, sz2):
        # DO NOTHING
        pass

    def __init__(self, parent):
        super(ErrorDialog, self).__init__(parent)


class ReplicateLayoutDialog(ReplicateLayoutGUI):
    def SetSizeHints(self, sz1, sz2):
        # DO NOTHING
        pass

    def __init__(self, parent, replicator, fp_ref, logger):
        super(ReplicateLayoutDialog, self).__init__(parent)

        self.logger = logger

        self.replicator = replicator
        self.src_anchor_fp = self.replicator.get_fp_by_ref(fp_ref)
        self.levels = self.src_anchor_fp.filename

        # clear levels
        self.list_levels.Clear()
        self.list_levels.AppendItems(self.levels)

        self.sheet_selection = None

        self.src_footprints = []
        self.hl_fps = []
        self.hl_items = []

        # select the bottom most level
        nr_levels = self.list_levels.GetCount()
        self.list_levels.SetSelection(nr_levels - 1)
        self.level_changed(None)

    def __del__(self):
        self.replicator.highlight_clear_level(self.hl_fps, self.hl_items)

    def group_layout_changed( self, event ):
        # when enabled, they should be checked by default
        if self.chkbox_group_layouts.GetValue():
            self.chkbox_group_footprints.Enable(True)
            self.chkbox_group_footprints.SetValue(True)
            self.chkbox_group_tracks.Enable(True)
            self.chkbox_group_tracks.SetValue(True)
            self.chkbox_group_zones.Enable(True)
            self.chkbox_group_zones.SetValue(True)
            self.chkbox_group_text.Enable(True)
            self.chkbox_group_text.SetValue(True)
            self.chkbox_group_drawings.Enable(True)
            self.chkbox_group_drawings.SetValue(True)
        else:
            self.chkbox_group_footprints.Disable()
            self.chkbox_group_footprints.SetValue(False)
            self.chkbox_group_tracks.Disable()
            self.chkbox_group_tracks.SetValue(False)
            self.chkbox_group_zones.Disable()
            self.chkbox_group_zones.SetValue(False)
            self.chkbox_group_text.Disable()
            self.chkbox_group_text.SetValue(False)
            self.chkbox_group_drawings.Disable()
            self.chkbox_group_drawings.SetValue(False)
        if event is not None:
            event.Skip()

    def level_changed(self, event):
        index = self.list_levels.GetSelection()
        list_sheets_choices = self.replicator.get_sheets_to_replicate(self.src_anchor_fp,
                                                                      self.src_anchor_fp.sheet_id[index])

        # show/hide checkbox
        if self.chkbox_group.GetValue():
            self.chkbox_include_group_items.Disable()
            self.chkbox_include_group_items.SetValue(False)
            self.chkbox_intersecting.Disable()
        else:
            self.chkbox_include_group_items.Enable(True)
            self.chkbox_intersecting.Enable(True)
            if self.chkbox_intersecting.GetValue():
                self.chkbox_include_group_items.Enable(True)
            else:
                self.chkbox_include_group_items.Disable()
                self.chkbox_include_group_items.SetValue(False)

        # clear highlight on all footprints on selected level
        self.replicator.highlight_clear_level(self.hl_fps, self.hl_items)
        self.hl_fps = []
        self.hl_items = []
        pcbnew.Refresh()

        # get anchor footprints
        anchor_footprints = self.replicator.get_list_of_footprints_with_same_id(self.src_anchor_fp.fp_id)
        # find matching anchors to matching sheets
        ref_list = []
        for sheet in list_sheets_choices:
            for pf in anchor_footprints:
                if "/".join(sheet) in "/".join(pf.sheet_id):
                    ref_list.append(pf.ref)
                    break

        sheets_for_list = ['/'.join(x[0]) + " (" + x[1] + ")" for x in zip(list_sheets_choices, ref_list)]
        # clear levels
        self.sheet_selection = self.list_sheets.GetSelections()

        self.list_sheets.Clear()
        self.list_sheets.AppendItems(sheets_for_list)

        # if none is selected, select all
        if len(self.sheet_selection) == 0:
            number_of_items = self.list_sheets.GetCount()
            for i in range(number_of_items):
                self.list_sheets.Select(i)
        else:
            for n in range(len(sheets_for_list)):
                if n in self.sheet_selection:
                    self.list_sheets.Select(n)
                else:
                    self.list_sheets.Deselect(n)

        # parse the settings
        settings = Settings(rep_tracks=self.chkbox_tracks.GetValue(), rep_zones=self.chkbox_zones.GetValue(),
                            rep_text=self.chkbox_text.GetValue(), rep_drawings=self.chkbox_drawings.GetValue(),
                            group_layouts=self.chkbox_group_layouts.GetValue(), group_footprints=self.chkbox_group_footprints.GetValue(),
                            group_tracks=self.chkbox_group_tracks.GetValue(), group_zones=self.chkbox_group_zones.GetValue(),
                            group_text=self.chkbox_group_text.GetValue(), group_drawings=self.chkbox_group_drawings.GetValue(),
                            rep_locked_tracks=self.chkbox_locked_tracks.GetValue(), rep_locked_zones=self.chkbox_locked_zones.GetValue(),
                            rep_locked_text=self.chkbox_locked_text.GetValue(), rep_locked_drawings=self.chkbox_locked_drawings.GetValue(),
                            intersecting=self.chkbox_intersecting.GetValue(), group_items=self.chkbox_include_group_items.GetValue(),
                            group_only=self.chkbox_group.GetValue(), locked_fps=self.chkbox_locked.GetValue(),
                            remove=self.chkbox_remove.GetValue())

        # highlight all footprints on selected level
        (self.hl_fps, self.hl_items) = self.replicator.highlight_set_level(self.src_anchor_fp.sheet_id[0:self.list_levels.GetSelection() + 1],
                                                                           settings)
        pcbnew.Refresh()

        if event is not None:
            event.Skip()

    def on_ok(self, event):
        # clear highlight on all footprints on selected level
        # so that duplicated tracks don't remain selected
        self.replicator.highlight_clear_level(self.hl_fps, self.hl_items)
        self.hl_fps = []
        self.hl_items = []

        selected_items = self.list_sheets.GetSelections()
        selected_names = []
        for item in selected_items:
            selected_names.append(self.list_sheets.GetString(item))

        # grab checkboxes
        remove_existing_nets_zones = self.chkbox_remove.GetValue()
        remove_duplicates = self.chkbox_remove_duplicates.GetValue()
        rep_locked = self.chkbox_locked.GetValue()
        group_only = self.chkbox_group.GetValue()

        # parse the settings
        settings = Settings(rep_tracks=self.chkbox_tracks.GetValue(), rep_zones=self.chkbox_zones.GetValue(),
                            rep_text=self.chkbox_text.GetValue(), rep_drawings=self.chkbox_drawings.GetValue(),
                            group_layouts=self.chkbox_group_layouts.GetValue(), group_footprints=self.chkbox_group_footprints.GetValue(),
                            group_tracks=self.chkbox_group_tracks.GetValue(), group_zones=self.chkbox_group_zones.GetValue(),
                            group_text=self.chkbox_group_text.GetValue(), group_drawings=self.chkbox_group_drawings.GetValue(),
                            rep_locked_tracks=self.chkbox_locked_tracks.GetValue(), rep_locked_zones=self.chkbox_locked_zones.GetValue(),
                            rep_locked_text=self.chkbox_locked_text.GetValue(), rep_locked_drawings=self.chkbox_locked_drawings.GetValue(),
                            intersecting=self.chkbox_intersecting.GetValue(), group_items=self.chkbox_include_group_items.GetValue(),
                            group_only=self.chkbox_group.GetValue(), locked_fps=self.chkbox_locked.GetValue(),
                            remove=self.chkbox_remove.GetValue())

        # failsafe sometimes on my machine wx does not generate a listbox event
        level = self.list_levels.GetSelection()
        selection_indices = self.list_sheets.GetSelections()
        sheets_on_a_level = self.replicator.get_sheets_to_replicate(self.src_anchor_fp,
                                                                    self.src_anchor_fp.sheet_id[level])
        dst_sheets = [sheets_on_a_level[i] for i in selection_indices]

        # check if all the destination anchor footprints are on the same layer as source anchor footprint
        # first get all the anchor footprints
        all_dst_footprints = []
        for sheet in dst_sheets:
            all_dst_footprints.extend(self.replicator.get_footprints_on_sheet(sheet))
        dst_anchor_footprints = [x for x in all_dst_footprints if x.fp_id == self.src_anchor_fp.fp_id]

        # replicate now
        self.logger.info("Replicating layout")

        self.start_time = time.time()
        self.last_time = self.start_time
        self.progress_dlg = wx.ProgressDialog("Preparing for replication", "Starting plugin", maximum=100)
        self.progress_dlg.Show()
        self.progress_dlg.ToggleWindowStyle(wx.STAY_ON_TOP)
        self.Hide()

        try:
            # update progress dialog
            self.replicator.update_progress = self.update_progress
            self.replicator.replicate_layout(self.src_anchor_fp, self.src_anchor_fp.sheet_id[0:level + 1],
                                             dst_sheets,
                                             settings, remove_duplicates)
                                             
            self.logger.info("Replication complete")

            if self.replicator.connectivity_issues:
                self.logger.info("Letting the user know there are some issues with replicated design")
                report_string = ""
                for item in self.replicator.connectivity_issues:
                    report_string = report_string + f"Footprint {item[0]}, pad {item[1]}\n"
                self.logger.info(f"Looks like the design has an exotic connectivity that the plugin might not"
                                 f" handle properly\n "
                                 f"Make sure that you check the connectivity around:\n" + report_string)
                # show dialog
                issue_dlg = ConnIssueDialog(self, self.replicator)
                issue_dlg.ShowModal()
                issue_dlg.Destroy()

            # clear highlight on all footprints on selected level
            self.replicator.highlight_clear_level(self.hl_fps, self.hl_items)
            self.hl_fps = []
            self.hl_items = []
            pcbnew.Refresh()

            logging.shutdown()
            self.progress_dlg.Destroy()
            event.Skip()
            self.EndModal(True)
        except LookupError as exception:
            # clear highlight on all footprints on selected level
            self.replicator.highlight_clear_level(self.hl_fps, self.hl_items)
            self.hl_fps = []
            self.hl_items = []
            pcbnew.Refresh()

            caption = 'Replicate Layout'
            message = str(exception)
            dlg = wx.MessageDialog(self, message, caption, wx.OK | wx.ICON_ERROR)
            dlg.ShowModal()
            dlg.Destroy()
            logging.shutdown()
            self.progress_dlg.Destroy()
            event.Skip()
            self.EndModal(False)
            return
        except Exception:
            # clear highlight on all footprints on selected level
            self.replicator.highlight_clear_level(self.hl_fps, self.hl_items)
            self.hl_fps = []
            self.hl_items = []
            pcbnew.Refresh()

            self.logger.exception("Fatal error when running Replicate layout plugin")
            e_dlg = ErrorDialog(self)
            e_dlg.ShowModal()
            e_dlg.Destroy()
            logging.shutdown()
            self.progress_dlg.Destroy()
            event.Skip()
            self.Destroy()

    def on_cancel(self, event):
        # clear highlight on all footprints on selected level
        self.replicator.highlight_clear_level(self.hl_fps, self.hl_items)
        self.hl_fps = []
        self.hl_items = []
        pcbnew.Refresh()

        self.logger.info("User canceled the dialog")
        logging.shutdown()
        event.Skip()

        self.Destroy()

    def update_progress(self, stage, percentage, message=None):
        current_time = time.time()
        # update GUI only every 10 ms
        i = int(percentage * 100)
        if message is not None:
            logging.info("updating GUI message: " + repr(message))
            self.progress_dlg.Update(i, message)
        if (current_time - self.last_time) > 0.01:
            self.last_time = current_time
            delta_time = self.last_time - self.start_time
            logging.info("updating GUI with: " + repr(i))
            self.progress_dlg.Update(i)


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
        self.frame = wx.FindWindowByName("PcbFrame")

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
            caption = 'Replicate layout'
            message = "More or less than 1 footprint selected. Please select exactly one footprint " \
                      "and run the script again"
            dlg = wx.MessageDialog(self.frame, message, caption, wx.OK | wx.ICON_INFORMATION)
            dlg.ShowModal()
            dlg.Destroy()
            return

        # this is the source anchor footprint reference
        src_anchor_fp_reference = selected_footprints[0]

        # search for the Replicate.Layout user layer where replication rooms can be defined

        if 'Replicate.Layout' in [board.GetLayerName(x) for x in board.GetEnabledLayers().Users()]:
            pass

        # prepare the replicator
        logger.info("Preparing replicator with " + src_anchor_fp_reference + " as a reference")

        # TODO return if replication is not possible at all
        try:
            replicator = Replicator(board, src_anchor_fp_reference)
        except LookupError as exception:
            logger.exception("Fatal error when making an instance of replicator")
            caption = 'Replicate Layout'
            message = str(exception)
            dlg = wx.MessageDialog(self.frame, message, caption, wx.OK | wx.ICON_ERROR)
            dlg.ShowModal()
            dlg.Destroy()
            logging.shutdown()
            return
        except Exception:
            logger.exception("Fatal error when making an instance of replicator")
            e_dlg = ErrorDialog(self.frame)
            e_dlg.ShowModal()
            e_dlg.Destroy()
            logging.shutdown()
            return

        src_anchor_fp = replicator.get_fp_by_ref(src_anchor_fp_reference)

        # check if source anchor footprint is on root level
        if len(src_anchor_fp.filename) == 0:
            caption = 'Replicate layout'
            message = "Selected anchor footprint is on the root schematic sheet. Replication is not possible."
            dlg = wx.MessageDialog(self.frame, message, caption, wx.OK | wx.ICON_INFORMATION)
            dlg.ShowModal()
            dlg.Destroy()
            return

        # check if there are at least two sheets pointing to same hierarchical file that the source anchor footprint belongs to
        count = 0        
        for filename in replicator.dict_of_sheets.values():           
            # filename contain sheet name and sheet filename, check only sheet filename.
            if filename[1] in src_anchor_fp.filename:
                count = count + 1
        if count < 2:
            caption = 'Replicate layout'
            message = "Selected anchor footprint is on the schematic sheet which does not have multiple instances." \
                      " Replication is not possible."
            dlg = wx.MessageDialog(self.frame, message, caption, wx.OK | wx.ICON_INFORMATION)
            dlg.ShowModal()
            dlg.Destroy()
            return

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
        try:
            dlg = ReplicateLayoutDialog(self.frame, replicator, src_anchor_fp_reference, logger)
            dlg.CenterOnParent()
            # find position of right toolbar
            toolbar_pos = self.frame.FindWindowById(pcbnew.ID_V_TOOLBAR).GetScreenPosition()
            logger.info("Toolbar position: " + repr(toolbar_pos))
            # find site of dialog
            size = dlg.GetSize()
            # place the dialog by the right toolbar
            dialog_position = wx.Point(toolbar_pos[0] - size[0], toolbar_pos[1])
            logger.info("Dialog position: " + repr(dialog_position))
            dlg.SetPosition(dialog_position)
            dlg.Show()
        except Exception:
            logger.exception("Fatal error when making an instance of replicator")
            e_dlg = ErrorDialog(self.frame)
            e_dlg.ShowModal()
            e_dlg.Destroy()
            logging.shutdown()
            return
