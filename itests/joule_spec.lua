local repo = vim.uv.cwd()

describe("joule", function()
  local workspace

  before_each(function()
    -- Resolve the symlinks, for example `/var` to `/private/var` on macOS. Neovim
    -- reports the root directory with the real path.
    local tmp = vim.fn.tempname()
    vim.fn.mkdir(tmp .. "/.git", "p")
    workspace = assert(vim.uv.fs_realpath(tmp))
    vim.fn.writefile({ "{ a: 1 }" }, workspace .. "/main.jsonnet")

    vim.lsp.config("joule", {
      cmd = { "uv", "run", "--frozen", "--project", repo, "joule", "serve" },
      filetypes = { "jsonnet" },
      root_markers = { ".git" },
    })
    vim.lsp.enable("joule")
  end)

  after_each(function()
    for _, client in ipairs(vim.lsp.get_clients({ name = "joule" })) do
      client:stop(true)
    end
    vim.cmd("silent! %bwipeout!")
    vim.fn.delete(workspace, "rf")
  end)

  it("attaches to a Jsonnet file", function()
    vim.cmd.edit(workspace .. "/main.jsonnet")
    assert.are.equal("jsonnet", vim.bo.filetype)

    local client
    local attached = vim.wait(20000, function()
      client = vim.lsp.get_clients({ bufnr = 0, name = "joule" })[1]
      return client ~= nil and client.initialized == true
    end, 100)

    assert(attached, "Joule did not attach to the buffer")
    assert.are.equal(workspace, client.root_dir)
    assert.is_truthy(client.server_capabilities.documentSymbolProvider)
  end)
end)
