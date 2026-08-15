"""pytest 公共 fixtures"""
import sys
import os
import pytest

# 确保 backend 目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
