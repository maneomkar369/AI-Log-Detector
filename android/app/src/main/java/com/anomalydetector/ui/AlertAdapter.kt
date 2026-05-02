package com.anomalydetector.ui

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.ImageView
import android.widget.TextView
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
    private val onMarkNormal: (Alert) -> Unit,
) : ListAdapter<Alert, AlertAdapter.ViewHolder>(DIFF) {

    private data class SeverityUi(
        val label: String,
        val color: Int,
        val iconRes: Int,
    )

    class ViewHolder(view: View) : RecyclerView.ViewHolder(view) {
        val textSeverity: TextView = view.findViewById(R.id.textSeverity)
        val iconSeverity: ImageView = view.findViewById(R.id.iconSeverity)
        val textThreatType: TextView = view.findViewById(R.id.textThreatType)
        val textMessage: TextView = view.findViewById(R.id.textMessage)
        val textConfidence: TextView = view.findViewById(R.id.textConfidence)
        val textTime: TextView = view.findViewById(R.id.textTime)
        val textStatus: TextView = view.findViewById(R.id.textStatus)
        val btnApprove: Button = view.findViewById(R.id.btnApprove)
        val btnDeny: Button = view.findViewById(R.id.btnDeny)
        val btnMarkNormal: Button = view.findViewById(R.id.btnMarkNormal)
        val severityBar: View = view.findViewById(R.id.severityBar)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_alert, parent, false)
        return ViewHolder(view)
    }

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        val alert = getItem(position)

        val severityUi = when {
            alert.severity >= 8 -> SeverityUi(
                label = "Critical",
                color = android.graphics.Color.parseColor("#D90429"),
                iconRes = R.drawable.ic_alert_critical,
            )
            alert.severity >= 4 -> SeverityUi(
                label = "Warning",
                color = android.graphics.Color.parseColor("#F57C00"),
                iconRes = R.drawable.ic_alert_warning,
            )
            else -> SeverityUi(
                label = "Normal",
                color = android.graphics.Color.parseColor("#16A34A"),
                iconRes = R.drawable.ic_alert_normal,
            )
        }

        holder.textSeverity.text = "${severityUi.label} · ${alert.severity}/10"
        holder.iconSeverity.setImageResource(severityUi.iconRes)
        holder.iconSeverity.setColorFilter(severityUi.color)
        holder.textThreatType.text = "Type: ${alert.threatType}"
        holder.textMessage.text = alert.message
        holder.textConfidence.text = "Confidence: ${(alert.confidence * 100).toInt()}%"
        holder.textTime.text = SimpleDateFormat("HH:mm:ss", Locale.getDefault())
            .format(Date(alert.receivedAt))
        val status = alert.status.lowercase(Locale.getDefault())
        holder.textStatus.text = status.replaceFirstChar { char ->
            if (char.isLowerCase()) char.titlecase(Locale.getDefault()) else char.toString()
        }

        holder.severityBar.setBackgroundColor(severityUi.color)
        holder.textSeverity.setTextColor(severityUi.color)

        val (statusBackgroundRes, statusTextColor) = when (status) {
            "approved" -> Pair(
                R.drawable.bg_alert_status_approved,
                android.graphics.Color.parseColor("#1B8B50"),
            )
            "denied", "rejected" -> Pair(
                R.drawable.bg_alert_status_denied,
                android.graphics.Color.parseColor("#C3273C"),
            )
            "normal" -> Pair(
                R.drawable.bg_alert_status_approved, // Reuse approved bg
                android.graphics.Color.parseColor("#1B8B50"),
            )
            else -> Pair(
                R.drawable.bg_alert_status_pending,
                android.graphics.Color.parseColor("#A15E10"),
            )
        }
        holder.textStatus.setBackgroundResource(statusBackgroundRes)
        holder.textStatus.setTextColor(statusTextColor)

        // Show/hide action buttons based on status
        val isPending = status == "pending"
        holder.btnApprove.visibility = if (isPending) View.VISIBLE else View.GONE
        holder.btnDeny.visibility = if (isPending) View.VISIBLE else View.GONE
        holder.btnMarkNormal.visibility = if (isPending) View.VISIBLE else View.GONE

        holder.btnApprove.setOnClickListener { onApprove(alert) }
        holder.btnDeny.setOnClickListener { onDeny(alert) }
        holder.btnMarkNormal.setOnClickListener { onMarkNormal(alert) }
    }

    companion object {
        private val DIFF = object : DiffUtil.ItemCallback<Alert>() {
            override fun areItemsTheSame(old: Alert, new: Alert) =
                old.anomalyId == new.anomalyId
            override fun areContentsTheSame(old: Alert, new: Alert) = old == new
        }
    }
}
