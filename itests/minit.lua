#!/usr/bin/env -S nvim -l

-- Keep the plugins, the rocks, and the state of the tests out of the user setup.
vim.env.LAZY_STDPATH = ".tests"
load(vim.fn.system("curl -s https://raw.githubusercontent.com/folke/lazy.nvim/main/bootstrap.lua"))()

require("lazy.minit").busted({
  spec = {},
})
