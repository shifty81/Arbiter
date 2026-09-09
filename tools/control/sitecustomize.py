"""Compatibility hook for older PCC embedded-console builds.

PCC-GUI 0.7 no longer suppresses consoles by giving every child CREATE_NO_WINDOW.
That approach could leave native grandchildren without an inherited console, allowing them
to allocate transient windows. The current process host launches one hidden console provider
and lets its descendants inherit that invisible console instead.

This module intentionally performs no monkey-patching. It remains present so older PYTHONPATH
layouts do not fail during a rolling manual overwrite.
"""
