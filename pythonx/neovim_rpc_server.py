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

if sys.version_info.major == 2:
    from Queue import Queue
else:
    from queue import Queue

# NVIM_PYTHON_LOG_FILE=nvim.log NVIM_PYTHON_LOG_LEVEL=INFO vim test.md

logger = logging.getLogger(__name__)

try:
    # Python 3
    import socketserver
except ImportError:
    # Python 2
    import SocketServer as socketserver

class NvimClientHandler(socketserver.BaseRequestHandler):

    channel_id_inc = 0
    channel_sockets = {}

    request_queue = Queue()

    _lock = threading.Lock()


    def handle(self):

        logger.info("=== socket opened for client ===")

        with NvimClientHandler._lock:
            NvimClientHandler.channel_id_inc += 1
            channel = NvimClientHandler.channel_id_inc

        sock = self.request
        NvimClientHandler.channel_sockets[channel] = sock

        try:
            class HackSocket():
                def read(self,cnt):
                    if cnt>4096:
                        cnt = 4096
                    return sock.recv(cnt)
            hack = HackSocket()
            unpacker = msgpack.Unpacker(hack)
            for unpacked in unpacker:
                logger.info("unpacked: %s", unpacked)
                NvimClientHandler.request_queue.put((sock,channel,unpacked))
                # notify vim in order to process request in main thread, and
                # avoiding the stupid json protocol
                MainChannelHandler.notify()

            logger.info('channel %s closed.', channel)

        except:
            logger.exception('unpacker failed.')
        finally:
            try:
                NvimClientHandler.channel_sockets.pop(channel)
                sock.close()
            except:
                pass

class MainChannelHandler(socketserver.BaseRequestHandler):

    _lock = threading.Lock()
    _sock = None
    _number = 0

    @classmethod
    def notify(cls):
        MainChannelHandler._number += 1
        num = MainChannelHandler._number
        if not MainChannelHandler._sock:
            return
        with MainChannelHandler._lock:
            encoded = json.dumps(['ex', "call neovim_rpc#_callback()"])
            logger.info("sending notification {0}".format(encoded))
            MainChannelHandler._sock.send(encoded.encode('utf-8'))

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

                MainChannelHandler._sock = self.request

                # initial setup
                encoded = json.dumps(['ex', "scall neovim_rpc#_callback()"])
                logger.info("sending {0}".format(encoded))
                self.request.sendall(encoded.encode('utf-8'))

            else:

                logger.error('unrecognized request, %s', decoded)


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    pass

# copied from neovim python-client/neovim/__init__.py
def setup_logging(name):
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

    setup_logging('neovim_rpc_server')

    # 0 for random port
    global _server_main
    global _server_clients
    _server_main = ThreadedTCPServer(("127.0.0.1", 0), MainChannelHandler)
    _server_clients = ThreadedTCPServer(("127.0.0.1", 0), NvimClientHandler)

    # Start a thread with the server -- that thread will then start one
    # more thread for each request
    main_server_thread = threading.Thread(target=_server_main.serve_forever)
    clients_server_thread = threading.Thread(target=_server_clients.serve_forever)

    # Exit the server thread when the main thread terminates
    main_server_thread.daemon = True
    main_server_thread.start()
    clients_server_thread.daemon = True
    clients_server_thread.start()

    vim.vars['_neovim_rpc_address']  = "{addr[0]}:{addr[1]}".format(addr=_server_clients.server_address)
    vim.vars['_neovim_rpc_main_address']  = "{addr[0]}:{addr[1]}".format(addr=_server_main.server_address)

def process_pending_requests():

    logger.info("process_pending_requests")
    q = NvimClientHandler.request_queue
    while True:

        try:
            # non blocking
            try:
                item = q.get(False)
            except Exception as ex:
                logger.info('queue is empty: %s', ex)
                break

            sock, channel, msg = item

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
                    result = _process_request(channel,method,args)
                except Exception as ex:
                    logger.exception("process failed: %s", ex)
                    # error uccor
                    packed = msgpack.packb([1, req_id, [1,str(ex)], None])
                    logger.info("sending result: %s", packed)
                    sock.send(packed)
                    continue

                result = [1,req_id,None,result]
                logger.info("sending result: %s", result)
                packed = msgpack.packb(result)
                sock.send(packed)

            if msg[0] == 2:
                # notification
                req_typed, method, args = msg

                try:
                    result = _process_request(channel,method,args)
                    logger.info('notification process result: [%s]', result)
                except Exception as ex:
                    logger.exception("process failed: %s", ex)

        finally:

            q.task_done()

# vim's python binding doesn't have the `call` method, wrap it here
def call_vimfunc(method,*args):
    vim.vars['_neovim_rpc_tmp_args'] = args
    return vim.eval('call("%s",g:_neovim_rpc_tmp_args)' % method)

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

def stop():

    logger.info("stopping")
    _server_main.shutdown()
    _server_main.server_close()
    _server_clients.shutdown()
    _server_clients.server_close()

    # close all clients
    for channel in NvimClientHandler.channel_sockets:
        sock = NvimClientHandler.channel_sockets.get(channel,None)
        if sock:
            logger.info("closing client %s", channel)
            # if don't shutdown the socket, vim will never exit because the
            # recv thread is still blocking
            sock.shutdown(socket.SHUT_RDWR)
            sock.close()

    logger.info("shutdown finished")

