package com.anomalydetector.ui

import android.os.Bundle
import android.widget.TextView
import androidx.activity.viewModels
import androidx.appcompat.app.AppCompatActivity
import com.anomalydetector.R

class MainActivity : AppCompatActivity() {

    private val viewModel: MainViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        val connectionValue = findViewById<TextView>(R.id.connectionValue)
        val syncValue = findViewById<TextView>(R.id.syncValue)

        viewModel.connectionStatus.observe(this) { connectionValue.text = it }
        viewModel.lastSyncTime.observe(this) { syncValue.text = it }
    }
}
