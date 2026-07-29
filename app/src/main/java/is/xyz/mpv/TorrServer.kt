package `is`.xyz.mpv

import android.content.Context
import android.preference.PreferenceManager
import android.util.Log
import java.io.File
import java.io.IOException
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

internal object TorrServer {
    const val PREF_ENABLED = "torrserver_enabled"
    const val PREF_SERVER = "torrserver_server"
    const val DEFAULT_SERVER = "http://127.0.0.1:8090"

    fun resolve(context: Context, source: String): String {
        val lower = source.lowercase()
        val isTorrent = lower.startsWith("magnet:") ||
                lower.startsWith("torrs://") ||
                ((lower.startsWith("http://") || lower.startsWith("https://")) &&
                        Regex("\\.torrent([?#].*)?$").containsMatchIn(lower))
        if (!isTorrent)
            return source

        // TorBox is the preferred provider when it is enabled and configured.
        // Returning null means TorBox is disabled, unavailable, or unsupported,
        // so the existing TorrServer path remains a transparent fallback.
        TorBox.resolve(context, source)?.let { resolved ->
            Log.i(TAG, "Routing torrent through TorBox")
            return resolved
        }

        val preferences = PreferenceManager.getDefaultSharedPreferences(context)
        if (!preferences.getBoolean(PREF_ENABLED, true))
            return source

        val configuredServer = preferences.getString(PREF_SERVER, DEFAULT_SERVER)
            ?.trim()
            ?.replace("\r", "")
            ?.replace("\n", "")
            .orEmpty()
        val server = configuredServer.ifBlank { DEFAULT_SERVER }.trimEnd('/')
        val encoded = URLEncoder.encode(source, StandardCharsets.UTF_8.name())
        val resolved = "$server/stream/torrent.m3u?link=$encoded&m3u"
        Log.i(TAG, "Routing torrent through TorrServer: $resolved")
        return resolved
    }

    fun install(context: Context, configDir: String) {
        try {
            val scriptsDir = File(configDir, "scripts").apply { mkdirs() }
            val scriptFile = File(scriptsDir, "torrserver.lua")
            context.assets.open("scripts/torrserver.lua").use { input ->
                scriptFile.outputStream().use { output -> input.copyTo(output) }
            }

            val preferences = PreferenceManager.getDefaultSharedPreferences(context)
            val enabled = preferences.getBoolean(PREF_ENABLED, true)
            val configuredServer = preferences.getString(PREF_SERVER, DEFAULT_SERVER)
                ?.trim()
                ?.replace("\r", "")
                ?.replace("\n", "")
                .orEmpty()
            val server = configuredServer.ifBlank { DEFAULT_SERVER }

            val scriptOptsDir = File(configDir, "script-opts").apply { mkdirs() }
            File(scriptOptsDir, "torrserver.conf").writeText(
                "enabled=${if (enabled) "yes" else "no"}\n" +
                "server=$server\n"
            )
        } catch (e: IOException) {
            Log.e(TAG, "Failed to install TorrServer integration", e)
        }
    }

    private const val TAG = "mpv"
}
