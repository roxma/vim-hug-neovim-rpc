
func! neovim_rpc#serveraddr()
	if exists('g:_neovim_rpc_address')
		return g:_neovim_rpc_address
	endif

	execute s:py_cmd 'import neovim_rpc_server'
	execute s:py_cmd 'neovim_rpc_server.start()'

	let g:_nvim_rpc_main_channel = ch_open(g:_neovim_rpc_main_address)

	" close channel before vim exit
	au VimLeavePre *  let s:leaving = 1 | execute s:py_cmd 'neovim_rpc_server.stop()'

	" identify myself
	call ch_sendexpr(g:_nvim_rpc_main_channel,'neovim_rpc_setup')

	return g:_neovim_rpc_address
endfunc

" opt keys:
" - on_exit
func! neovim_rpc#jobstart(cmd,...)

	let l:opts = {}
	if len(a:000)>=1
		let l:opts = a:1
	endif

	" init
	call neovim_rpc#serveraddr()

	let g:_neovim_rpc_tmp_args  = [a:cmd, l:opts]
	execute s:py_cmd 'neovim_rpc_server.jobstart()'
	if g:_neovim_rpc_tmp_ret>0
		" g:_neovim_rpc_tmp_ret is the jobid
		" remember options
		let g:_neovim_rpc_jobs[string(g:_neovim_rpc_tmp_ret)] = {'cmd': a:cmd, 'opts': l:opts}
	endif
	return g:_neovim_rpc_tmp_ret
endfunc

func! neovim_rpc#rpcnotify(channel,event,...)
	let g:_neovim_rpc_tmp_args  = [a:channel,a:event,a:000]
	execute s:py_cmd 'neovim_rpc_server.rpcnotify()'
	" a:000
endfunc

func! neovim_rpc#_on_exit(channel)
	" let g:_neovim_rpc_jobs[g:_neovim_rpc_tmp_ret . ''] = {'cmd': a:cmd, 'opts':a:opts}
	let l:key = string(a:channel)
	if !has_key(g:_neovim_rpc_jobs,l:key)
		return
	endif
	let l:opts = g:_neovim_rpc_jobs[l:key]['opts']
	" remove entry
	unlet g:_neovim_rpc_jobs[l:key]
	if has_key(l:opts,'on_exit')
		call call(l:opts['on_exit'],[a:channel,'','exited'],l:opts)
	endif
endfunc

func! neovim_rpc#_callback()
	execute s:py_cmd 'neovim_rpc_server.process_pending_requests()'
endfunc

if has('python3')
  let s:py_cmd = 'python3'
  let s:pyfile_cmd = 'py3file'
elseif has('python')
  let s:py_cmd = 'python'
  let s:pyfile_cmd = 'pyfile'
endif

let g:_nvim_rpc_main_channel = -1
let g:_neovim_rpc_jobs = {}

let s:leaving = 0
