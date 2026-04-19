import os

activity_main = """<?xml version="1.0" encoding="utf-8"?>
<androidx.constraintlayout.widget.ConstraintLayout
    xmlns:android="http://schemas.android.com/apk/res/android"
    xmlns:app="http://schemas.android.com/apk/res-auto"
    android:layout_width="match_parent"
    android:layout_height="match_parent"
    android:background="#F2F5FA"
    android:paddingStart="16dp"
    android:paddingEnd="16dp"
    android:paddingTop="16dp"
    android:paddingBottom="10dp">

    <LinearLayout
        android:id="@+id/headerBar"
        android:layout_width="0dp"
        android:layout_height="wrap_content"
        android:background="@drawable/bg_mirror_card"
        android:elevation="8dp"
        android:gravity="center_vertical"
        android:orientation="horizontal"
        android:padding="20dp"
        app:layout_constraintEnd_toEndOf="parent"
        app:layout_constraintStart_toStartOf="parent"
        app:layout_constraintTop_toTopOf="parent">

        <LinearLayout
            android:layout_width="0dp"
            android:layout_height="wrap_content"
            android:layout_weight="1"
            android:orientation="vertical">

            <TextView
                android:layout_width="wrap_content"
                android:layout_height="wrap_content"
                android:fontFamily="sans-serif-black"
                android:text="Overview"
                android:textColor="#111B3D"
                android:textSize="32sp" />

            <TextView
                android:layout_width="wrap_content"
                android:layout_height="wrap_content"
                android:layout_marginTop="4dp"
                android:fontFamily="sans-serif-medium"
                android:text="Behavioral Log Anomaly Detector"
                android:textColor="#5A6B90"
                android:textSize="14sp" />
        </LinearLayout>

        <LinearLayout
            android:layout_width="wrap_content"
            android:layout_height="wrap_content"
            android:background="@drawable/bg_mirror_chip_unselected"
            android:gravity="center_vertical"
            android:orientation="horizontal"
            android:paddingStart="12dp"
            android:paddingTop="8dp"
            android:paddingEnd="12dp"
            android:paddingBottom="8dp">

            <View
                android:layout_width="8dp"
                android:layout_height="8dp"
                android:background="@drawable/bg_status_dot" />

            <TextView
                android:id="@+id/textSyncStatus"
                android:layout_width="wrap_content"
                android:layout_height="wrap_content"
                android:layout_marginStart="8dp"
                android:fontFamily="sans-serif-medium"
                android:text="Pending sync: 0"
                android:textColor="#586B97"
                android:textSize="13sp" />
        </LinearLayout>
    </LinearLayout>

    <FrameLayout
        android:id="@+id/pageHost"
        android:layout_width="0dp"
        android:layout_height="0dp"
        android:layout_marginTop="16dp"
        android:layout_marginBottom="16dp"
        app:layout_constraintBottom_toTopOf="@+id/tabsRow"
        app:layout_constraintEnd_toEndOf="parent"
        app:layout_constraintStart_toStartOf="parent"
        app:layout_constraintTop_toBottomOf="@id/headerBar">

        <androidx.core.widget.NestedScrollView
            android:id="@+id/pageDashboard"
            android:layout_width="match_parent"
            android:layout_height="match_parent"
            android:fillViewport="true"
            android:overScrollMode="never">

            <LinearLayout
                android:layout_width="match_parent"
                android:layout_height="wrap_content"
                android:orientation="vertical"
                android:paddingBottom="30dp">

                <LinearLayout
                    android:layout_width="match_parent"
                    android:layout_height="wrap_content"
                    android:background="@drawable/bg_mirror_card"
                    android:elevation="4dp"
                    android:gravity="center_vertical"
                    android:orientation="horizontal"
                    android:padding="20dp">

                    <View
                        android:id="@+id/statusDot"
                        android:layout_width="14dp"
                        android:layout_height="14dp"
                        android:background="@drawable/bg_status_dot" />

                    <TextView
                        android:id="@+id/textConnectionStatus"
                        android:layout_width="0dp"
                        android:layout_height="wrap_content"
                        android:layout_marginStart="14dp"
                        android:layout_weight="1"
                        android:fontFamily="sans-serif-medium"
                        android:text="Disconnected"
                        android:textColor="#111B3D"
                        android:textSize="17sp" />

                    <TextView
                        android:layout_width="wrap_content"
                        android:layout_height="wrap_content"
                        android:background="@drawable/bg_mirror_chip_selected"
                        android:fontFamily="sans-serif-bold"
                        android:paddingStart="12dp"
                        android:paddingTop="6dp"
                        android:paddingEnd="12dp"
                        android:paddingBottom="6dp"
                        android:text="Live"
                        android:textColor="#1C2F59"
                        android:textSize="12sp" />
                </LinearLayout>

                <!-- RECENT ALERTS AT THE TOP -->
                <LinearLayout
                    android:layout_width="match_parent"
                    android:layout_height="wrap_content"
                    android:layout_marginTop="16dp"
                    android:background="@drawable/bg_mirror_card"
                    android:elevation="4dp"
                    android:orientation="vertical"
                    android:padding="20dp">

                    <LinearLayout
                        android:layout_width="match_parent"
                        android:layout_height="wrap_content"
                        android:gravity="center_vertical"
                        android:orientation="horizontal">

                        <TextView
                            android:layout_width="0dp"
                            android:layout_height="wrap_content"
                            android:layout_weight="1"
                            android:fontFamily="sans-serif-bold"
                            android:text="Recent Alerts"
                            android:textColor="#111B3D"
                            android:textSize="20sp" />

                        <TextView
                            android:id="@+id/textAlertCount"
                            android:layout_width="wrap_content"
                            android:layout_height="wrap_content"
                            android:fontFamily="sans-serif-medium"
                            android:text="0 alerts"
                            android:textColor="#6A7EA8"
                            android:textSize="14sp" />
                    </LinearLayout>

                    <androidx.recyclerview.widget.RecyclerView
                        android:id="@+id/recyclerAlerts"
                        android:layout_width="match_parent"
                        android:layout_height="280dp"
                        android:layout_marginTop="16dp"
                        android:nestedScrollingEnabled="true" />
                </LinearLayout>

                <LinearLayout
                    android:layout_width="match_parent"
                    android:layout_height="wrap_content"
                    android:layout_marginTop="16dp"
                    android:orientation="horizontal"
                    android:weightSum="3">

                    <LinearLayout
                        android:layout_width="0dp"
                        android:layout_height="wrap_content"
                        android:layout_marginEnd="6dp"
                        android:layout_weight="1"
                        android:background="@drawable/bg_mirror_card"
                        android:elevation="3dp"
                        android:orientation="vertical"
                        android:padding="16dp">

                        <TextView
                            android:layout_width="wrap_content"
                            android:layout_height="wrap_content"
                            android:fontFamily="sans-serif-medium"
                            android:text="Total"
                            android:textColor="#697C9F"
                            android:textSize="13sp" />

                        <TextView
                            android:id="@+id/textTotalAlerts"
                            android:layout_width="wrap_content"
                            android:layout_height="wrap_content"
                            android:layout_marginTop="6dp"
                            android:fontFamily="sans-serif-bold"
                            android:text="0"
                            android:textColor="#192A4D"
                            android:textSize="26sp" />
                    </LinearLayout>

                    <LinearLayout
                        android:layout_width="0dp"
                        android:layout_height="wrap_content"
                        android:layout_marginHorizontal="3dp"
                        android:layout_weight="1"
                        android:background="@drawable/bg_mirror_card"
                        android:elevation="3dp"
                        android:orientation="vertical"
                        android:padding="16dp">

                        <TextView
                            android:layout_width="wrap_content"
                            android:layout_height="wrap_content"
                            android:fontFamily="sans-serif-medium"
                            android:text="Pending"
                            android:textColor="#697C9F"
                            android:textSize="13sp" />

                        <TextView
                            android:id="@+id/textPendingAlerts"
                            android:layout_width="wrap_content"
                            android:layout_height="wrap_content"
                            android:layout_marginTop="6dp"
                            android:fontFamily="sans-serif-bold"
                            android:text="0"
                            android:textColor="#192A4D"
                            android:textSize="26sp" />
                    </LinearLayout>

                    <LinearLayout
                        android:layout_width="0dp"
                        android:layout_height="wrap_content"
                        android:layout_marginStart="6dp"
                        android:layout_weight="1"
                        android:background="@drawable/bg_mirror_card"
                        android:elevation="3dp"
                        android:orientation="vertical"
                        android:padding="16dp">

                        <TextView
                            android:layout_width="wrap_content"
                            android:layout_height="wrap_content"
                            android:fontFamily="sans-serif-medium"
                            android:text="Approved"
                            android:textColor="#697C9F"
                            android:textSize="13sp" />

                        <TextView
                            android:id="@+id/textApprovedAlerts"
                            android:layout_width="wrap_content"
                            android:layout_height="wrap_content"
                            android:layout_marginTop="6dp"
                            android:fontFamily="sans-serif-bold"
                            android:text="0"
                            android:textColor="#192A4D"
                            android:textSize="26sp" />
                    </LinearLayout>
                </LinearLayout>

                <LinearLayout
                    android:layout_width="match_parent"
                    android:layout_height="wrap_content"
                    android:layout_marginTop="16dp"
                    android:background="@drawable/bg_mirror_card"
                    android:elevation="3dp"
                    android:orientation="vertical"
                    android:padding="20dp">

                    <TextView
                        android:layout_width="wrap_content"
                        android:layout_height="wrap_content"
                        android:fontFamily="sans-serif-bold"
                        android:text="Trends &amp; Distribution"
                        android:textColor="#111B3D"
                        android:textSize="18sp" />

                    <TextView
                        android:id="@+id/textTrendSummary"
                        android:layout_width="wrap_content"
                        android:layout_height="wrap_content"
                        android:layout_marginTop="4dp"
                        android:fontFamily="sans-serif-medium"
                        android:text="7-day total: 0 · peak/day: 0"
                        android:textColor="#697CA6"
                        android:textSize="14sp" />

                    <LinearLayout
                        android:layout_width="match_parent"
                        android:layout_height="wrap_content"
                        android:layout_marginTop="20dp"
                        android:gravity="center_vertical"
                        android:orientation="vertical">

                        <LinearLayout
                            android:layout_width="match_parent"
                            android:layout_height="200dp"
                            android:background="@drawable/bg_mirror_chip_unselected"
                            android:gravity="center"
                            android:padding="12dp">

                            <com.anomalydetector.ui.MirrorTrendChartView
                                android:id="@+id/trendAlertDistribution"
                                android:layout_width="match_parent"
                                android:layout_height="match_parent" />
                        </LinearLayout>

                        <LinearLayout
                            android:layout_width="match_parent"
                            android:layout_height="180dp"
                            android:layout_marginTop="16dp"
                            android:background="@drawable/bg_mirror_chip_unselected"
                            android:gravity="center"
                            android:padding="12dp">

                            <com.anomalydetector.ui.MirrorPieChartView
                                android:id="@+id/pieAlertDistribution"
                                android:layout_width="match_parent"
                                android:layout_height="match_parent" />
                        </LinearLayout>
                    </LinearLayout>

                    <LinearLayout
                        android:layout_width="match_parent"
                        android:layout_height="wrap_content"
                        android:layout_marginTop="16dp"
                        android:orientation="horizontal"
                        android:weightSum="2">

                        <LinearLayout
                            android:layout_width="0dp"
                            android:layout_height="wrap_content"
                            android:layout_weight="1"
                            android:orientation="vertical">

                            <TextView
                                android:id="@+id/textCriticalSlice"
                                android:layout_width="wrap_content"
                                android:layout_height="wrap_content"
                                android:fontFamily="sans-serif-bold"
                                android:text="Critical: 0"
                                android:textColor="#E86A8E"
                                android:textSize="14sp" />

                            <TextView
                                android:id="@+id/textHighSlice"
                                android:layout_width="wrap_content"
                                android:layout_height="wrap_content"
                                android:layout_marginTop="6dp"
                                android:fontFamily="sans-serif-bold"
                                android:text="High: 0"
                                android:textColor="#F39C5D"
                                android:textSize="14sp" />
                        </LinearLayout>

                        <LinearLayout
                            android:layout_width="0dp"
                            android:layout_height="wrap_content"
                            android:layout_weight="1"
                            android:orientation="vertical">

                            <TextView
                                android:id="@+id/textMediumSlice"
                                android:layout_width="wrap_content"
                                android:layout_height="wrap_content"
                                android:fontFamily="sans-serif-bold"
                                android:text="Medium: 0"
                                android:textColor="#6695E8"
                                android:textSize="14sp" />

                            <TextView
                                android:id="@+id/textLowSlice"
                                android:layout_width="wrap_content"
                                android:layout_height="wrap_content"
                                android:layout_marginTop="6dp"
                                android:fontFamily="sans-serif-bold"
                                android:text="Low: 0"
                                android:textColor="#4DBA95"
                                android:textSize="14sp" />
                        </LinearLayout>
                    </LinearLayout>
                </LinearLayout>

                <LinearLayout
                    android:layout_width="match_parent"
                    android:layout_height="wrap_content"
                    android:layout_marginTop="16dp"
                    android:background="@drawable/bg_mirror_card"
                    android:elevation="3dp"
                    android:orientation="vertical"
                    android:padding="20dp">

                    <TextView
                        android:layout_width="wrap_content"
                        android:layout_height="wrap_content"
                        android:fontFamily="sans-serif-bold"
                        android:text="Monitoring Controls"
                        android:textColor="#111B3D"
                        android:textSize="18sp" />

                    <com.google.android.material.button.MaterialButton
                        android:id="@+id/btnToggle"
                        android:layout_width="match_parent"
                        android:layout_height="56dp"
                        android:layout_marginTop="16dp"
                        android:background="@drawable/bg_mirror_button_primary"
                        android:fontFamily="sans-serif-medium"
                        android:text="Start Monitoring"
                        android:textAllCaps="false"
                        android:textColor="#FFFFFF"
                        android:textSize="16sp"
                        app:backgroundTint="@android:color/transparent" />

                    <com.google.android.material.button.MaterialButton
                        android:id="@+id/btnVpnFlow"
                        android:layout_width="match_parent"
                        android:layout_height="56dp"
                        android:layout_marginTop="12dp"
                        android:background="@drawable/bg_mirror_chip_unselected"
                        android:fontFamily="sans-serif-medium"
                        android:text="Start VPN Flow Monitor"
                        android:textAllCaps="false"
                        android:textColor="#2D436F"
                        android:textSize="16sp"
                        app:backgroundTint="@android:color/transparent" />

                    <TextView
                        android:id="@+id/textVpnStatus"
                        android:layout_width="wrap_content"
                        android:layout_height="wrap_content"
                        android:layout_marginTop="12dp"
                        android:fontFamily="sans-serif"
                        android:text="VPN flow: inactive"
                        android:textColor="#6C7FA8"
                        android:textSize="14sp" />
                </LinearLayout>
            </LinearLayout>
        </androidx.core.widget.NestedScrollView>

        <androidx.core.widget.NestedScrollView
            android:id="@+id/pageProfiles"
            android:layout_width="match_parent"
            android:layout_height="match_parent"
            android:fillViewport="true"
            android:overScrollMode="never"
            android:visibility="gone">

            <LinearLayout
                android:layout_width="match_parent"
                android:layout_height="wrap_content"
                android:orientation="vertical"
                android:paddingBottom="24dp">

                <TextView
                    android:layout_width="wrap_content"
                    android:layout_height="wrap_content"
                    android:fontFamily="sans-serif-bold"
                    android:text="Monitoring Profiles"
                    android:textColor="#111B3D"
                    android:textSize="24sp" />

                <TextView
                    android:id="@+id/textActiveProfile"
                    android:layout_width="wrap_content"
                    android:layout_height="wrap_content"
                    android:layout_marginTop="8dp"
                    android:fontFamily="sans-serif-medium"
                    android:text="Active profile: Development"
                    android:textColor="#687DA6"
                    android:textSize="15sp" />

                <!-- Profiles list exactly as is, just with fonts updated -->
                <LinearLayout
                    android:id="@+id/cardProfileDev"
                    android:layout_width="match_parent"
                    android:layout_height="wrap_content"
                    android:layout_marginTop="16dp"
                    android:background="@drawable/bg_mirror_card_active"
                    android:elevation="4dp"
                    android:orientation="vertical"
                    android:padding="20dp">
                    <TextView android:layout_width="wrap_content" android:layout_height="wrap_content" android:fontFamily="sans-serif-bold" android:text="Development" android:textColor="#111B3D" android:textSize="18sp" />
                    <TextView android:layout_width="wrap_content" android:layout_height="wrap_content" android:layout_marginTop="6dp" android:fontFamily="sans-serif" android:text="Balanced telemetry, rich diagnostics, medium-threshold alerts." android:textColor="#5B6F9A" android:textSize="14sp" />
                </LinearLayout>

                <LinearLayout
                    android:id="@+id/cardProfileSecurity"
                    android:layout_width="match_parent"
                    android:layout_height="wrap_content"
                    android:layout_marginTop="12dp"
                    android:background="@drawable/bg_mirror_card"
                    android:elevation="3dp"
                    android:orientation="vertical"
                    android:padding="20dp">
                    <TextView android:layout_width="wrap_content" android:layout_height="wrap_content" android:fontFamily="sans-serif-bold" android:text="Security Audit" android:textColor="#111B3D" android:textSize="18sp" />
                    <TextView android:layout_width="wrap_content" android:layout_height="wrap_content" android:layout_marginTop="6dp" android:fontFamily="sans-serif" android:text="High-sensitivity policy with aggressive auth and package checks." android:textColor="#5B6F9A" android:textSize="14sp" />
                </LinearLayout>

                <LinearLayout
                    android:id="@+id/cardProfilePerformance"
                    android:layout_width="match_parent"
                    android:layout_height="wrap_content"
                    android:layout_marginTop="12dp"
                    android:background="@drawable/bg_mirror_card"
                    android:elevation="3dp"
                    android:orientation="vertical"
                    android:padding="20dp">
                    <TextView android:layout_width="wrap_content" android:layout_height="wrap_content" android:fontFamily="sans-serif-bold" android:text="Performance" android:textColor="#111B3D" android:textSize="18sp" />
                    <TextView android:layout_width="wrap_content" android:layout_height="wrap_content" android:layout_marginTop="6dp" android:fontFamily="sans-serif" android:text="Lower overhead profile focused on core network and memory anomalies." android:textColor="#5B6F9A" android:textSize="14sp" />
                </LinearLayout>

                <LinearLayout
                    android:id="@+id/cardProfileQa"
                    android:layout_width="match_parent"
                    android:layout_height="wrap_content"
                    android:layout_marginTop="12dp"
                    android:background="@drawable/bg_mirror_card"
                    android:elevation="3dp"
                    android:orientation="vertical"
                    android:padding="20dp">
                    <TextView android:layout_width="wrap_content" android:layout_height="wrap_content" android:fontFamily="sans-serif-bold" android:text="Production QA" android:textColor="#111B3D" android:textSize="18sp" />
                    <TextView android:layout_width="wrap_content" android:layout_height="wrap_content" android:layout_marginTop="6dp" android:fontFamily="sans-serif" android:text="Release-ready checks with stable thresholds and traceability." android:textColor="#5B6F9A" android:textSize="14sp" />
                </LinearLayout>
            </LinearLayout>
        </androidx.core.widget.NestedScrollView>

        <LinearLayout
            android:id="@+id/pageConfig"
            android:layout_width="match_parent"
            android:layout_height="match_parent"
            android:orientation="vertical"
            android:visibility="gone">
            
            <androidx.core.widget.NestedScrollView
                android:layout_width="match_parent"
                android:layout_height="0dp"
                android:layout_weight="1"
                android:fillViewport="true"
                android:overScrollMode="never">

                <LinearLayout
                    android:layout_width="match_parent"
                    android:layout_height="wrap_content"
                    android:orientation="vertical"
                    android:paddingBottom="24dp">

                    <TextView
                        android:layout_width="wrap_content"
                        android:layout_height="wrap_content"
                        android:fontFamily="sans-serif-bold"
                        android:text="Runtime Config"
                        android:textColor="#111B3D"
                        android:textSize="24sp" />

                    <LinearLayout
                        android:layout_width="match_parent"
                        android:layout_height="wrap_content"
                        android:layout_marginTop="16dp"
                        android:background="@drawable/bg_mirror_card"
                        android:elevation="4dp"
                        android:orientation="vertical"
                        android:padding="20dp">

                        <TextView android:layout_width="wrap_content" android:layout_height="wrap_content" android:fontFamily="sans-serif-medium" android:text="Log Buffer" android:textColor="#536891" android:textSize="14sp" />
                        <Spinner android:id="@+id/spinnerConfigBuffer" android:layout_width="match_parent" android:layout_height="50dp" android:layout_marginTop="8dp" android:background="@drawable/bg_mirror_input" android:popupBackground="#FFFFFF" />

                        <TextView android:layout_width="wrap_content" android:layout_height="wrap_content" android:layout_marginTop="16dp" android:fontFamily="sans-serif-medium" android:text="Sampling Interval" android:textColor="#536891" android:textSize="14sp" />
                        <Spinner android:id="@+id/spinnerConfigSampling" android:layout_width="match_parent" android:layout_height="50dp" android:layout_marginTop="8dp" android:background="@drawable/bg_mirror_input" android:popupBackground="#FFFFFF" />

                        <TextView android:layout_width="wrap_content" android:layout_height="wrap_content" android:layout_marginTop="16dp" android:fontFamily="sans-serif-medium" android:text="Package Filter" android:textColor="#536891" android:textSize="14sp" />
                        <EditText android:id="@+id/editConfigPackageFilter" android:layout_width="match_parent" android:layout_height="50dp" android:layout_marginTop="8dp" android:background="@drawable/bg_mirror_input" android:fontFamily="sans-serif" android:hint="com.example.app" android:inputType="text" android:paddingHorizontal="16dp" android:textColor="#1F3158" android:textColorHint="#8EA0C2" />

                        <com.google.android.material.switchmaterial.SwitchMaterial android:id="@+id/switchConfigCrash" android:layout_width="match_parent" android:layout_height="wrap_content" android:layout_marginTop="16dp" android:fontFamily="sans-serif-medium" android:text="Crash detection" android:textColor="#26406D" android:textSize="15sp" />
                        <com.google.android.material.switchmaterial.SwitchMaterial android:id="@+id/switchConfigMl" android:layout_width="match_parent" android:layout_height="wrap_content" android:layout_marginTop="8dp" android:fontFamily="sans-serif-medium" android:text="ML scoring" android:textColor="#26406D" android:textSize="15sp" />
                        <com.google.android.material.switchmaterial.SwitchMaterial android:id="@+id/switchConfigSqlite" android:layout_width="match_parent" android:layout_height="wrap_content" android:layout_marginTop="8dp" android:fontFamily="sans-serif-medium" android:text="SQLite logging" android:textColor="#26406D" android:textSize="15sp" />
                        <com.google.android.material.switchmaterial.SwitchMaterial android:id="@+id/switchConfigPush" android:layout_width="match_parent" android:layout_height="wrap_content" android:layout_marginTop="8dp" android:fontFamily="sans-serif-medium" android:text="Push notifications" android:textColor="#26406D" android:textSize="15sp" />
                    </LinearLayout>
                </LinearLayout>
            </androidx.core.widget.NestedScrollView>

            <!-- Sticky Save Config Button -->
            <LinearLayout
                android:layout_width="match_parent"
                android:layout_height="wrap_content"
                android:orientation="vertical"
                android:paddingTop="12dp"
                android:gravity="center">

                <com.google.android.material.button.MaterialButton
                    android:id="@+id/btnSaveConfig"
                    android:layout_width="match_parent"
                    android:layout_height="56dp"
                    android:background="@drawable/bg_mirror_button_primary"
                    android:fontFamily="sans-serif-medium"
                    android:text="Save Config"
                    android:textAllCaps="false"
                    android:textColor="#FFFFFF"
                    android:textSize="16sp"
                    app:backgroundTint="@android:color/transparent" />

                <TextView
                    android:id="@+id/textConfigSaved"
                    android:layout_width="wrap_content"
                    android:layout_height="wrap_content"
                    android:layout_marginTop="8dp"
                    android:fontFamily="sans-serif"
                    android:text=""
                    android:textColor="#677CA5"
                    android:textSize="13sp" />
            </LinearLayout>
        </LinearLayout>

        <androidx.core.widget.NestedScrollView
            android:id="@+id/pageSettings"
            android:layout_width="match_parent"
            android:layout_height="match_parent"
            android:fillViewport="true"
            android:overScrollMode="never"
            android:visibility="gone">

            <LinearLayout
                android:layout_width="match_parent"
                android:layout_height="wrap_content"
                android:orientation="vertical"
                android:paddingBottom="24dp">

                <TextView
                    android:layout_width="wrap_content"
                    android:layout_height="wrap_content"
                    android:fontFamily="sans-serif-bold"
                    android:text="Advanced Settings"
                    android:textColor="#111B3D"
                    android:textSize="24sp" />

                <LinearLayout
                    android:layout_width="match_parent"
                    android:layout_height="wrap_content"
                    android:layout_marginTop="16dp"
                    android:background="@drawable/bg_mirror_card"
                    android:elevation="4dp"
                    android:orientation="vertical"
                    android:padding="20dp">

                    <TextView
                        android:layout_width="match_parent"
                        android:layout_height="wrap_content"
                        android:fontFamily="sans-serif"
                        android:lineSpacingExtra="4dp"
                        android:text="Open the full settings screen to tune server URL, intervals, reconnection behavior, and runtime policies."
                        android:textColor="#536992"
                        android:textSize="15sp" />

                    <com.google.android.material.button.MaterialButton
                        android:id="@+id/btnSettings"
                        android:layout_width="match_parent"
                        android:layout_height="56dp"
                        android:layout_marginTop="20dp"
                        android:background="@drawable/bg_mirror_chip_unselected"
                        android:fontFamily="sans-serif-medium"
                        android:text="Open Full Settings"
                        android:textAllCaps="false"
                        android:textColor="#2E436E"
                        android:textSize="16sp"
                        app:backgroundTint="@android:color/transparent" />
                </LinearLayout>
            </LinearLayout>
        </androidx.core.widget.NestedScrollView>
    </FrameLayout>

    <LinearLayout
        android:id="@+id/tabsRow"
        android:layout_width="0dp"
        android:layout_height="80dp"
        android:layout_marginStart="8dp"
        android:layout_marginEnd="8dp"
        android:background="@drawable/bg_mirror_nav_glass"
        android:elevation="12dp"
        android:gravity="center"
        android:orientation="horizontal"
        android:padding="8dp"
        android:weightSum="4"
        app:layout_constraintBottom_toBottomOf="parent"
        app:layout_constraintEnd_toEndOf="parent"
        app:layout_constraintStart_toStartOf="parent">

        <TextView android:id="@+id/tabDashboard" android:layout_width="0dp" android:layout_height="match_parent" android:layout_marginEnd="4dp" android:layout_weight="1" android:background="@drawable/bg_mirror_chip_selected" android:drawableTop="@android:drawable/ic_menu_view" android:drawableTint="#1A2E57" android:drawablePadding="4dp" android:fontFamily="sans-serif-medium" android:gravity="center" android:paddingTop="6dp" android:paddingBottom="6dp" android:text="Dashboard" android:textColor="#1A2E57" android:textSize="12sp" />
        <TextView android:id="@+id/tabProfiles" android:layout_width="0dp" android:layout_height="match_parent" android:layout_marginHorizontal="2dp" android:layout_weight="1" android:background="@drawable/bg_mirror_chip_unselected" android:drawableTop="@android:drawable/ic_menu_myplaces" android:drawableTint="#4B608B" android:drawablePadding="4dp" android:fontFamily="sans-serif-medium" android:gravity="center" android:paddingTop="6dp" android:paddingBottom="6dp" android:text="Profiles" android:textColor="#4B608B" android:textSize="12sp" />
        <TextView android:id="@+id/tabConfig" android:layout_width="0dp" android:layout_height="match_parent" android:layout_marginHorizontal="2dp" android:layout_weight="1" android:background="@drawable/bg_mirror_chip_unselected" android:drawableTop="@android:drawable/ic_menu_manage" android:drawableTint="#4B608B" android:drawablePadding="4dp" android:fontFamily="sans-serif-medium" android:gravity="center" android:paddingTop="6dp" android:paddingBottom="6dp" android:text="Config" android:textColor="#4B608B" android:textSize="12sp" />
        <TextView android:id="@+id/tabSettings" android:layout_width="0dp" android:layout_height="match_parent" android:layout_marginStart="4dp" android:layout_weight="1" android:background="@drawable/bg_mirror_chip_unselected" android:drawableTop="@android:drawable/ic_menu_preferences" android:drawableTint="#4B608B" android:drawablePadding="4dp" android:fontFamily="sans-serif-medium" android:gravity="center" android:paddingTop="6dp" android:paddingBottom="6dp" android:text="Settings" android:textColor="#4B608B" android:textSize="12sp" />
    </LinearLayout>
</androidx.constraintlayout.widget.ConstraintLayout>
"""

item_alert = """<?xml version="1.0" encoding="utf-8"?>
<androidx.cardview.widget.CardView
    xmlns:android="http://schemas.android.com/apk/res/android"
    xmlns:app="http://schemas.android.com/apk/res-auto"
    android:layout_width="match_parent"
    android:layout_height="wrap_content"
    android:layout_marginBottom="12dp"
    app:cardBackgroundColor="#FFFFFF"
    app:cardCornerRadius="24dp"
    app:cardElevation="2dp"
    app:cardUseCompatPadding="true">

    <LinearLayout
        android:layout_width="match_parent"
        android:layout_height="wrap_content"
        android:orientation="horizontal">

        <View
            android:id="@+id/severityBar"
            android:layout_width="8dp"
            android:layout_height="match_parent"
            android:background="#EF4444" />

        <LinearLayout
            android:layout_width="match_parent"
            android:layout_height="wrap_content"
            android:orientation="vertical"
            android:padding="20dp">

            <LinearLayout
                android:layout_width="match_parent"
                android:layout_height="wrap_content"
                android:gravity="center_vertical"
                android:orientation="horizontal">

                <TextView
                    android:id="@+id/textSeverity"
                    android:layout_width="0dp"
                    android:layout_height="wrap_content"
                    android:layout_weight="1"
                    android:fontFamily="sans-serif-bold"
                    android:textColor="#E85E78"
                    android:textSize="16sp" />

                <TextView
                    android:id="@+id/textTime"
                    android:layout_width="wrap_content"
                    android:layout_height="wrap_content"
                    android:fontFamily="sans-serif-medium"
                    android:textColor="#8192B3"
                    android:textSize="13sp" />
            </LinearLayout>

            <TextView
                android:id="@+id/textThreatType"
                android:layout_width="wrap_content"
                android:layout_height="wrap_content"
                android:layout_marginTop="4dp"
                android:fontFamily="sans-serif-medium"
                android:textColor="#6D7FA8"
                android:textSize="14sp" />

            <TextView
                android:id="@+id/textMessage"
                android:layout_width="match_parent"
                android:layout_height="wrap_content"
                android:layout_marginTop="12dp"
                android:fontFamily="sans-serif"
                android:lineSpacingExtra="4dp"
                android:textColor="#24375F"
                android:textSize="15sp" />

            <LinearLayout
                android:layout_width="match_parent"
                android:layout_height="wrap_content"
                android:layout_marginTop="12dp"
                android:gravity="center_vertical"
                android:orientation="horizontal">

                <TextView
                    android:id="@+id/textConfidence"
                    android:layout_width="0dp"
                    android:layout_height="wrap_content"
                    android:layout_weight="1"
                    android:fontFamily="sans-serif-medium"
                    android:textColor="#7083AA"
                    android:textSize="13sp" />

                <TextView
                    android:id="@+id/textStatus"
                    android:layout_width="wrap_content"
                    android:layout_height="wrap_content"
                    android:background="@drawable/bg_mirror_chip_unselected"
                    android:fontFamily="sans-serif-bold"
                    android:paddingStart="12dp"
                    android:paddingTop="6dp"
                    android:paddingEnd="12dp"
                    android:paddingBottom="6dp"
                    android:textColor="#4A5E8A"
                    android:textSize="12sp" />
            </LinearLayout>

            <LinearLayout
                android:layout_width="match_parent"
                android:layout_height="wrap_content"
                android:layout_marginTop="16dp"
                android:gravity="end"
                android:orientation="horizontal">

                <Button
                    android:id="@+id/btnApprove"
                    android:layout_width="wrap_content"
                    android:layout_height="48dp"
                    android:layout_marginEnd="12dp"
                    android:background="@drawable/bg_mirror_button_primary"
                    android:fontFamily="sans-serif-medium"
                    android:paddingStart="20dp"
                    android:paddingEnd="20dp"
                    android:text="Approve"
                    android:textAllCaps="false"
                    android:textColor="#FFFFFF"
                    android:textSize="14sp" />

                <Button
                    android:id="@+id/btnDeny"
                    android:layout_width="wrap_content"
                    android:layout_height="48dp"
                    android:background="@drawable/bg_mirror_chip_unselected"
                    android:fontFamily="sans-serif-medium"
                    android:paddingStart="20dp"
                    android:paddingEnd="20dp"
                    android:text="Deny"
                    android:textAllCaps="false"
                    android:textColor="#3E5381"
                    android:textSize="14sp" />
            </LinearLayout>
        </LinearLayout>
    </LinearLayout>
</androidx.cardview.widget.CardView>
"""

activity_settings = """<?xml version="1.0" encoding="utf-8"?>
<androidx.constraintlayout.widget.ConstraintLayout
    xmlns:android="http://schemas.android.com/apk/res/android"
    xmlns:app="http://schemas.android.com/apk/res-auto"
    android:layout_width="match_parent"
    android:layout_height="match_parent"
    android:background="#F2F5FA"
    android:padding="16dp">

    <LinearLayout
        android:id="@+id/settingsHeader"
        android:layout_width="0dp"
        android:layout_height="wrap_content"
        android:background="@drawable/bg_mirror_card"
        android:elevation="6dp"
        android:gravity="center_vertical"
        android:orientation="horizontal"
        android:padding="16dp"
        app:layout_constraintTop_toTopOf="parent"
        app:layout_constraintStart_toStartOf="parent"
        app:layout_constraintEnd_toEndOf="parent">

        <com.google.android.material.button.MaterialButton
            android:id="@+id/btnBackSettings"
            android:layout_width="48dp"
            android:layout_height="48dp"
            android:background="@drawable/bg_mirror_chip_unselected"
            android:fontFamily="sans-serif-medium"
            android:text="←"
            android:textAllCaps="false"
            android:textColor="#2D446F"
            android:textSize="20sp"
            app:backgroundTint="@android:color/transparent" />

        <TextView
            android:layout_width="0dp"
            android:layout_height="wrap_content"
            android:layout_marginStart="16dp"
            android:layout_weight="1"
            android:fontFamily="sans-serif-bold"
            android:text="Settings"
            android:textColor="#111B3D"
            android:textSize="22sp" />
    </LinearLayout>

    <LinearLayout
        android:id="@+id/settingsContent"
        android:layout_width="0dp"
        android:layout_height="0dp"
        android:layout_marginTop="16dp"
        android:orientation="vertical"
        app:layout_constraintTop_toBottomOf="@id/settingsHeader"
        app:layout_constraintBottom_toBottomOf="parent"
        app:layout_constraintStart_toStartOf="parent"
        app:layout_constraintEnd_toEndOf="parent">

        <androidx.core.widget.NestedScrollView
            android:layout_width="match_parent"
            android:layout_height="0dp"
            android:layout_weight="1"
            android:fillViewport="true"
            android:overScrollMode="never">

            <LinearLayout
                android:layout_width="match_parent"
                android:layout_height="wrap_content"
                android:orientation="vertical"
                android:paddingBottom="24dp">

                <LinearLayout
                    android:layout_width="match_parent"
                    android:layout_height="wrap_content"
                    android:background="@drawable/bg_mirror_card"
                    android:elevation="4dp"
                    android:orientation="vertical"
                    android:padding="20dp">

                    <TextView android:layout_width="wrap_content" android:layout_height="wrap_content" android:fontFamily="sans-serif-medium" android:text="Edge Server URL" android:textColor="#536891" android:textSize="14sp" />
                    <EditText android:id="@+id/editServerUrl" android:layout_width="match_parent" android:layout_height="50dp" android:layout_marginTop="8dp" android:background="@drawable/bg_mirror_input" android:fontFamily="sans-serif" android:hint="wss://your-domain.ngrok-free.app/ws" android:inputType="textUri" android:paddingHorizontal="16dp" android:textColor="#20345D" android:textColorHint="#8EA0C2" />

                    <TextView android:layout_width="wrap_content" android:layout_height="wrap_content" android:layout_marginTop="16dp" android:fontFamily="sans-serif-medium" android:text="Sampling Interval" android:textColor="#536891" android:textSize="14sp" />
                    <Spinner android:id="@+id/spinnerSamplingInterval" android:layout_width="match_parent" android:layout_height="50dp" android:layout_marginTop="8dp" android:background="@drawable/bg_mirror_input" android:popupBackground="#FFFFFF" />

                    <TextView android:layout_width="wrap_content" android:layout_height="wrap_content" android:layout_marginTop="16dp" android:fontFamily="sans-serif-medium" android:text="Reconnect Delay (ms)" android:textColor="#536891" android:textSize="14sp" />
                    <EditText android:id="@+id/editReconnectDelay" android:layout_width="match_parent" android:layout_height="50dp" android:layout_marginTop="8dp" android:background="@drawable/bg_mirror_input" android:fontFamily="sans-serif" android:inputType="number" android:paddingHorizontal="16dp" android:textColor="#20345D" android:textColorHint="#8EA0C2" />

                    <TextView android:layout_width="wrap_content" android:layout_height="wrap_content" android:layout_marginTop="16dp" android:fontFamily="sans-serif-medium" android:text="Auto Approval Timeout (ms)" android:textColor="#536891" android:textSize="14sp" />
                    <EditText android:id="@+id/editAutoApprovalTimeout" android:layout_width="match_parent" android:layout_height="50dp" android:layout_marginTop="8dp" android:background="@drawable/bg_mirror_input" android:fontFamily="sans-serif" android:inputType="number" android:paddingHorizontal="16dp" android:textColor="#20345D" android:textColorHint="#8EA0C2" />

                    <com.google.android.material.switchmaterial.SwitchMaterial android:id="@+id/switchEnableNotifications" android:layout_width="match_parent" android:layout_height="wrap_content" android:layout_marginTop="16dp" android:fontFamily="sans-serif-medium" android:text="Enable notification alerts" android:textColor="#26406D" android:textSize="15sp" />
                    <com.google.android.material.switchmaterial.SwitchMaterial android:id="@+id/switchEnableVpnCapture" android:layout_width="match_parent" android:layout_height="wrap_content" android:layout_marginTop="8dp" android:fontFamily="sans-serif-medium" android:text="Enable VPN flow capture mode" android:textColor="#26406D" android:textSize="15sp" />
                    <com.google.android.material.switchmaterial.SwitchMaterial android:id="@+id/switchEnableMlScoring" android:layout_width="match_parent" android:layout_height="wrap_content" android:layout_marginTop="8dp" android:fontFamily="sans-serif-medium" android:text="Enable ML scoring" android:textColor="#26406D" android:textSize="15sp" />
                </LinearLayout>
            </LinearLayout>
        </androidx.core.widget.NestedScrollView>

        <!-- Sticky Save Settings Button -->
        <LinearLayout
            android:layout_width="match_parent"
            android:layout_height="wrap_content"
            android:orientation="vertical"
            android:paddingTop="12dp"
            android:gravity="center">

            <com.google.android.material.button.MaterialButton
                android:id="@+id/btnSaveSettings"
                android:layout_width="match_parent"
                android:layout_height="56dp"
                android:background="@drawable/bg_mirror_button_primary"
                android:fontFamily="sans-serif-medium"
                android:text="Save Settings"
                android:textAllCaps="false"
                android:textColor="#FFFFFF"
                android:textSize="16sp"
                app:backgroundTint="@android:color/transparent" />

            <TextView
                android:id="@+id/textSettingsStatus"
                android:layout_width="wrap_content"
                android:layout_height="wrap_content"
                android:layout_marginTop="8dp"
                android:fontFamily="sans-serif"
                android:text=""
                android:textColor="#677CA5"
                android:textSize="13sp" />
        </LinearLayout>
    </LinearLayout>

</androidx.constraintlayout.widget.ConstraintLayout>
"""

with open("android/app/src/main/res/layout/activity_main.xml", "w") as f:
    f.write(activity_main)

with open("android/app/src/main/res/layout/item_alert.xml", "w") as f:
    f.write(item_alert)

with open("android/app/src/main/res/layout/activity_settings.xml", "w") as f:
    f.write(activity_settings)
