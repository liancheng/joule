vim.lsp.config["joule"] = {
	cmd = { "joule", "serve" },
	filetypes = { "jsonnet" },
	root_markers = { "vendor", "jsonnetfile.json", ".git" },
	capabilities = {
		workspace = {
			didChangeConfiguration = {
				dynamicRegistration = true,
			},
			didChangeWatchedFiles = {
				dynamicRegistration = true,
			},
		},
	},
	settings = {
		library_paths = { "**/vendor", "**/jsonnet" },
		exclude = { "**/.*" },
		include = { "**/*" },
		suffixes = { "jsonnet", "libsonnet" },
	},
}

vim.lsp.enable("joule", true)
vim.lsp.inlay_hint.enable(true)
vim.lsp.set_log_level("TRACE")
