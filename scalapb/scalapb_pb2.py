"""Compatibility protobuf module for generated Dialogs bindings.

The Dialogs protobufs import this module because generated descriptors reference
`scalapb/scalapb.proto`. The real dependency is not required at runtime for the
current text-only implementation, so we register a tiny descriptor to keep imports
and descriptor resolution working.
"""

from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import descriptor_pb2 as _descriptor_pb2
from google.protobuf import symbol_database as _symbol_database

_sym_db = _symbol_database.Default()


def _build_scalapb_descriptor() -> _descriptor.FileDescriptor:
    pool = _descriptor_pool.Default()
    try:
        return pool.FindFileByName("scalapb/scalapb.proto")
    except Exception:
        fdp = _descriptor_pb2.FileDescriptorProto()
        fdp.name = "scalapb/scalapb.proto"
        fdp.package = "scalapb"
        fdp.syntax = "proto3"
        return pool.AddSerializedFile(fdp.SerializeToString())


DESCRIPTOR = _build_scalapb_descriptor()
