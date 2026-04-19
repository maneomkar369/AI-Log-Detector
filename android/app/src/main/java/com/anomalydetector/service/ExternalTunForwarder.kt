package com.anomalydetector.service

import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/**
 * Runs an external TUN forwarder process (e.g., tun2socks).
 */
class ExternalTunForwarder {

    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private var process: Process? = null
    private var stdoutJob: Job? = null

    fun start(commandTemplate: String, tunFd: Int): Boolean {
        if (process != null) return true

        val commandString = commandTemplate.replace("%TUN_FD%", tunFd.toString())
        val command = commandString
            .trim()
            .split(Regex("\\s+"))
            .filter { it.isNotBlank() }

        if (command.isEmpty()) {
            Log.e(TAG, "Forwarder command is empty")
            return false
        }

        return try {
            val proc = ProcessBuilder(command)
                .redirectErrorStream(true)
                .start()
            process = proc

            stdoutJob = scope.launch {
                proc.inputStream.bufferedReader().useLines { lines ->
                    lines.forEach { line ->
                        Log.i(TAG, "forwarder: $line")
                    }
                }
            }

            Log.i(TAG, "Forwarder started: $commandString")
            true
        } catch (e: Exception) {
            Log.e(TAG, "Failed to start forwarder: ${e.message}")
            stop()
            false
        }
    }

    fun isAlive(): Boolean = process?.isAlive == true

    fun stop() {
        try {
            process?.destroy()
        } catch (_: Exception) {
        }
        process = null

        stdoutJob?.cancel()
        stdoutJob = null
    }

    fun shutdown() {
        stop()
        scope.cancel()
    }

    companion object {
        private const val TAG = "ExternalTunForwarder"
    }
}
