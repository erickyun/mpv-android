package `is`.xyz.mpv

import android.content.Context
import android.preference.PreferenceManager
import android.util.Log
import java.io.File
import java.io.IOException

internal object TorrServer {
    const val PREF_ENABLED = "torrserver_enabled"
    const val PREF_SERVER = "torrserver_server"
    const val DEFAULT_SERVER = "http://127.0.0.1:8090"

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
