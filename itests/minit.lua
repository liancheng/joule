#!/usr/bin/env -S nvim -l

-- Keep the plugins, the rocks, and the state of the tests out of the user setup.
vim.env.LAZY_STDPATH = ".tests"
dofile("vendor/lazy.nvim/bootstrap.lua")

require("lazy.minit").busted({
  spec = {},
})
