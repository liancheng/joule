vim.lsp.config["just"] = {
	cmd = { "just", "serve" },
	filetypes = { "jsonnet" },
	root_markers = { "vendor", "jsonnetfile.json", ".git" },
}

vim.lsp.enable("just", true)
vim.lsp.inlay_hint.enable(true)
vim.lsp.set_log_level("TRACE")
