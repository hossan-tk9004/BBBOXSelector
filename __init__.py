# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, generators, print_function, unicode_literals
import sys
from importlib import reload
sys.dont_write_bytecode = True

def addGUI():
    from . import BBBoxSelector
    reload(BBBoxSelector)
    
    tool = BBBoxSelector.BBBoxSelectorGUI()
    tool.show()