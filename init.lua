vim.lsp.config["pj"] = {
	cmd = { "./just" },
	filetypes = { "jsonnet" },
}

vim.lsp.enable("pj", true)
