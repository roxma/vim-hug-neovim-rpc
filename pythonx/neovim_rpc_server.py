# vim:set et sw=4 ts=8:

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
import subprocess
from neovim.api import common as neovim_common
import neovim_rpc_protocol

# protable devnull
if sys.version_info.major==2:
    DEVNULL = open(os.devnull, 'wb')
else:
    from subprocess import DEVNULL


if sys.version_info.major == 2:
    from Queue import Queue, Empty as QueueEmpty
else:
    from queue import Queue, Empty as QueueEmpty

# NVIM_PYTHON_LOG_FILE=nvim.log NVIM_PYTHON_LOG_LEVEL=INFO vim test.md

try:
    # Python 3
    import socketserver
except ImportError:
    # Python 2
    import SocketServer as socketserver

# globals
logger = logging.getLogger(__name__)
# supress the annoying error message: 
#     No handlers could be found for logger "neovim_rpc_server"
logger.addHandler(logging.NullHandler())

request_queue = Queue()


def _channel_id_new():
    with _channel_id_new._lock:
        _channel_id_new._counter += 1
        return _channel_id_new._counter
# static local
_channel_id_new._counter = 0
_channel_id_new._lock = threading.Lock()


class VimChannelHandler(socketserver.BaseRequestHandler):

    _lock = threading.Lock()
    _sock = None

    @classmethod
    def notify(cls,cmd="call neovim_rpc#_callback()"):
        try:
            if not VimChannelHandler._sock:
                return
            with VimChannelHandler._lock:
                encoded = json.dumps(['ex', cmd])
                logger.info("sending notification: %s",encoded)
                VimChannelHandler._sock.send(encoded.encode('utf-8'))
        except Exception as ex:
            logger.exception('VimChannelHandler notify exception for [%s]: %s', cmd, ex)

    @classmethod
    def notify_exited(cls,channel):
        try:
            cmd = "call neovim_rpc#_on_exit(%s)" % channel
            cls.notify(cmd)
        except Exception as ex:
            logger.exception('notify_exited for channel [%s] exception: %s',channel,ex)

    # each connection is a thread
    def handle(self):
        logger.info("=== socket opened ===")
        while True:
            try:
                # 16k buffer by default
                data = self.request.recv(4096)
            except socket.error:
                logger.info("=== socket error ===")
                break
            except IOError:
                logger.info("=== socket closed ===")
                break
            if len(data) == 0:
                logger.info("=== socket closed ===")
                break
            logger.info("received: %s", data)
            try:
                decoded = json.loads(data.decode('utf-8'))
            except ValueError:
                logger.exception("json decoding failed")
                decoded = [-1, '']

            # Send a response if the sequence number is positive.
            # Negative numbers are used for "eval" responses.
            if len(decoded)>=2 and  decoded[0] >= 0 and decoded[1] == 'neovim_rpc_setup':

                VimChannelHandler._sock = self.request

                # initial setup
                encoded = json.dumps(['ex', "scall neovim_rpc#_callback()"])
                logger.info("sending {0}".format(encoded))
                self.request.send(encoded.encode('utf-8'))

            else:

                logger.error('unrecognized request, %s', decoded)

class SocketToStream():

    def __init__(self,sock):
        self._sock = sock

    def read(self,cnt):
        if cnt>4096:
            cnt = 4096
        return self._sock.recv(cnt)

    def write(self,w):
        return self._sock.send(w)

class Receiver(socketserver.BaseRequestHandler):

    channel_sockets = {}

    def handle(self):

        logger.info("=== socket opened for client ===")

        channel = _channel_id_new()

        sock = self.request
        Receiver.channel_sockets[channel] = sock

        try:
            f = SocketToStream(sock)
            unpacker = msgpack.Unpacker(f)
            for unpacked in unpacker:
                logger.info("unpacked: %s", unpacked)
                request_queue.put((f,channel,unpacked))
                # notify vim in order to process request in main thread, and
                # avoiding the stupid json protocol
                VimChannelHandler.notify()

            logger.info('channel %s closed.', channel)

        except:
            logger.exception('unpacker failed.')
        finally:
            try:
                Receiver.channel_sockets.pop(channel)
                sock.close()
            except:
                pass

    @classmethod
    def notify(cls,channel,event,args):
        try:
            channel = int(channel)
            if channel not in cls.channel_sockets:
                logger.info("channel[%s] not in Receiver", channel)
                return
            sock = cls.channel_sockets[channel]
            content = [2, event, args]
            logger.info("notify channel[%s]: %s", channel, content)
            packed = msgpack.packb(neovim_rpc_protocol.to_client(content))
            sock.send(packed)
        except Exception as ex:
            logger.exception("notify failed: %s", ex)

    @classmethod
    def shutdown(cls):
        # close all sockets
        for channel in list(cls.channel_sockets.keys()):
            sock = cls.channel_sockets.get(channel,None)
            if sock:
                logger.info("closing client %s", channel)
                # if don't shutdown the socket, vim will never exit because the
                # recv thread is still blocking
                sock.shutdown(socket.SHUT_RDWR)
                sock.close()


# copied from neovim python-client/neovim/__init__.py
def _setup_logging(name):
    """Setup logging according to environment variables."""
    logger = logging.getLogger(__name__)
    if 'NVIM_PYTHON_LOG_FILE' in os.environ:
        prefix = os.environ['NVIM_PYTHON_LOG_FILE'].strip()
        major_version = sys.version_info[0]
        logfile = '{}_py{}_{}'.format(prefix, major_version, name)
        handler = logging.FileHandler(logfile, 'w')
        handler.formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s @ '
            '%(filename)s:%(funcName)s:%(lineno)s] %(process)s - %(message)s')
        logging.root.addHandler(handler)
        level = logging.INFO
        if 'NVIM_PYTHON_LOG_LEVEL' in os.environ:
            l = getattr(logging,
                        os.environ['NVIM_PYTHON_LOG_LEVEL'].strip(),
                        level)
            if isinstance(l, int):
                level = l
        logger.setLevel(level)

def start():

    _setup_logging('neovim_rpc_server')

    class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
        pass

    # 0 for random port
    global _vim_server
    global _nvim_server
    _vim_server = ThreadedTCPServer(("127.0.0.1", 0), VimChannelHandler)
    _nvim_server = ThreadedTCPServer(("127.0.0.1", 0), Receiver)

    # Start a thread with the server -- that thread will then start one
    # more thread for each request
    main_server_thread = threading.Thread(target=_vim_server.serve_forever)
    clients_server_thread = threading.Thread(target=_nvim_server.serve_forever)

    # Exit the server thread when the main thread terminates
    main_server_thread.daemon = True
    main_server_thread.start()
    clients_server_thread.daemon = True
    clients_server_thread.start()

    return ["{addr[0]}:{addr[1]}".format(addr=_nvim_server.server_address), "{addr[0]}:{addr[1]}".format(addr=_vim_server.server_address)]

def process_pending_requests():

    logger.info("process_pending_requests")
    while True:

        item = None
        try:

            item = request_queue.get(False)

            f, channel, msg = item

            msg = neovim_rpc_protocol.from_client(msg)

            logger.info("get msg from channel [%s]: %s", channel, msg)

            # request format:
            #   - msg[0] type, which is 0
            #   - msg[1] request id
            #   - msg[2] method
            #   - msg[3] arguments

            # notification format:
            #   - msg[0] type, which is 0
            #   - msg[1] method
            #   - msg[2] arguments

            # response format:
            #   - msg[0]: 1
            #   - msg[1]: the request id
            #   - msg[2]: error(if any), format: [code,str]
            #   - msg[3]: result(if not errored)

            if msg[0] == 0:
                #request

                req_typed, req_id, method, args = msg

                try:
                    err=None
                    result = _process_request(channel,method,args)
                except Exception as ex:
                    logger.exception("process failed: %s", ex)
                    # error uccor
                    err = [1,str(ex)]
                    result = None

                result = [1,req_id,err,result]
                logger.info("sending result: %s", result)
                packed = msgpack.packb(neovim_rpc_protocol.to_client(result))
                f.write(packed)
                logger.info("sended")
            if msg[0] == 2:
                # notification
                req_typed, method, args = msg
                try:
                    result = _process_request(channel,method,args)
                    logger.info('notification process result: [%s]', result)
                except Exception as ex:
                    logger.exception("process failed: %s", ex)

        except QueueEmpty as em:
            pass
        except Exception as ex:
            logger.exception("exception during process: %s", ex)
        finally:
            if item:
                request_queue.task_done()
            else:
                # item==None means the queue is empty
                break

def _process_request(channel,method,args):
    if method=='vim_get_api_info':
        # this is the first request send from neovim client
        api_info = neovim_rpc_server_api_info.API_INFO
        return [channel,api_info]
    if hasattr(neovim_rpc_methods,method):
        return getattr(neovim_rpc_methods,method)(*args)
    else:
        logger.error("method %s not implemented", method)
        raise Exception('%s not implemented' % method)

def rpcnotify(channel,method,args):
    Receiver.notify(channel,method,args)

def stop():

    logger.info("stop begin")

    # close tcp channel server
    _nvim_server.shutdown()
    _nvim_server.server_close()

    # close the main channel
    try:
        vim.command('call ch_close(g:_neovim_rpc_main_channel)')
    except Exception as ex:
        logger.info("ch_close failed: %s", ex)

    # remove all sockets
    Receiver.shutdown()

    try:
        # stop the main channel
        _vim_server.shutdown()
    except Exception as ex:
        logger.info("_vim_server shutodwn failed: %s", ex)

    try:
        _vim_server.server_close()
    except Exception as ex:
        logger.info("_vim_server close failed: %s", ex)


