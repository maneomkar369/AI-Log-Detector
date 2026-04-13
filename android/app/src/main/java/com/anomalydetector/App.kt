package com.anomalydetector

import android.app.Application
import dagger.hilt.android.HiltAndroidApp

/**
 * Application class — initializes Hilt dependency injection.
 */
@HiltAndroidApp
class App : Application() {
    override fun onCreate() {
        super.onCreate()
        // Additional initialization (logging, crash reporting) goes here
    }
}
