#!/usr/bin/env -S nvim -l

-- Keep the plugins, the rocks, and the state of the tests out of the user setup.
vim.env.LAZY_STDPATH = ".tests"
dofile("vendor/lazy.nvim/bootstrap.lua")

require("lazy.minit").busted({
  spec = {},
  -- Pin the versions of the test plugins, e.g., busted. A scheduled update
  -- changes this file. Without the update, run the tests with `LAZY_OFFLINE=1`.
  lockfile = "itests/lazy-lock.json",
})
