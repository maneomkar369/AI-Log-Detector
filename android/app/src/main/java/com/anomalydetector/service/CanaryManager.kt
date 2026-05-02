package com.anomalydetector.service

import android.content.Context
import android.content.SharedPreferences
import android.os.Environment
import android.os.FileObserver
import android.util.Log
import com.anomalydetector.data.local.AppDatabase
import com.anomalydetector.data.model.BehaviorEvent
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import java.io.File
import java.io.FileOutputStream
import kotlin.random.Random

/**
 * Deploys and monitors stealthy "honey files" (Canary Decoys).
 *
 * Flaw #4 Fix: Uses randomized filenames from innocuous patterns and
 * monitors entire directories instead of specific tempting filenames.
 * This prevents smart malware from identifying and avoiding canaries.
 *
 * Enhancements:
 *   - Random filenames from large pool (cache_XXXXX.tmp, temp_XXXX.log, etc.)
 *   - Content with realistic entropy (not obviously fake)
 *   - Directory-level honeypots that no normal app should access
 *   - Persists canary registry in SharedPreferences across restarts
 */
class CanaryManager(
    private val context: Context,
    private val database: AppDatabase,
    private val gson: Gson = Gson(),
) {
    companion object {
        private const val TAG = "CanaryManager"
        private const val PREFS_NAME = "canary_registry"
        private const val PREFS_KEY_FILES = "deployed_files"
        private const val CANARY_COUNT = 5

        // Innocuous filename patterns that won't arouse suspicion
        private val FILENAME_PATTERNS = listOf(
            { "cache_${Random.nextInt(10000, 99999)}.tmp" },
            { "temp_${Random.nextInt(1000, 9999)}.log" },
            { ".thumb_${Random.nextInt(10000, 99999)}.dat" },
            { "backup_${Random.nextInt(100, 999)}.bak" },
            { ".sync_${Random.nextInt(10000, 99999)}.db" },
            { "index_${Random.nextInt(1000, 9999)}.cache" },
            { ".metadata_${Random.nextInt(100, 999)}.bin" },
            { "session_${Random.nextInt(10000, 99999)}.tmp" },
        )

        // Debounce map to avoid flooding events for the same file
        private val lastAlertTimes = mutableMapOf<String, Long>()
    }

    private val observers = mutableListOf<FileObserver>()
    private var isWatching = false
    private lateinit var prefs: SharedPreferences
    private var deployedFiles = mutableSetOf<String>()

    fun start() {
        if (isWatching) return

        prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        loadDeployedFiles()

        // Primary canary directory
        val primaryDir = context.getExternalFilesDir(Environment.DIRECTORY_DOCUMENTS)
        if (primaryDir != null) {
            if (!primaryDir.exists()) primaryDir.mkdirs()
            deployCanaries(primaryDir)
            watchDirectory(primaryDir)
        }

        // Directory-level honeypots — directories no normal app should access
        val honeypotDirs = listOf(
            File(context.getExternalFilesDir(null), ".private_data"),
            File(context.getExternalFilesDir(null), ".system_backup"),
        )

        for (dir in honeypotDirs) {
            try {
                if (!dir.exists()) dir.mkdirs()
                // Deploy a single canary in each honeypot dir
                deploySingleCanary(dir)
                watchDirectory(dir)
                Log.i(TAG, "Honeypot directory monitored: ${dir.absolutePath}")
            } catch (e: Exception) {
                Log.w(TAG, "Failed to setup honeypot dir ${dir.absolutePath}: ${e.message}")
            }
        }

        isWatching = true
        Log.i(TAG, "Canary system active — ${deployedFiles.size} files across ${observers.size} directories")
    }

    fun stop() {
        observers.forEach { it.stopWatching() }
        observers.clear()
        isWatching = false
        Log.i(TAG, "Canary monitoring stopped")
    }

    /**
     * Watch an entire directory for ACCESS/OPEN events.
     * Any file interaction in monitored directories triggers analysis.
     */
    private fun watchDirectory(dir: File) {
        val flags = FileObserver.ACCESS or FileObserver.MODIFY or
                FileObserver.DELETE or FileObserver.MOVED_FROM or FileObserver.OPEN

        @Suppress("DEPRECATION")
        val observer = object : FileObserver(dir.absolutePath, flags) {
            override fun onEvent(event: Int, path: String?) {
                if (path == null) return

                // Check if the accessed file is one of our deployed canaries
                val fullPath = "${dir.absolutePath}/$path"
                if (isCanaryFile(path) || isCanaryFile(fullPath)) {
                    val eventTypeStr = when {
                        (event and MODIFY) != 0 -> "MODIFY"
                        (event and DELETE) != 0 -> "DELETE"
                        (event and ACCESS) != 0 -> "ACCESS"
                        (event and OPEN) != 0 -> "OPEN"
                        (event and MOVED_FROM) != 0 -> "MOVED"
                        else -> "UNKNOWN"
                    }
                    handleCanaryEvent(path, eventTypeStr, dir.absolutePath)
                }
            }
        }

        observer.startWatching()
        observers.add(observer)
    }

    /**
     * Deploy canary files with randomized names and realistic content.
     */
    private fun deployCanaries(targetDir: File) {
        // If we already have deployed files in this dir, skip
        val existingInDir = deployedFiles.count { it.startsWith(targetDir.absolutePath) }
        if (existingInDir >= CANARY_COUNT) return

        val needed = CANARY_COUNT - existingInDir
        for (i in 0 until needed) {
            deploySingleCanary(targetDir)
        }
    }

    private fun deploySingleCanary(targetDir: File) {
        val pattern = FILENAME_PATTERNS[Random.nextInt(FILENAME_PATTERNS.size)]
        val fileName = pattern()

        try {
            val file = File(targetDir, fileName)
            if (!file.exists()) {
                FileOutputStream(file).use { fos ->
                    fos.write(generateRealisticContent().toByteArray())
                }
                val fullPath = file.absolutePath
                deployedFiles.add(fullPath)
                saveDeployedFiles()
                Log.d(TAG, "Deployed canary: $fullPath")
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to deploy canary $fileName: ${e.message}")
        }
    }

    /**
     * Generate content with realistic entropy — not obviously fake
     * but also not containing actual sensitive data.
     */
    private fun generateRealisticContent(): String {
        val templates = listOf(
            // Binary-looking cache data
            { buildString {
                repeat(Random.nextInt(256, 1024)) {
                    append(Random.nextInt(33, 127).toChar())
                }
            }},
            // Log-like content
            { buildString {
                repeat(Random.nextInt(10, 30)) {
                    val ts = System.currentTimeMillis() - Random.nextLong(86400000)
                    append("$ts INFO Process ${Random.nextInt(1000, 9999)} state=${Random.nextInt(0, 5)}\n")
                }
            }},
            // Config-like content
            { buildString {
                val keys = listOf("cache_size", "ttl", "max_retry", "buffer", "timeout", "interval")
                for (key in keys) {
                    append("$key=${Random.nextInt(1, 10000)}\n")
                }
            }},
        )

        return templates[Random.nextInt(templates.size)]()
    }

    private fun isCanaryFile(path: String): Boolean {
        return deployedFiles.any { it.endsWith("/$path") || it == path }
    }

    private fun handleCanaryEvent(fileName: String, action: String, dirPath: String) {
        val now = System.currentTimeMillis()
        val key = "$dirPath/$fileName"
        val lastAlert = lastAlertTimes[key] ?: 0L

        // Debounce: 5 seconds per file
        if (now - lastAlert < 5000L) return
        lastAlertTimes[key] = now

        Log.w(TAG, "⚠ CANARY TRIGGERED: $key experienced $action")

        CoroutineScope(Dispatchers.IO).launch {
            database.behaviorEventDao().insert(
                BehaviorEvent(
                    eventType = "CANARY_FILE_ACCESS",
                    packageName = "system_level",
                    timestamp = now,
                    data = gson.toJson(
                        mapOf(
                            "fileName" to fileName,
                            "directory" to dirPath,
                            "action" to action,
                            "urgency" to "CRITICAL"
                        )
                    )
                )
            )
        }
    }

    private fun loadDeployedFiles() {
        val json = prefs.getString(PREFS_KEY_FILES, null) ?: return
        try {
            val type = object : TypeToken<Set<String>>() {}.type
            val loaded: Set<String> = gson.fromJson(json, type)
            deployedFiles = loaded.toMutableSet()
            // Prune files that no longer exist on disk
            deployedFiles.removeAll { !File(it).exists() }
            Log.d(TAG, "Loaded ${deployedFiles.size} canary files from registry")
        } catch (e: Exception) {
            Log.w(TAG, "Failed to load canary registry: ${e.message}")
            deployedFiles = mutableSetOf()
        }
    }

    private fun saveDeployedFiles() {
        prefs.edit()
            .putString(PREFS_KEY_FILES, gson.toJson(deployedFiles))
            .apply()
    }
}
