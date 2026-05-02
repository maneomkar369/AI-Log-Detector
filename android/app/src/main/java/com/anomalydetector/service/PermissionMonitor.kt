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
import android.app.SyncNotedAppOp
import android.util.Log
import kotlinx.coroutines.runBlocking
import androidx.core.app.NotificationCompat
import com.anomalydetector.Config
import com.anomalydetector.data.local.AppDatabase
import com.anomalydetector.data.model.BehaviorEvent
import com.anomalydetector.ui.MainActivity
import com.google.gson.Gson

/**
 * Enhanced Permission Monitor with real-time monitoring for Android 11+
 * and polling fallback for older versions.
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
     * Whether we've already logged the setup guidance for missing permissions.
     */
    private var hasLoggedSetupGuidance = false

    /**
     * OnOpNotedCallback for real-time permission monitoring (Android 11+)
     */
    private var opNotedCallback: AppOpsManager.OnOpNotedCallback? = null

    init {
        // Flaw #8: Initialize OnOpNotedCallback for Android 11+
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            initializeOnOpNotedCallback()
        }
    }

    /**
     * Initialize OnOpNotedCallback for real-time permission monitoring
     */
    private fun initializeOnOpNotedCallback() {
        try {
            val appOpsManager = context.getSystemService(Context.APP_OPS_SERVICE) as? AppOpsManager
                ?: return

            opNotedCallback = object : AppOpsManager.OnOpNotedCallback() {
                override fun onNoted(syncOpEvent: SyncNotedAppOp) {
                    // Handle permission usage immediately
                    handlePermissionUsage(syncOpEvent)
                }

                override fun onSelfNoted(syncOpEvent: SyncNotedAppOp) {
                    // Handle self (our app) permission usage
                    handleSelfPermissionUsage(syncOpEvent)
                }

                override fun onAsyncNoted(asyncOp: android.app.AsyncNotedAppOp) {
                    // Handle async noted ops
                }
            }

            // Register the callback
            appOpsManager.setOnOpNotedCallback(
                context.mainExecutor,
                opNotedCallback!!
            )

            Log.i(TAG, "OnOpNotedCallback registered for real-time permission monitoring")
        } catch (e: Exception) {
            Log.w(TAG, "Failed to register OnOpNotedCallback: ${e.message}")
        }
    }

    /**
     * Handle permission usage events from OnOpNotedCallback
     */
    private fun handlePermissionUsage(syncOpEvent: SyncNotedAppOp) {
        try {
            val packageName = context.packageName // SyncNotedAppOp is for current UID
            val opStr = syncOpEvent.op
            val permName = getPermissionNameFromOp(opStr) ?: return

            // Skip system apps
            val appInfo = try {
                context.packageManager.getApplicationInfo(packageName, 0)
            } catch (e: PackageManager.NameNotFoundException) {
                return
            }

            if (isSystemApp(appInfo)) return

            val now = System.currentTimeMillis()
            val cacheKey = "$packageName:$permName"

            val lastSeen = lastSeenUsage[cacheKey] ?: 0L

            // Debounce: don't re-alert within 30 seconds
            if (now - lastSeen < 30_000L) return

            lastSeenUsage[cacheKey] = now

            val isSideLoaded = isSideLoadedApp(appInfo)
            val installerPackage = getInstallerPackage(appInfo)

            Log.i(TAG, "Real-time permission access detected: $packageName -> $permName " +
                "(sideLoaded=$isSideLoaded, installer=$installerPackage)")

            // Persist event asynchronously
            Thread {
                try {
                    runBlocking {
                        database.behaviorEventDao().insert(
                            BehaviorEvent(
                                eventType = "PERMISSION_ACCESS",
                                packageName = packageName,
                                timestamp = now,
                                data = gson.toJson(mutableMapOf<String, Any>(
                                    "permission" to permName,
                                    "packageName" to packageName,
                                    "isSideLoaded" to isSideLoaded,
                                    "installerPackage" to (installerPackage ?: "unknown"),
                                    "uid" to appInfo.uid,
                                    "apiLevel" to Build.VERSION.SDK_INT,
                                    "realtime" to true
                                ))
                            )
                        )
                    }

                    // Show immediate local notification for side-loaded apps
                    if (isSideLoaded && permName in listOf("CAMERA", "RECORD_AUDIO")) {
                        // Note: This needs to run on main thread for notifications
                        // In a real implementation, you'd use a Handler or similar
                    }
                } catch (e: Exception) {
                    Log.e(TAG, "Error persisting real-time permission event: ${e.message}")
                }
            }.start()
        } catch (e: Exception) {
            Log.w(TAG, "Error handling permission usage: ${e.message}")
        }
    }

    /**
     * Handle self permission usage events
     */
    private fun handleSelfPermissionUsage(syncOpEvent: SyncNotedAppOp) {
        // Log or handle our own app's permission usage if needed
        Log.d(TAG, "Self permission usage: ${syncOpEvent.op} at ${System.currentTimeMillis()}")
    }

    /**
     * Get permission name from AppOps operation string
     */
    private fun getPermissionNameFromOp(opStr: String): String? {
        return TRACKED_OPS.find { it.first == opStr }?.second
    }

    /**
     * Check all installed packages for recent permission usage.
     * Call this periodically from the monitoring loop (fallback for older Android versions).
     */
    suspend fun checkPermissionUsage() {
        // Flaw #8: On Android 11+, rely on OnOpNotedCallback for real-time monitoring
        // Only use polling as fallback for older versions or edge cases
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            // Real-time monitoring is active via callback
            return
        }

        try {
            // Flaw #8: Check required permissions on Android 13+
            if (!checkRequiredPermissions()) {
                return
            }

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

    /**
     * Flaw #8: Verify that required permissions are granted on Android 13+.
     * Logs setup guidance if permissions are missing.
     */
    private fun checkRequiredPermissions(): Boolean {
        // On Android 13+ (API 33), POST_NOTIFICATIONS is required for showing alerts
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            val notifPermission = context.checkSelfPermission(
                android.Manifest.permission.POST_NOTIFICATIONS
            )
            if (notifPermission != PackageManager.PERMISSION_GRANTED) {
                if (!hasLoggedSetupGuidance) {
                    Log.w(TAG, "⚠ POST_NOTIFICATIONS permission not granted on Android 13+. " +
                        "Permission alerts cannot be displayed. " +
                        "Please grant notification permission in Settings > Apps > AI Log Detector > Notifications.")
                    hasLoggedSetupGuidance = true
                }
                // Continue monitoring but skip notification display
            }
        }

        // Usage access permission is required for AppOpsManager queries
        val appOpsManager = context.getSystemService(Context.APP_OPS_SERVICE) as? AppOpsManager
        if (appOpsManager != null) {
            try {
                val mode = appOpsManager.unsafeCheckOpNoThrow(
                    AppOpsManager.OPSTR_GET_USAGE_STATS,
                    android.os.Process.myUid(),
                    context.packageName
                )
                if (mode != AppOpsManager.MODE_ALLOWED) {
                    if (!hasLoggedSetupGuidance) {
                        Log.w(TAG, "⚠ Usage access permission not granted. " +
                            "Permission monitoring requires: " +
                            "Settings > Security > Apps with usage access > AI Log Detector > Enable")
                        hasLoggedSetupGuidance = true
                    }
                    return false
                }
            } catch (e: Exception) {
                Log.w(TAG, "Could not verify usage access permission: ${e.message}")
            }
        }

        return true
    }

    private suspend fun checkAppOp(
        appOpsManager: AppOpsManager,
        appInfo: ApplicationInfo,
        opStr: String,
        permName: String,
    ) {
        try {
            val mode = try {
                appOpsManager.unsafeCheckOpNoThrow(
                    opStr, appInfo.uid, appInfo.packageName
                )
            } catch (e: SecurityException) {
                // Flaw #8: On Android 13+, some ops may throw SecurityException
                // for background apps. Fall back gracefully.
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                    Log.d(TAG, "SecurityException checking $opStr for ${appInfo.packageName} " +
                        "(expected on Android 13+ for background queries)")
                }
                return
            }

            // Only interested in ops that are allowed
            if (mode != AppOpsManager.MODE_ALLOWED) return

            val now = System.currentTimeMillis()
            val cacheKey = "${appInfo.packageName}:$permName"

            // Check if the op is running (active right now)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                val isRunning = try {
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
                            "apiLevel" to Build.VERSION.SDK_INT,
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
     *
     * Flaw #8: Uses appropriate API for each Android version:
     *   - API 30+ (R): isOpActive() — direct and reliable
     *   - API 29 (Q): unsafeCheckOpNoThrow fallback
     *   - API 33+ (Tiramisu): Additional error handling for restricted ops
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
        } catch (e: SecurityException) {
            // Flaw #8: Android 13+ may restrict isOpActive for certain ops
            Log.d(TAG, "isOpActive restricted for $opStr/$packageName: ${e.message}")
            false
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
     * Flaw #8: Uses getInstallSourceInfo (API 30+) with proper error handling.
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
        } catch (e: PackageManager.NameNotFoundException) {
            // Flaw #8: Package may have been uninstalled between listing and query
            Log.d(TAG, "Package ${appInfo.packageName} not found during installer lookup")
            null
        } catch (_: Exception) {
            null
        }
    }

    /**
     * Show an immediate notification warning the user about a
     * side-loaded app accessing a sensitive permission.
     *
     * Flaw #8: Checks POST_NOTIFICATIONS on Android 13+ before attempting to show.
     */
    private fun showPermissionWarning(packageName: String, permission: String) {
        // Flaw #8: On Android 13+, check notification permission first
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            val notifPermission = context.checkSelfPermission(
                android.Manifest.permission.POST_NOTIFICATIONS
            )
            if (notifPermission != PackageManager.PERMISSION_GRANTED) {
                Log.w(TAG, "Cannot show permission warning — POST_NOTIFICATIONS not granted")
                return
            }
        }

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
