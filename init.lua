vim.lsp.config["just"] = {
	cmd = { "./just", "serve" },
	filetypes = { "jsonnet" },
}

vim.lsp.enable("just", true)
