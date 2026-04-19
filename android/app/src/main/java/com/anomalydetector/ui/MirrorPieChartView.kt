package com.anomalydetector.ui

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.util.AttributeSet
import android.util.TypedValue
import android.view.View
import kotlin.math.min

/**
 * Lightweight pie chart view used by the Android dashboard.
 */
class MirrorPieChartView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0,
) : View(context, attrs, defStyleAttr) {

    data class Slice(
        val label: String,
        val value: Float,
        val color: Int,
    )

    private val arcPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.BUTT
    }

    private val ringTrackPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        color = Color.parseColor("#DCE7F6")
    }

    private val centerTextPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#111111")
        textAlign = Paint.Align.CENTER
        textSize = sp(31f)
        isFakeBoldText = true
    }

    private val subTextPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#5E6E87")
        textAlign = Paint.Align.CENTER
        textSize = sp(13f)
    }

    private val centerIconRingPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#5A83E6")
        style = Paint.Style.STROKE
        strokeWidth = dp(1.5f)
    }

    private val centerIconCorePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#1D57EE")
        style = Paint.Style.FILL
    }

    private val chartBounds = RectF()
    private var slices: List<Slice> = emptyList()
    private var centerText: String = "0"

    fun setSlices(values: List<Slice>) {
        slices = values.filter { it.value > 0f }
        invalidate()
    }

    fun setCenterText(value: String) {
        centerText = value
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)

        val stroke = dp(22f)
        val widthPx = width.toFloat()
        val heightPx = height.toFloat()
        val diameter = min(widthPx, heightPx) - stroke
        val left = (widthPx - diameter) / 2f
        val top = (heightPx - diameter) / 2f
        chartBounds.set(left, top, left + diameter, top + diameter)

        arcPaint.strokeWidth = stroke
        ringTrackPaint.strokeWidth = stroke

        canvas.drawArc(chartBounds, 0f, 360f, false, ringTrackPaint)

        val total = slices.sumOf { it.value.toDouble() }.toFloat()
        if (total > 0f) {
            var startAngle = -90f
            slices.forEach { slice ->
                val sweep = (slice.value / total) * 360f
                arcPaint.color = slice.color
                canvas.drawArc(chartBounds, startAngle, sweep, false, arcPaint)
                startAngle += sweep
            }
        }

        val centerX = widthPx / 2f
        val centerY = heightPx / 2f

        val iconY = centerY - dp(22f)
        canvas.drawCircle(centerX, iconY, dp(5f), centerIconRingPaint)
        canvas.drawCircle(centerX, iconY, dp(1.8f), centerIconCorePaint)

        val numberBaseline = centerY - ((centerTextPaint.ascent() + centerTextPaint.descent()) / 2f) + dp(1f)
        canvas.drawText(centerText, centerX, numberBaseline, centerTextPaint)

        val labelBaseline = centerY + dp(24f)
        canvas.drawText("Total Alerts", centerX, labelBaseline, subTextPaint)
    }

    private fun dp(value: Float): Float = value * resources.displayMetrics.density

    private fun sp(value: Float): Float = TypedValue.applyDimension(
        TypedValue.COMPLEX_UNIT_SP,
        value,
        resources.displayMetrics,
    )
}
