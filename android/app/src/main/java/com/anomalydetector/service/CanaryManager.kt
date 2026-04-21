package com.anomalydetector.service

import android.content.Context
import android.os.Environment
import android.os.FileObserver
import android.util.Log
import com.anomalydetector.data.local.AppDatabase
import com.anomalydetector.data.model.BehaviorEvent
import com.google.gson.Gson
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import java.io.File
import java.io.FileOutputStream

/**
 * Deploys and monitors "honey files" (Canary Decoys).
 *
 * Deploys fake sensitive documents to an accessible directory and watches them.
 * Any system process or app interacting with these files triggers a critical
 * CANARY_FILE_ACCESS event (indicating potential ransomware or unauthorized access).
 */
class CanaryManager(
    private val context: Context,
    private val database: AppDatabase,
    private val gson: Gson = Gson(),
) {
    companion object {
        private const val TAG = "CanaryManager"

        private val CANARY_FILES = mapOf(
            "passwords_backup.txt" to "admin123\nroot_ssh_key=ssh-rsa AAA...\nbank_pin=4021",
            "bitcoin_wallet.dat" to "WALLET_SEED=1af3b51... DO NOT SHARE",
            "tax_return_2025.pdf" to "%PDF-1.4\n%Fake PDF content for bait purposes..."
        )
        
        // Debounce map to avoid flooding events for the same file in rapid succession
        private val lastAlertTimes = mutableMapOf<String, Long>()
    }

    private var directoryObserver: FileObserver? = null
    private var isWatching = false

    fun start() {
        if (isWatching) return

        val targetDir = context.getExternalFilesDir(Environment.DIRECTORY_DOCUMENTS)
        if (targetDir == null) {
            Log.e(TAG, "Cannot access external documents directory")
            return
        }

        if (!targetDir.exists()) {
            targetDir.mkdirs()
        }

        // Deploy the canary files
        deployCanaries(targetDir)

        // Setup FileObserver to watch the directory
        // Watch for access, modify, delete
        val flags = FileObserver.ACCESS or FileObserver.MODIFY or FileObserver.DELETE or FileObserver.MOVED_FROM
        
        // Use the deprecated constructor to maintain compatibility with older Android versions
        @Suppress("DEPRECATION")
        directoryObserver = object : FileObserver(targetDir.absolutePath, flags) {
            override fun onEvent(event: Int, path: String?) {
                if (path == null) return
                
                // Only react if the affected file is one of our canaries
                if (CANARY_FILES.containsKey(path)) {
                    val eventTypeStr = when {
                        (event and FileObserver.MODIFY) != 0 -> "MODIFY"
                        (event and FileObserver.DELETE) != 0 -> "DELETE"
                        (event and FileObserver.ACCESS) != 0 -> "ACCESS"
                        (event and FileObserver.MOVED_FROM) != 0 -> "MOVED"
                        else -> "UNKNOWN"
                    }
                    
                    handleCanaryEvent(path, eventTypeStr)
                }
            }
        }
        
        directoryObserver?.startWatching()
        isWatching = true
        Log.i(TAG, "Canary files deployed and actively monitored at ${targetDir.absolutePath}")
    }

    fun stop() {
        directoryObserver?.stopWatching()
        isWatching = false
        Log.i(TAG, "Canary monitoring stopped")
    }

    private fun deployCanaries(targetDir: File) {
        for ((fileName, content) in CANARY_FILES) {
            try {
                val file = File(targetDir, fileName)
                if (!file.exists()) {
                    FileOutputStream(file).use { fos ->
                        fos.write(content.toByteArray())
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "Failed to deploy canary $fileName: ${e.message}")
            }
        }
    }

    private fun handleCanaryEvent(fileName: String, action: String) {
        val now = System.currentTimeMillis()
        val lastAlert = lastAlertTimes[fileName] ?: 0L
        
        // Debounce: 5 seconds per file
        if (now - lastAlert < 5000L) {
            return
        }
        lastAlertTimes[fileName] = now

        Log.w(TAG, "⚠ CANARY TRIGGERED: File $fileName experienced $action")

        CoroutineScope(Dispatchers.IO).launch {
            database.behaviorEventDao().insert(
                BehaviorEvent(
                    eventType = "CANARY_FILE_ACCESS",
                    packageName = "system_level", // Since FileObserver doesn't tell us who accessed it easily
                    timestamp = now,
                    data = gson.toJson(
                        mapOf(
                            "fileName" to fileName,
                            "action" to action,
                            "urgency" to "CRITICAL"
                        )
                    )
                )
            )
        }
    }
}
