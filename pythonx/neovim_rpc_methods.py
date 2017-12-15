# vim:set et sw=4 ts=8:
import vim
import json
import msgpack

# vim's python binding doesn't have the `call` method, wrap it here
def nvim_call_function(method,args):
    vim.vars['_neovim_rpc_tmp_args'] = args
    # vim.eval('getcurpos()') return an array of string, it should be an array
    # of int.  Use json_encode to workaround this
    return vim.bindeval('call("%s",g:_neovim_rpc_tmp_args)' % method)

def nvim_get_current_buf():
    return vim.current.buffer

def nvim_list_bufs():
    return list(vim.buffers)

# {'return_type': 'Integer', 'since': 1, 'method': True, 'parameters': [['Buffer', 'buffer']], 'name': 'nvim_buf_get_number'}
def nvim_buf_get_number(buf):
    return buf.number

def nvim_buf_get_name(buffer):
    return buffer.name

def nvim_get_var(name):
    return vim.vars[name]

def nvim_set_var(name,val):
    vim.vars[name] = val
    return val

def nvim_buf_get_var(buffer,name):
    return json.loads(vim.eval('json_encode(getbufvar(%s, "%s"))' % (buffer.number, name)))

def nvim_buf_set_var(buffer,name,val):
    buffer.vars[name] = val

def nvim_buf_get_lines(buffer,start,end,*args):
    if start < 0:
        start = len(buffer) + 1 + start
    if end < 0:
        end = len(buffer) + 1 + end
    return buffer[start:end]

def nvim_eval(expr):
    return nvim_call_function('eval',[expr])

def nvim_buf_set_lines(buffer,start,end,err,lines):
    if start < 0:
        start = len(buffer) + 1 + start
    if end < 0:
        end = len(buffer) + 1 + end
    buffer[start:end] = lines

    if nvim_call_function('bufwinnr',[buffer.number])!=-1:
        # vim needs' redraw to update the screen, it seems to be a bug
        vim.command('redraw')

buffer_set_lines = nvim_buf_set_lines

def buffer_line_count(buffer):
    return len(buffer)

def nvim_buf_line_count(buffer):
    return len(buffer)

def nvim_get_option(name):
    return vim.options[name]

def nvim_buf_get_option(buf, name):
    return buf.options[name]

def nvim_set_option(name, val):
    vim.options[name] = val

def nvim_command(cmd):
    vim.command(cmd)

def nvim_get_current_win():
    return vim.current.window

def nvim_win_get_cursor(window):
    return window.cursor

def nvim_out_write(s):
    nvim_call_function('neovim_rpc#_nvim_out_write', [s])

def nvim_err_write(s):
    nvim_call_function('neovim_rpc#_nvim_err_write', [s])

# NOTE https://github.com/autozimu/LanguageClient-neovim/pull/151#issuecomment-339198527
# TODO
def nvim_buf_add_highlight(buf, src_id, *args):
    return src_id

# NOTE https://github.com/autozimu/LanguageClient-neovim/pull/151#issuecomment-339198527
# TODO
def nvim_buf_clear_highlight(*args):
    pass
