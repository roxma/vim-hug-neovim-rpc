# vim:set et sw=4 ts=8:
import vim
import msgpack

# vim's python binding doesn't have the `call` method, wrap it here
def call_vimfunc(method,*args):
    vim.vars['_neovim_rpc_tmp_args'] = args
    return vim.eval('call("%s",g:_neovim_rpc_tmp_args)' % method)

def nvim_get_current_buf():
    return msgpack.ExtType(0, msgpack.packb(vim.current.buffer.number))

def nvim_buf_get_name(buffer):
    return call_vimfunc('bufname', msgpack.unpackb(buffer.data))

def nvim_get_var(name):
    return vim.vars[name]

def nvim_set_var(name,val):
    vim.vars[name] = val
    return val

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
    return call_vimfunc('getbufline',buffer,start,end)

def nvim_eval(expr):
    return vim.eval(expr)

