
if has('python3')
  let s:py_cmd = 'python3'
  let s:pyfile_cmd = 'py3file'
elseif has('python')
  let s:py_cmd = 'python'
  let s:pyfile_cmd = 'pyfile'
endif

let g:_nvim_prc_channel = -1

func! neovim_rpc#address()
	if exists('g:_neovim_rpc_address')
		return g:_neovim_rpc_address
	endif

	execute s:py_cmd 'import neovim_rpc_server'
	execute s:py_cmd 'neovim_rpc_server.start()'

	let g:_nvim_prc_channel = ch_open(g:_neovim_rpc_main_address)

	" close channel before vim exit
	au VimLeavePre *  call ch_close(g:_nvim_prc_channel) | execute s:py_cmd 'neovim_rpc_server.stop()'

	" identify myself
	call ch_sendexpr(g:_nvim_prc_channel,'neovim_rpc_setup')

	return g:_neovim_rpc_address
endfunc

func! neovim_rpc#_callback()
	execute s:py_cmd 'neovim_rpc_server.process_pending_requests()'
endfunc

