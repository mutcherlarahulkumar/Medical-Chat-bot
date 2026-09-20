package com.skintracker

import android.app.Application
import com.skintracker.schedule.Notifications

class SkinTrackerApp : Application() {
    override fun onCreate() {
        super.onCreate()
        // Creating the channel early means the OS shows it in settings even
        // before the first reminder fires.
        Notifications.ensureChannel(this)
    }
}
