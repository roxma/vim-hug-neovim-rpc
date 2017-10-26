import json
import socket
import sys
import os
import threading
import vim
import logging
import msgpack
import neovim_rpc_server_api_info
import neovim_rpc_methods
import threading
import socket
import time
from neovim.api.common import decode_if_bytes

BUFFER_TYPE = type(vim.current.buffer)
BUFFER_TYPE_ID = neovim_rpc_server_api_info.API_INFO['types']['Buffer']['id']
WINDOW_TYPE = type(vim.current.window)
WINDOW_TYPE_ID = neovim_rpc_server_api_info.API_INFO['types']['Window']['id']

def walk(fn, obj):
    if type(obj) in [list, tuple, vim.List]:
        return list(walk(fn, o) for o in obj)
    if type(obj) in [dict, vim.Dictionary]:
        return dict((walk(fn, k), walk(fn, v)) for k, v in
                    obj.items())
    return fn(obj)

def from_client(msg):

    def handler(obj):
        if type(obj) is msgpack.ExtType:
            if obj.code == BUFFER_TYPE_ID:
                return vim.buffers[msgpack.unpackb(obj.data)]
            if obj.code == WINDOW_TYPE_ID:
                return vim.windows[msgpack.unpackb(obj.data) - 1]
        elif obj is None:
            return ''
        if sys.version_info.major!=2:
            # python3 needs decode
            obj = decode_if_bytes(obj)
        return obj

    return walk(handler,msg)

def to_client(msg):
    def handler( obj):
        if type(obj) == BUFFER_TYPE:
            return msgpack.ExtType(BUFFER_TYPE_ID, msgpack.packb(obj.number))
        if type(obj) == WINDOW_TYPE:
            return msgpack.ExtType(WINDOW_TYPE_ID, msgpack.packb(obj.number))
        if type(obj) == vim.Function:
            return obj.name
        return obj
    return walk(handler, msg)

