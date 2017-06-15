
# vim-hug-neovim-rpc

This is an **experimental project**, trying to build a compatible layer for
[neovim rpc client](https://github.com/neovim/python-client) working on vim8.
I started this project because I want to fix the [vim8
support](https://github.com/roxma/nvim-completion-manager/issues/14) issue for
[nvim-completion-manager](https://github.com/roxma/nvim-completion-manager).

Since this is a general perpurse module, other plugins needing rpc support may
benefits from this project. However, there're many neovim rpc methods I havn't
implemented yet, which make this an experimental plugin. **Please fork and
open a PR if you get any idea on improving it**.

![screencast](https://cloud.githubusercontent.com/assets/4538941/23102626/9e1bd928-f6e7-11e6-8fa2-2776f70819d9.gif)

## Requirements

- vim8 with `has('python')` or `has('python3')`
- installation of
  [neovim/python-client](https://github.com/neovim/python-client). (`pip
  install neovim`). There should be no error when you execute `:python import
  neovim` or `:python3 import neovim`

Use `:echo neovim_rpc#serveraddr()` to test the installation. It should print
something like `127.0.0.1:51359`.

## Overall Implementation

```
   "vim-hug-neovim-rpc - Sequence Diagram"
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^


┌───┐            ┌──────────┐                  ┌───────────┐                    ┌──────┐
│VIM│            │VIM Server│                  │NVIM Server│                    │Client│
└─┬─┘            └────┬─────┘                  └─────┬─────┘                    └──┬───┘
  │   Launch thread   │                              │                             │
  │───────────────────>                              │                             │
  │                   │                              │                             │
  │                  Launch thread                   │                             │
  │─────────────────────────────────────────────────>│                             │
  │                   │                              │                             │
  │ `ch_open` connect │                              │                             │
  │───────────────────>                              │                             │
  │                   │                              │                             │
  │                   │────┐                         │                             │
  │                   │    │ Launch VimHandler thread│                             │
  │                   │<───┘                         │                             │
  │                   │                              │                             │
  │                   │                              │           Connect           │
  │                   │                              │<─────────────────────────────
  │                   │                              │                             │
  │                   │                              ────┐
  │                   │                                  │ Launch NvimHandler thread
  │                   │                              <───┘
  │                   │                              │                             │
  │                   │                              │    Request (msgpack rpc)    │
  │                   │                              │<─────────────────────────────
  │                   │                              │                             │
  │                   │                              ────┐                         │
  │                   │                                  │ Request enqueue         │
  │                   │                              <───┘                         │
  │                   │                              │                             │
  │                   │     notify (method call)     │                             │
  │                   │ <────────────────────────────│                             │
  │                   │                              │                             │
  │ notify (json rpc) │                              │                             │
  │<───────────────────                              │                             │
  │                   │                              │                             │
  ────┐                                              │                             │
      │ Request dequeue                              │                             │
  <───┘                                              │                             │
  │                   │                              │                             │
  ────┐               │                              │                             │
      │ Process       │                              │                             │
  <───┘               │                              │                             │
  │                   │                              │                             │
  │                   │      Send response (msgpack rpc)                           │
  │────────────────────────────────────────────────────────────────────────────────>
┌─┴─┐            ┌────┴─────┐                  ┌─────┴─────┐                    ┌──┴───┐
│VIM│            │VIM Server│                  │NVIM Server│                    │Client│
└───┘            └──────────┘                  └───────────┘                    └──────┘
```

<!-- 
@startuml

title "vim-hug-neovim-rpc - Sequence Diagram"

VIM -> "VIM Server": Launch thread
VIM -> "NVIM Server": Launch thread
VIM -> "VIM Server": `ch_open` connect
"VIM Server" -> "VIM Server": Launch VimHandler thread

Client-> "NVIM Server": Connect
"NVIM Server" -> "NVIM Server": Launch NvimHandler thread
Client -> "NVIM Server": Request (msgpack rpc)
"NVIM Server" -> "NVIM Server": Request enqueue
"NVIM Server" -> "VIM Server": notify (method call)
"VIM Server" -> VIM: notify (json rpc)
VIM -> VIM: Request dequeue 
VIM -> VIM: Process
VIM -> Client: Send response (msgpack rpc)

@enduml
-->

## Debugging

```sh
NVIM_PYTHON_LOG_FILE=nvim.log NVIM_PYTHON_LOG_LEVEL=DEBUG vim
```

## Known isues

- [delay on vim8 exit](https://github.com/roxma/nvim-completion-manager/issues/52)

