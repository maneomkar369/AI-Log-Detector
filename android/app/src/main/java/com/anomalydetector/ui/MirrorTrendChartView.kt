package com.anomalydetector.ui

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.graphics.Shader
import android.util.AttributeSet
import android.util.TypedValue
import android.view.View
import kotlin.math.max

/**
 * Lightweight 7-day trend chart for alert counts.
 */
class MirrorTrendChartView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0,
) : View(context, attrs, defStyleAttr) {

    private val gridPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#D9E5F7")
        strokeWidth = dp(1f)
        style = Paint.Style.STROKE
    }

    private val linePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#1D57EE")
        strokeWidth = dp(4.4f)
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
    }

    private val dotPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#1D57EE")
        style = Paint.Style.FILL
    }

    private val fillPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.FILL
    }

    private val spikeHaloPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#401D57EE")
        style = Paint.Style.FILL
    }

    private val spikeRingPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#1D57EE")
        style = Paint.Style.STROKE
        strokeWidth = dp(2f)
    }

    private val spikeCorePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#FFFFFF")
        style = Paint.Style.FILL
    }

    private val xAxisLabelPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#5B6B86")
        textAlign = Paint.Align.CENTER
        textSize = sp(11f)
    }

    private val chartRect = RectF()
    private var points: List<Float> = List(7) { 0f }
    private var xAxisLabels: List<String> = listOf("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

    fun setPoints(values: List<Float>) {
        points = if (values.isEmpty()) List(7) { 0f } else values
        invalidate()
    }

    fun setXAxisLabels(labels: List<String>) {
        xAxisLabels = if (labels.isEmpty()) {
            listOf("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
        } else {
            labels
        }
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)

        val left = dp(12f)
        val top = dp(10f)
        val right = width - dp(12f)
        val bottom = height - dp(30f)
        chartRect.set(left, top, right, bottom)

        drawGrid(canvas)
        drawTrend(canvas)
        drawXAxisLabels(canvas)
    }

    private fun drawGrid(canvas: Canvas) {
        val rowCount = 5
        for (row in 0 until rowCount) {
            val y = chartRect.top + (row * (chartRect.height() / (rowCount - 1)))
            canvas.drawLine(chartRect.left, y, chartRect.right, y, gridPaint)
        }
    }

    private fun drawTrend(canvas: Canvas) {
        if (points.isEmpty()) return

        val maxValue = max(points.maxOrNull() ?: 0f, 1f)
        val stepX = if (points.size <= 1) 0f else chartRect.width() / (points.size - 1)
        val coordinates = mutableListOf<Pair<Float, Float>>()

        val linePath = Path()
        val fillPath = Path()

        points.forEachIndexed { index, value ->
            val x = chartRect.left + (stepX * index)
            val ratio = value / maxValue
            val y = chartRect.bottom - (ratio * chartRect.height())
            coordinates += x to y

            if (index == 0) {
                linePath.moveTo(x, y)
                fillPath.moveTo(x, chartRect.bottom)
                fillPath.lineTo(x, y)
            } else {
                linePath.lineTo(x, y)
                fillPath.lineTo(x, y)
            }
        }

        fillPath.lineTo(chartRect.right, chartRect.bottom)
        fillPath.close()

        fillPaint.shader = LinearGradient(
            0f,
            chartRect.top,
            0f,
            chartRect.bottom,
            Color.parseColor("#801D57EE"),
            Color.parseColor("#001D57EE"),
            Shader.TileMode.CLAMP,
        )

        canvas.drawPath(fillPath, fillPaint)
        canvas.drawPath(linePath, linePaint)

        coordinates.forEach { (x, y) ->
            canvas.drawCircle(x, y, dp(3.6f), dotPaint)
        }

        val spikeIndex = points.indices.maxByOrNull { idx -> points[idx] } ?: 0
        if (spikeIndex in coordinates.indices) {
            val (spikeX, spikeY) = coordinates[spikeIndex]
            canvas.drawCircle(spikeX, spikeY, dp(9f), spikeHaloPaint)
            canvas.drawCircle(spikeX, spikeY, dp(6f), spikeRingPaint)
            canvas.drawCircle(spikeX, spikeY, dp(3f), spikeCorePaint)
        }
    }

    private fun drawXAxisLabels(canvas: Canvas) {
        if (xAxisLabels.isEmpty()) return

        val visibleLabels = if (xAxisLabels.size == points.size) {
            xAxisLabels
        } else {
            xAxisLabels.take(points.size)
        }

        val stepX = if (points.size <= 1) 0f else chartRect.width() / (points.size - 1)
        val labelY = chartRect.bottom + dp(16f)
        visibleLabels.forEachIndexed { index, label ->
            val x = chartRect.left + (stepX * index)
            canvas.drawText(label, x, labelY, xAxisLabelPaint)
        }
    }

    private fun dp(value: Float): Float = value * resources.displayMetrics.density

    private fun sp(value: Float): Float = TypedValue.applyDimension(
        TypedValue.COMPLEX_UNIT_SP,
        value,
        resources.displayMetrics,
    )
}
