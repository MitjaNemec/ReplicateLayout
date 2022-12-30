# -*- coding: utf-8 -*-

###########################################################################
## Python code generated with wxFormBuilder (version 3.10.1-0-g8feb16b)
## http://www.wxformbuilder.org/
##
## PLEASE DO *NOT* EDIT THIS FILE!
###########################################################################

import wx
import wx.xrc
import wx.adv

###########################################################################
## Class ErrorDialogGUI
###########################################################################

class ErrorDialogGUI ( wx.Dialog ):

    def __init__( self, parent ):
        wx.Dialog.__init__ ( self, parent, id = wx.ID_ANY, title = u"Replicate Layout", pos = wx.DefaultPosition, size = wx.Size( 458,212 ), style = wx.DEFAULT_DIALOG_STYLE )

        self.SetSizeHints( wx.DefaultSize, wx.DefaultSize )

        bSizer1 = wx.BoxSizer( wx.VERTICAL )

        self.m_staticText1 = wx.StaticText( self, wx.ID_ANY, u"Fatal error when restoring layout. You can raise an issue on GiHub page.                    + \"Please attach the save_restore_layout.log which you should find in the project folder.", wx.DefaultPosition, wx.DefaultSize, 0 )
        self.m_staticText1.Wrap( -1 )

        bSizer1.Add( self.m_staticText1, 0, wx.ALL, 5 )

        self.m_staticText3 = wx.StaticText( self, wx.ID_ANY, u"You can raise an issue on GiHub page.", wx.DefaultPosition, wx.DefaultSize, 0 )
        self.m_staticText3.Wrap( -1 )

        bSizer1.Add( self.m_staticText3, 0, wx.ALL, 5 )

        self.m_hyperlink1 = wx.adv.HyperlinkCtrl( self, wx.ID_ANY, u"https://github.com/MitjaNemec/ReplicateLayout", u"https://github.com/MitjaNemec/ReplicateLayout", wx.DefaultPosition, wx.DefaultSize, wx.adv.HL_DEFAULT_STYLE )
        bSizer1.Add( self.m_hyperlink1, 0, wx.ALL, 5 )

        self.m_staticText4 = wx.StaticText( self, wx.ID_ANY, u"Please attach the save_restore_layout.log which you should find in the project folder.", wx.DefaultPosition, wx.DefaultSize, 0 )
        self.m_staticText4.Wrap( -1 )

        self.m_staticText4.SetMinSize( wx.Size( -1,40 ) )

        bSizer1.Add( self.m_staticText4, 0, wx.ALL, 5 )

        bSizer3 = wx.BoxSizer( wx.HORIZONTAL )


        bSizer3.Add( ( 0, 0), 1, wx.EXPAND, 5 )

        self.btn_ok = wx.Button( self, wx.ID_OK, u"Ok", wx.DefaultPosition, wx.DefaultSize, 0 )
        bSizer3.Add( self.btn_ok, 0, wx.ALL, 5 )


        bSizer3.Add( ( 0, 0), 1, wx.EXPAND, 5 )


        bSizer1.Add( bSizer3, 1, wx.EXPAND, 5 )


        self.SetSizer( bSizer1 )
        self.Layout()

        self.Centre( wx.BOTH )

    def __del__( self ):
        pass


