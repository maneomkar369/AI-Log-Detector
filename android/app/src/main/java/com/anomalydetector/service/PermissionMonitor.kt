package com.anomalydetector.service

import android.app.AppOpsManager
import android.app.Notification
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.os.Build
import android.util.Log
import androidx.core.app.NotificationCompat
import com.anomalydetector.Config
import com.anomalydetector.data.local.AppDatabase
import com.anomalydetector.data.model.BehaviorEvent
import com.anomalydetector.ui.MainActivity
import com.google.gson.Gson

/**
 * Monitors runtime permission usage (camera, microphone, location)
 * by third-party apps using AppOpsManager.
 *
 * When a side-loaded or third-party app accesses a sensitive permission,
 * a PERMISSION_ACCESS event is generated and (for side-loaded apps) an
 * immediate local notification is shown.
 */
class PermissionMonitor(
    private val context: Context,
    private val database: AppDatabase,
    private val gson: Gson = Gson(),
) {
    companion object {
        private const val TAG = "PermissionMonitor"

        // Tracked sensitive operations
        private val TRACKED_OPS = listOf(
            AppOpsManager.OPSTR_CAMERA to "CAMERA",
            AppOpsManager.OPSTR_RECORD_AUDIO to "RECORD_AUDIO",
            AppOpsManager.OPSTR_FINE_LOCATION to "FINE_LOCATION",
            AppOpsManager.OPSTR_COARSE_LOCATION to "COARSE_LOCATION",
        )

        // Known Play Store installer package names
        private val PLAY_STORE_INSTALLERS = setOf(
            "com.android.vending",       // Google Play Store
            "com.google.android.packageinstaller",
        )

        // System-level packages to skip
        private val SYSTEM_PACKAGE_PREFIXES = listOf(
            "com.android.",
            "com.google.android.",
            "com.samsung.",
            "com.sec.",
            "com.qualcomm.",
            "com.mediatek.",
            "android",
        )
    }

    /**
     * Map of (packageName:opName) -> last known usage timestamp.
     * Used to detect new usages since the last poll.
     */
    private val lastSeenUsage = mutableMapOf<String, Long>()

    /**
     * Check all installed packages for recent permission usage.
     * Call this periodically from the monitoring loop.
     */
    suspend fun checkPermissionUsage() {
        try {
            val appOpsManager = context.getSystemService(Context.APP_OPS_SERVICE) as? AppOpsManager
                ?: return

            val pm = context.packageManager
            val installedPackages = pm.getInstalledApplications(PackageManager.GET_META_DATA)

            for (appInfo in installedPackages) {
                // Skip system apps
                if (isSystemApp(appInfo)) continue

                for ((opStr, permName) in TRACKED_OPS) {
                    checkAppOp(appOpsManager, appInfo, opStr, permName)
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Error checking permission usage: ${e.message}")
        }
    }

    private suspend fun checkAppOp(
        appOpsManager: AppOpsManager,
        appInfo: ApplicationInfo,
        opStr: String,
        permName: String,
    ) {
        try {
            val mode = appOpsManager.unsafeCheckOpNoThrow(
                opStr, appInfo.uid, appInfo.packageName
            )

            // Only interested in ops that are allowed
            if (mode != AppOpsManager.MODE_ALLOWED) return

            // Try to get the last usage timestamp
            // On Android Q+, we can check if the op is currently active
            val now = System.currentTimeMillis()
            val cacheKey = "${appInfo.packageName}:$permName"

            // Check if the op is running (active right now)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                val isRunning = try {
                    appOpsManager.unsafeCheckOpNoThrow(opStr, appInfo.uid, appInfo.packageName) ==
                        AppOpsManager.MODE_ALLOWED &&
                        isOpActive(appOpsManager, opStr, appInfo.uid, appInfo.packageName)
                } catch (_: Exception) {
                    false
                }

                if (!isRunning) return

                val lastSeen = lastSeenUsage[cacheKey] ?: 0L

                // Debounce: don't re-alert within 30 seconds
                if (now - lastSeen < 30_000L) return

                lastSeenUsage[cacheKey] = now

                val isSideLoaded = isSideLoadedApp(appInfo)
                val installerPackage = getInstallerPackage(appInfo)

                Log.i(TAG, "Permission access detected: ${appInfo.packageName} -> $permName " +
                    "(sideLoaded=$isSideLoaded, installer=$installerPackage)")

                // Persist event
                database.behaviorEventDao().insert(
                    BehaviorEvent(
                        eventType = "PERMISSION_ACCESS",
                        packageName = appInfo.packageName,
                        timestamp = now,
                        data = gson.toJson(mapOf(
                            "permission" to permName,
                            "packageName" to appInfo.packageName,
                            "isSideLoaded" to isSideLoaded,
                            "installerPackage" to (installerPackage ?: "unknown"),
                            "uid" to appInfo.uid,
                        ))
                    )
                )

                // Show immediate local notification for side-loaded apps
                if (isSideLoaded && permName in listOf("CAMERA", "RECORD_AUDIO")) {
                    showPermissionWarning(appInfo.packageName, permName)
                }
            }
        } catch (e: SecurityException) {
            // Some ops may not be accessible — skip silently
        } catch (e: Exception) {
            Log.w(TAG, "Error checking op $opStr for ${appInfo.packageName}: ${e.message}")
        }
    }

    /**
     * Checks if an AppOps operation is currently active (running) for a given app.
     */
    private fun isOpActive(
        appOpsManager: AppOpsManager,
        opStr: String,
        uid: Int,
        packageName: String,
    ): Boolean {
        return try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                appOpsManager.isOpActive(opStr, uid, packageName)
            } else {
                // On Q, we can't directly check isOpActive for all ops;
                // fall back to checking the note/start behavior
                appOpsManager.unsafeCheckOpNoThrow(opStr, uid, packageName) ==
                    AppOpsManager.MODE_ALLOWED
            }
        } catch (_: Exception) {
            false
        }
    }

    /**
     * Determine if an app is system-level (pre-installed).
     */
    private fun isSystemApp(appInfo: ApplicationInfo): Boolean {
        if (appInfo.flags and ApplicationInfo.FLAG_SYSTEM != 0) return true
        if (appInfo.flags and ApplicationInfo.FLAG_UPDATED_SYSTEM_APP != 0) return true

        val pkg = appInfo.packageName.lowercase()
        return SYSTEM_PACKAGE_PREFIXES.any { pkg.startsWith(it) }
    }

    /**
     * Determine if an app was side-loaded (not installed from Play Store).
     */
    private fun isSideLoadedApp(appInfo: ApplicationInfo): Boolean {
        val installer = getInstallerPackage(appInfo)
        if (installer == null || installer.isBlank()) return true
        return installer !in PLAY_STORE_INSTALLERS
    }

    /**
     * Get the installer package name for an app.
     */
    private fun getInstallerPackage(appInfo: ApplicationInfo): String? {
        return try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                context.packageManager.getInstallSourceInfo(appInfo.packageName)
                    .installingPackageName
            } else {
                @Suppress("DEPRECATION")
                context.packageManager.getInstallerPackageName(appInfo.packageName)
            }
        } catch (_: Exception) {
            null
        }
    }

    /**
     * Show an immediate notification warning the user about a
     * side-loaded app accessing a sensitive permission.
     */
    private fun showPermissionWarning(packageName: String, permission: String) {
        val permLabel = permission.lowercase().replace("_", " ")
        val appLabel = try {
            context.packageManager.getApplicationLabel(
                context.packageManager.getApplicationInfo(packageName, 0)
            ).toString()
        } catch (_: Exception) {
            packageName
        }

        val notification = NotificationCompat.Builder(context, Config.CHANNEL_ALERTS)
            .setSmallIcon(android.R.drawable.ic_dialog_alert)
            .setContentTitle("⚠ Permission Alert")
            .setContentText("'$appLabel' is accessing $permLabel")
            .setStyle(NotificationCompat.BigTextStyle().bigText(
                "Side-loaded app '$appLabel' ($packageName) is currently accessing " +
                "$permLabel. This may pose a security risk if you did not initiate this action."
            ))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            .setContentIntent(PendingIntent.getActivity(
                context, 0,
                Intent(context, MainActivity::class.java),
                PendingIntent.FLAG_IMMUTABLE
            ))
            .build()

        val nm = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        // Use unique notification ID based on package + permission
        val notifId = (packageName + permission).hashCode()
        nm.notify(notifId, notification)
    }
}
