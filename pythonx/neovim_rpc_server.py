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


class MainChannelHandler(socketserver.BaseRequestHandler):

    _lock = threading.Lock()
    _sock = None

    @classmethod
    def notify(cls,cmd="call neovim_rpc#_callback()"):
        try:
            if not MainChannelHandler._sock:
                return
            with MainChannelHandler._lock:
                encoded = json.dumps(['ex', cmd])
                logger.info("sending notification: %s",encoded)
                MainChannelHandler._sock.send(encoded.encode('utf-8'))
        except Exception as ex:
            logger.exception('MainChannelHandler notify exception for [%s]: %s', cmd, ex)

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

                MainChannelHandler._sock = self.request

                # initial setup
                encoded = json.dumps(['ex', "scall neovim_rpc#_callback()"])
                logger.info("sending {0}".format(encoded))
                self.request.sendall(encoded.encode('utf-8'))

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

class TcpChannelHandler(socketserver.BaseRequestHandler):

    channel_sockets = {}

    def handle(self):

        logger.info("=== socket opened for client ===")

        channel = _channel_id_new()

        sock = self.request
        TcpChannelHandler.channel_sockets[channel] = sock

        try:
            f = SocketToStream(sock)
            unpacker = msgpack.Unpacker(f)
            for unpacked in unpacker:
                logger.info("unpacked: %s", unpacked)
                request_queue.put((f,channel,unpacked))
                # notify vim in order to process request in main thread, and
                # avoiding the stupid json protocol
                MainChannelHandler.notify()

            logger.info('channel %s closed.', channel)

        except:
            logger.exception('unpacker failed.')
        finally:
            try:
                TcpChannelHandler.channel_sockets.pop(channel)
                sock.close()
            except:
                pass

    @classmethod
    def notify(cls,channel,event,args):
        try:
            channel = int(channel)
            if channel not in cls.channel_sockets:
                logger.info("channel[%s] not in TcpChannelHandler", channel)
                return
            sock = cls.channel_sockets[channel]
            content = [2, event, args]
            logger.info("notify channel[%s]: %s", channel, content)
            packed = msgpack.packb(content)
            sock.send(packed)
        except Exception as ex:
            logger.exception("notify failed: %s", ex)

    @classmethod
    def shutdown(cls):
        # close all sockets
        for channel in cls.channel_sockets:
            sock = cls.channel_sockets.get(channel,None)
            if sock:
                logger.info("closing client %s", channel)
                # if don't shutdown the socket, vim will never exit because the
                # recv thread is still blocking
                sock.shutdown(socket.SHUT_RDWR)
                sock.close()


class JobChannelHandler(threading.Thread):

    channel_procs = {}

    is_stopping = False
    stopping_queue = Queue()
    stopping_cnt = 0

    def __init__(self,proc,channel):
        channel = int(channel)
        self._proc = proc
        self._channel = channel
        threading.Thread.__init__(self)

        JobChannelHandler.channel_procs[channel] = proc


    def run(self):

        channel = self._channel
        proc = self._proc
        try:

            logger.info("reading for job: %s", channel)
            class HackStdout():
                def __init__(self,o):
                    self._stdout = o
                def read(self,cnt):
                    return self._stdout.read(1)

            unpacker = msgpack.Unpacker(HackStdout(proc.stdout))
            for unpacked in unpacker:
                logger.info("unpacked: %s", unpacked)
                request_queue.put((proc.stdin, channel, unpacked))
                # notify vim in order to process request in main thread, and
                # avoiding the stupid json protocol
                MainChannelHandler.notify()

            # wait for terminating
            logger.exception("channel [%s] has terminated", channel)

        except Exception as ex:
            logger.exception("failed for channel %s, %s", channel)
        finally:
            try:
                # remove it from registration
                JobChannelHandler.channel_procs.pop(channel)
                if proc.poll() is None:
                    # kill it 
                    logger.exception("killing channel[%s] in finally block", channel)
                    proc.kill()
            except Exception as ex:
                logger.exception("exception during finally block for job channel %s: %s", channel,ex)

            # notify on exit
            MainChannelHandler.notify_exited(channel)

            # notify here
            if JobChannelHandler.is_stopping:
                JobChannelHandler.stopping_queue.put(channel)

    @classmethod
    def notify(cls,channel,event,args):
        try:
            channel = int(channel)
            if channel not in cls.channel_procs:
                logger.info("channel[%s] not in JobChannelHandler", channel)
                return
            proc = cls.channel_procs[channel]
            content = [2, event, args]
            logger.info("notify channel[%s]: %s", channel, content)
            packed = msgpack.packb(content)
            proc.stdin.write(packed)
        except Exception as ex:
            logger.exception("notify failed: %s", ex)

    @classmethod
    def shutdown(cls):

        JobChannelHandler.is_stopping = True
        cnt = 0

        """
        This method is called from the main thread, terminating all jobs
        """
        for channel in cls.channel_procs:
            logger.info('terminating channel [%s]',channel)
            try:
                cls.channel_procs[channel].terminate()
            except Exception as ex:
                logger.info('send terminate signal failed for channel [%s]: %s',channel, ex)
            finally:
                cnt += 1

        cls.stopping_cnt = cnt

    @classmethod
    def join_shutdown(cls):

        for i in range(cls.stopping_cnt):
            try:
                channel = JobChannelHandler.stopping_queue.get(True,timeout=2)
                # call on exit handler
                cmd = 'call neovim_rpc#_on_exit(%s)' % channel
                logger.info("shutdown: %s",cmd)
                vim.command(cmd)
            except QueueEmpty as ex:
                pass

        # getting out of patience, kill them all
        cls.killall()


    @classmethod
    def killall(cls):
        logger.info('killall jobs')
        for channel in cls.channel_procs:
            logger.info('killing channel [%s]',channel)
            try:
                cls.channel_procs[channel].kill()

                # call on exit handler
                cmd = 'call neovim_rpc#_on_exit(%s)' % channel
                logger.info("shutdown: %s",cmd)
                vim.command(cmd)

            except Exception as ex:
                logger.info('kill failed for channel [%s]: %s',channel, ex)



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
    global _server_main
    global _server_clients
    _server_main = ThreadedTCPServer(("127.0.0.1", 0), MainChannelHandler)
    _server_clients = ThreadedTCPServer(("127.0.0.1", 0), TcpChannelHandler)

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
    while True:

        item = None
        try:

            item = request_queue.get(False)

            f, channel, msg = item

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
                    f.write(packed)
                    continue

                result = [1,req_id,None,result]
                logger.info("sending result: %s", result)
                packed = msgpack.packb(result)
                f.write(packed)

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

def jobstart():
    channel = _channel_id_new()
    """Launches 'command' windowless and waits until finished"""
    startupinfo = None
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    except:
        pass
    proc = subprocess.Popen(args=vim.vars['_neovim_rpc_tmp_args'][0], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=DEVNULL, startupinfo=startupinfo)
    handler = JobChannelHandler(proc,channel)
    handler.start()
    logger.info("jobstart for %s", channel)
    vim.vars['_neovim_rpc_tmp_ret'] = channel
    return channel

def rpcnotify():
    args = vim.vars['_neovim_rpc_tmp_args']
    channel, method, args = args 
    args = json.loads(vim.eval('json_encode(a:000)'))
    JobChannelHandler.notify(channel,method,args)
    TcpChannelHandler.notify(channel,method,args)

def stop_pre():

    logger.info("stop_pre begin")

    # close tcp channel server
    _server_clients.shutdown()
    _server_clients.server_close()

    # remove all sockets
    TcpChannelHandler.shutdown()
    JobChannelHandler.shutdown()

    logger.info("stop_pre end")


def stop_post():

    logger.info("stop_post begin")

    JobChannelHandler.join_shutdown()

    # close the main channel
    try:
        vim.command('call ch_close(g:_neovim_rpc_main_channel)')
    except Exception as ex:
        logger.info("ch_close failed: %s", ex)

    try:
        # stop the main channel
        _server_main.shutdown()
    except Exception as ex:
        logger.info("_server_main shutodwn failed: %s", ex)

    try:
        _server_main.server_close()
    except Exception as ex:
        logger.info("_server_main close failed: %s", ex)


