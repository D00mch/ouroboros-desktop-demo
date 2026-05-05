"""Compatibility package for generated Dialogs protobuf imports.

The Dialogs schema imports `scalapb/scalapb.proto`, which pulls in a Python
module named `scalapb`. The repository vendors generated stubs for this plan
without shipping the external `scalapb` package, so this shim keeps imports
working in local/test environments.
"""
