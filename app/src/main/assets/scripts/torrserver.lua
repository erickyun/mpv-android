local mp = require "mp"
local options = require "mp.options"

local opts = {
    enabled = true,
    server = "http://127.0.0.1:8090",
}

options.read_options(opts, "torrserver")

local function starts_with(value, prefix)
    return value:sub(1, #prefix) == prefix
end

local function is_torrent_source(value)
    if value == nil or value == "" then
        return false
    end

    local lower = value:lower()
    if starts_with(lower, "magnet:") or starts_with(lower, "torrs://") then
        return true
    end

    if starts_with(lower, "http://") or starts_with(lower, "https://") then
        return lower:match("%.torrent([?#].*)?$") ~= nil
    end

    return false
end

local function url_encode(value)
    return (value:gsub("([^%w%-_%.~])", function(char)
        return string.format("%%%02X", string.byte(char))
    end))
end

local function normalized_server()
    local server = (opts.server or ""):gsub("^%s+", ""):gsub("%s+$", "")
    server = server:gsub("/+$", "")
    if server == "" then
        server = "http://127.0.0.1:8090"
    end
    return server
end

mp.add_hook("on_load", 20, function()
    if not opts.enabled then
        return
    end

    local source = mp.get_property("stream-open-filename")
    if source == nil or source == "" then
        source = mp.get_property("path")
    end

    if not is_torrent_source(source) then
        return
    end

    local playlist_url = normalized_server()
        .. "/stream/torrent.m3u?link="
        .. url_encode(source)
        .. "&m3u"

    mp.msg.info("Routing torrent through TorrServer: " .. playlist_url)
    mp.osd_message("Opening torrent with TorrServer…", 3)
    mp.set_property("stream-open-filename", playlist_url)
end)
