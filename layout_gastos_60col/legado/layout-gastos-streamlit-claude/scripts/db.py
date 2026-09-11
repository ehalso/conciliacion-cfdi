"""Conexion compartida a TRIVASADB3 (base viva). Ver decisions/2026-07-conexion-trivasadb3-vs-trivasadb.md"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from connection_200_trivasadb3 import q, engine  # noqa: E402,F401
