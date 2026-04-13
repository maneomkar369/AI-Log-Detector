package com.anomalydetector.ui

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.TextView
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.ListAdapter
import androidx.recyclerview.widget.RecyclerView
import com.anomalydetector.R
import com.anomalydetector.data.model.Alert
import java.text.SimpleDateFormat
import java.util.*

/**
 * RecyclerView adapter for displaying alerts with severity color coding
 * and approve/deny action buttons.
 */
class AlertAdapter(
    private val onApprove: (Alert) -> Unit,
    private val onDeny: (Alert) -> Unit,
) : ListAdapter<Alert, AlertAdapter.ViewHolder>(DIFF) {

    class ViewHolder(view: View) : RecyclerView.ViewHolder(view) {
        val textSeverity: TextView = view.findViewById(R.id.textSeverity)
        val textThreatType: TextView = view.findViewById(R.id.textThreatType)
        val textMessage: TextView = view.findViewById(R.id.textMessage)
        val textConfidence: TextView = view.findViewById(R.id.textConfidence)
        val textTime: TextView = view.findViewById(R.id.textTime)
        val textStatus: TextView = view.findViewById(R.id.textStatus)
        val btnApprove: Button = view.findViewById(R.id.btnApprove)
        val btnDeny: Button = view.findViewById(R.id.btnDeny)
        val severityBar: View = view.findViewById(R.id.severityBar)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_alert, parent, false)
        return ViewHolder(view)
    }

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        val alert = getItem(position)
        val ctx = holder.itemView.context

        holder.textSeverity.text = "Severity ${alert.severity}/10"
        holder.textThreatType.text = alert.threatType
        holder.textMessage.text = alert.message
        holder.textConfidence.text = "Confidence: ${(alert.confidence * 100).toInt()}%"
        holder.textTime.text = SimpleDateFormat("HH:mm:ss", Locale.getDefault())
            .format(Date(alert.receivedAt))
        holder.textStatus.text = alert.status.uppercase()

        // Severity color
        val color = when {
            alert.severity >= 9 -> android.graphics.Color.parseColor("#EF4444")
            alert.severity >= 7 -> android.graphics.Color.parseColor("#F97316")
            alert.severity >= 4 -> android.graphics.Color.parseColor("#F59E0B")
            else -> android.graphics.Color.parseColor("#10B981")
        }
        holder.severityBar.setBackgroundColor(color)
        holder.textSeverity.setTextColor(color)

        // Show/hide action buttons based on status
        val isPending = alert.status == "pending"
        holder.btnApprove.visibility = if (isPending) View.VISIBLE else View.GONE
        holder.btnDeny.visibility = if (isPending) View.VISIBLE else View.GONE

        holder.btnApprove.setOnClickListener { onApprove(alert) }
        holder.btnDeny.setOnClickListener { onDeny(alert) }
    }

    companion object {
        private val DIFF = object : DiffUtil.ItemCallback<Alert>() {
            override fun areItemsTheSame(old: Alert, new: Alert) =
                old.anomalyId == new.anomalyId
            override fun areContentsTheSame(old: Alert, new: Alert) = old == new
        }
    }
}
