local repo = vim.uv.cwd()
local K = vim.lsp.protocol.SymbolKind

---@type vim.lsp.ClientConfig
local lsp_config = {
  cmd = { "uv", "run", "--frozen", "--project", repo, "joule", "serve" },
  filetypes = { "jsonnet" },
  root_markers = { ".git" },
}

---@param line integer
---@param character integer
---@return lsp.Position
local function at(line, character)
  return { line = line, character = character }
end

---@param start lsp.Position
---@param stop lsp.Position
---@return lsp.Range
local function span(start, stop)
  return { start = start, ["end"] = stop }
end

describe("joule", function()
  local workspace

  ---@param name string
  ---@param lines string[]
  ---@return vim.lsp.Client
  local function open(name, lines)
    local path = workspace .. "/" .. name
    vim.fn.writefile(lines, path)
    vim.cmd.edit(path)

    local client
    local attached = vim.wait(20000, function()
      client = vim.lsp.get_clients({ bufnr = 0, name = "joule" })[1]
      return client ~= nil and client.initialized == true
    end, 100)

    assert(attached, "Joule did not attach to the buffer")
    return client
  end

  before_each(function()
    -- Resolve the symlinks, for example `/var` to `/private/var` on macOS. Neovim
    -- reports the root directory with the real path.
    local tmp = vim.fn.tempname()
    vim.fn.mkdir(tmp .. "/.git", "p")
    workspace = assert(vim.uv.fs_realpath(tmp))

    vim.lsp.config("joule", lsp_config)
    vim.lsp.enable("joule")
  end)

  after_each(function()
    for _, client in ipairs(vim.lsp.get_clients({ name = "joule" })) do
      client:stop()
    end

    -- Neovim removes a client only after its process exits.
    local stopped = vim.wait(5000, function()
      return #vim.lsp.get_clients({ name = "joule" }) == 0
    end, 50)

    assert(stopped, "Joule did not stop")
    vim.cmd("silent! %bwipeout!")
    vim.fn.delete(workspace, "rf")
  end)

  it("attaches to a Jsonnet file", function()
    local client = open("main.jsonnet", { "{ a: 1 }" })

    assert.are.equal("jsonnet", vim.bo.filetype)
    assert.are.equal(workspace, client.root_dir)
    assert.is_truthy(client.server_capabilities.documentSymbolProvider)
  end)

  it("serves document symbols", function()
    local client = open("main.jsonnet", {
      "local x = 1;",
      "{ a: x }",
    })

    local response = client:request_sync("textDocument/documentSymbol", {
      textDocument = vim.lsp.util.make_text_document_params(0),
    }, 5000, 0)

    assert(response, "Joule did not answer the request")
    assert.is_nil(response.err)
    assert.are.same({
      {
        name = "x",
        kind = K.Variable,
        range = span(at(0, 6), at(0, 11)),
        selectionRange = span(at(0, 6), at(0, 7)),
      },
      {
        name = "a",
        kind = K.Field,
        range = span(at(1, 2), at(1, 6)),
        selectionRange = span(at(1, 2), at(1, 3)),
      },
    }, response.result)
  end)

  it("serves folding ranges", function()
    local client = open("main.jsonnet", {
      "{",
      "  a: [",
      "    1,",
      "  ],",
      "}",
    })

    local response = client:request_sync("textDocument/foldingRange", {
      textDocument = vim.lsp.util.make_text_document_params(0),
    }, 5000, 0)

    assert(response, "Joule did not answer the request")
    assert.is_nil(response.err)
    assert.are.same({
      {
        startLine = 1,
        startCharacter = 5,
        endLine = 3,
        endCharacter = 3,
      },
      {
        startLine = 0,
        startCharacter = 0,
        endLine = 4,
        endCharacter = 1,
      },
    }, response.result)
  end)
end)
