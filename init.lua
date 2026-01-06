vim.lsp.config["just"] = {
	cmd = { "just", "serve" },
	filetypes = { "jsonnet" },
	root_markers = { ".git", "jsonnetfile.json" },
}

vim.lsp.enable("just", true)
vim.lsp.inlay_hint.enable(true)
vim.lsp.set_log_level("TRACE")
