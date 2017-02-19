# vim:set et sw=4 ts=8:
import vim
import json
import msgpack

# vim's python binding doesn't have the `call` method, wrap it here
def nvim_call_function(method,args):
    vim.vars['_neovim_rpc_tmp_args'] = args
    # vim.eval('getcurpos()') return an array of string, it should be an array
    # of int.  Use json_encode to workaround this
    return json.loads(vim.eval('json_encode(call("%s",g:_neovim_rpc_tmp_args))' % method))

def nvim_get_current_buf():
    return msgpack.ExtType(0, msgpack.packb(vim.current.buffer.number))

def nvim_buf_get_name(buffer):
    return nvim_call_function('bufname', [msgpack.unpackb(buffer.data)])

def nvim_get_var(name):
    return vim.vars[name]

def nvim_set_var(name,val):
    vim.vars[name] = val
    return val

def nvim_buf_get_var(buffer,name):
    buffer = msgpack.unpackb(buffer.data)
    return vim.buffers[buffer].vars[name]

def nvim_buf_set_var(buffer,name,val):
    buffer = msgpack.unpackb(buffer.data)
    vim.buffers[buffer].vars[name] = val

def nvim_buf_get_lines(buffer,start,end,*args):

    buffer = msgpack.unpackb(buffer.data)

    if type(start)==type(1) and type(end)==type(1) and type(buffer)==type(1):
        # I think it's more efficient this way
        if end==-1:
            return vim.buffers[buffer][start:]
        return vim.buffers[buffer][start:end]
    start = args[1]+1
    end = args[2]
    if end==-1:
        end = '$'
    else:
        end = end+1
    return nvim_call_function('getbufline',[buffer,start,end])

def nvim_eval(expr):
    return nvim_call_function('eval',[expr])

def buffer_set_lines(buffer,start,end,err,lines):
    buffer = msgpack.unpackb(buffer.data)
    if end==-1:
        vim.buffers[buffer][start:] = lines
    else:
        vim.buffers[buffer][start:end] = lines

    if nvim_call_function('bufwinnr',[buffer])!=-1:
        # vim needs' redraw to update the screen, it seems to be a bug
        vim.command('redraw')


