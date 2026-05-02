#!/bin/bash
# AI Log Detector - Live Demo Execution Scripts
# Run these commands to simulate anomalies during your physical demonstration.

ADB_PATH="/Users/vishal/Library/Android/sdk/platform-tools/adb"

function print_header() {
    echo -e "\n========================================"
    echo -e "🚀 $1"
    echo -e "========================================\n"
}

# Ensure ADB is connected
$ADB_PATH devices

echo "Select which 'Real Life' scenario to trigger on your Android Device:"
echo "1) 🐦 Trigger Canary File Alert (Ransomware mimicry)"
echo "2) 🎣 Trigger Phishing Detection (DNS / TFLite Hook)"
echo "3) 🕵️ Trigger Suspicious Permission (Insider Threat)"
echo "4) 📱 Spike App Transitions (Malware Mimicry)"
echo "q) Quit"

read -p "Choose an option: " choice

case $choice in
    1)
        print_header "Triggering Canary File Decoy Access"
        echo "Creating/Modifying the decoy file via ADB..."
        $ADB_PATH shell touch /sdcard/Download/.canary_bank_details.pdf
        echo "✅ Sent. Check your Dashboard for a Severity 10 MALWARE_MIMICRY alert."
        ;;
    2)
        print_header "Triggering Phishing Navigation"
        echo "Forcing Android browser to open a known phishing URL..."
        $ADB_PATH shell am start -a android.intent.action.VIEW -d "http://paypal-secure-login-update.tk"
        echo "✅ Sent. The device should open Chrome, and the server should catch the URL."
        ;;
    3)
        print_header "Triggering Suspicious Permission Event"
        echo "Simulating a background app accessing the CAMERA..."
        # NOTE: Replace 'com.test.app' with any random third-party app installed on your phone
        $ADB_PATH shell cmd appops set com.whatsapp CAMERA allow
        echo "✅ Sent. The system will correlate this permission with the baseline score."
        ;;
    4)
        print_header "Triggering Rapid App Spikes"
        echo "Rapidly launching multiple apps to trigger DEVICE_MISUSE..."
        $ADB_PATH shell monkey -p com.android.chrome -c android.intent.category.LAUNCHER 1
        sleep 1
        $ADB_PATH shell monkey -p com.google.android.calculator -c android.intent.category.LAUNCHER 1
        sleep 1
        $ADB_PATH shell monkey -p com.android.settings -c android.intent.category.LAUNCHER 1
        echo "✅ Sent. Check Dashboard for anomaly threshold spike."
        ;;
    q)
        echo "Exiting."
        exit 0
        ;;
    *)
        echo "Invalid option."
        ;;
esac
