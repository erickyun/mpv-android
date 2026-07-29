package `is`.xyz.mpv

import android.content.Context
import android.preference.PreferenceManager
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import java.util.concurrent.atomic.AtomicReference

internal object TorBox {
    const val PREF_ENABLED = "torbox_enabled"
    const val PREF_API_KEY = "torbox_api_key"

    private const val API_BASE = "https://api.torbox.app/v1/api/torrents"
    private const val TAG = "mpv-torbox"
    private const val RESOLVE_TIMEOUT_MS = 45_000L

    private val videoExtensions = setOf(
        "mkv", "mp4", "m4v", "webm", "avi", "mov", "ts", "m2ts", "mts", "wmv", "flv", "mpg", "mpeg"
    )

    /**
     * Resolves a magnet link through TorBox. Returns null when TorBox is disabled,
     * is not configured, the source is unsupported, or the API request fails.
     *
     * Network work runs on a worker thread. The caller waits for a bounded amount
     * of time because MPVActivity needs a final URL before handing it to libmpv.
     */
    fun resolve(context: Context, source: String): String? {
        if (!source.startsWith("magnet:", ignoreCase = true))
            return null

        val preferences = PreferenceManager.getDefaultSharedPreferences(context)
        if (!preferences.getBoolean(PREF_ENABLED, false))
            return null

        val apiKey = preferences.getString(PREF_API_KEY, "")?.trim().orEmpty()
        if (apiKey.isBlank()) {
            Log.w(TAG, "TorBox is enabled but no API key is configured")
            return null
        }

        val result = AtomicReference<String?>(null)
        val worker = Thread({
            try {
                result.set(resolveNetwork(apiKey, source))
            } catch (error: Exception) {
                Log.e(TAG, "TorBox resolution failed", error)
            }
        }, "TorBoxResolver")

        worker.start()
        worker.join(RESOLVE_TIMEOUT_MS)
        if (worker.isAlive) {
            worker.interrupt()
            Log.e(TAG, "TorBox resolution timed out")
            return null
        }
        return result.get()
    }

    private fun resolveNetwork(apiKey: String, magnet: String): String {
        val torrentId = createTorrent(apiKey, magnet)
        val fileId = waitForPlayableFile(apiKey, torrentId)
        return requestDownloadLink(apiKey, torrentId, fileId)
    }

    private fun createTorrent(apiKey: String, magnet: String): Long {
        val boundary = "----mpvAndroidTorBox${System.currentTimeMillis()}"
        val connection = openConnection("$API_BASE/createtorrent", "POST", apiKey)
        connection.setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")
        connection.doOutput = true

        connection.outputStream.bufferedWriter(StandardCharsets.UTF_8).use { writer ->
            writer.append("--$boundary\r\n")
            writer.append("Content-Disposition: form-data; name=\"magnet\"\r\n\r\n")
            writer.append(magnet)
            writer.append("\r\n--$boundary--\r\n")
        }

        val json = readJson(connection)
        ensureSuccess(json)
        return findLong(json.opt("data"), "torrent_id", "id")
            ?: findLong(json, "torrent_id", "id")
            ?: throw IllegalStateException("TorBox did not return a torrent ID")
    }

    private fun waitForPlayableFile(apiKey: String, torrentId: Long): Long {
        var lastState = "unknown"
        repeat(15) {
            val connection = openConnection("$API_BASE/mylist?id=$torrentId&bypass_cache=true", "GET", apiKey)
            val json = readJson(connection)
            ensureSuccess(json)
            val torrent = findTorrentObject(json.opt("data"), torrentId)
            if (torrent != null) {
                lastState = torrent.optString("download_state", torrent.optString("status", "unknown"))
                chooseFile(torrent.optJSONArray("files"))?.let { return it }
            }
            Thread.sleep(2_000L)
        }
        throw IllegalStateException("TorBox torrent is not ready (state: $lastState)")
    }

    private fun chooseFile(files: JSONArray?): Long? {
        if (files == null || files.length() == 0)
            return null

        var bestVideoId: Long? = null
        var bestVideoSize = Long.MIN_VALUE
        var fallbackId: Long? = null
        var fallbackSize = Long.MIN_VALUE

        for (index in 0 until files.length()) {
            val file = files.optJSONObject(index) ?: continue
            val id = findLong(file, "id", "file_id") ?: continue
            val name = file.optString("name", file.optString("short_name", file.optString("path", "")))
            val size = findLong(file, "size", "bytes") ?: 0L

            if (size > fallbackSize) {
                fallbackSize = size
                fallbackId = id
            }

            val extension = name.substringAfterLast('.', "").lowercase()
            if (extension in videoExtensions && size > bestVideoSize) {
                bestVideoSize = size
                bestVideoId = id
            }
        }
        return bestVideoId ?: fallbackId
    }

    private fun requestDownloadLink(apiKey: String, torrentId: Long, fileId: Long): String {
        val encodedToken = URLEncoder.encode(apiKey, StandardCharsets.UTF_8.name())
        val url = "$API_BASE/requestdl?token=$encodedToken&torrent_id=$torrentId&file_id=$fileId&redirect=false"
        val connection = openConnection(url, "GET", null)
        val json = readJson(connection)
        ensureSuccess(json)
        return findString(json.opt("data"), "download_link", "url", "link")
            ?: findString(json, "download_link", "url", "link")
            ?: throw IllegalStateException("TorBox did not return a download URL")
    }

    private fun openConnection(url: String, method: String, apiKey: String?): HttpURLConnection {
        return (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = 15_000
            readTimeout = 30_000
            setRequestProperty("Accept", "application/json")
            setRequestProperty("User-Agent", "mpv-android-torbox/1.0")
            if (!apiKey.isNullOrBlank())
                setRequestProperty("Authorization", "Bearer $apiKey")
        }
    }

    private fun readJson(connection: HttpURLConnection): JSONObject {
        val status = connection.responseCode
        val stream = if (status in 200..299) connection.inputStream else connection.errorStream
        val body = stream?.let { input ->
            BufferedReader(InputStreamReader(input, StandardCharsets.UTF_8)).use { it.readText() }
        }.orEmpty()
        connection.disconnect()
        if (status !in 200..299)
            throw IllegalStateException("TorBox HTTP $status: $body")
        return JSONObject(body)
    }

    private fun ensureSuccess(json: JSONObject) {
        if (json.has("success") && !json.optBoolean("success")) {
            val detail = json.optString("detail", json.optString("error", "Unknown TorBox error"))
            throw IllegalStateException(detail)
        }
    }

    private fun findTorrentObject(value: Any?, torrentId: Long): JSONObject? = when (value) {
        is JSONObject -> {
            val currentId = findLong(value, "id", "torrent_id")
            if (currentId == torrentId || value.has("files")) value else null
        }
        is JSONArray -> {
            var match: JSONObject? = null
            for (index in 0 until value.length()) {
                val item = value.optJSONObject(index) ?: continue
                if (findLong(item, "id", "torrent_id") == torrentId) {
                    match = item
                    break
                }
            }
            match
        }
        else -> null
    }

    private fun findLong(value: Any?, vararg keys: String): Long? {
        if (value is Number)
            return value.toLong()
        if (value is String)
            return value.toLongOrNull()
        if (value !is JSONObject)
            return null
        for (key in keys) {
            if (!value.has(key)) continue
            val item = value.opt(key)
            when (item) {
                is Number -> return item.toLong()
                is String -> item.toLongOrNull()?.let { return it }
            }
        }
        return null
    }

    private fun findString(value: Any?, vararg keys: String): String? {
        if (value is String && value.startsWith("http"))
            return value
        if (value !is JSONObject)
            return null
        for (key in keys) {
            val candidate = value.optString(key, "")
            if (candidate.startsWith("http"))
                return candidate
        }
        return null
    }
}
