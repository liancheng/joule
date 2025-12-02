vim.lsp.config["just"] = {
	cmd = { "./just", "serve" },
	filetypes = { "jsonnet" },
}

vim.lsp.enable("just", true)
vim.lsp.inlay_hint.enable(true)
