package com.skintracker.schedule

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import com.skintracker.MainActivity
import com.skintracker.R

object Notifications {
    const val CHANNEL_ID = "routine-reminders"
    const val EXTRA_ROUTINE_ID = "routineId"

    fun ensureChannel(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val channel = NotificationChannel(
            CHANNEL_ID,
            "Routine reminders",
            NotificationManager.IMPORTANCE_HIGH,
        ).apply {
            description = "Tells you when it's time to do a skincare routine."
            enableVibration(true)
        }
        context.getSystemService(NotificationManager::class.java)
            ?.createNotificationChannel(channel)
    }

    /** Tapping the notification opens that routine's checklist. */
    fun show(context: Context, routineId: Long, title: String, stepCount: Int) {
        ensureChannel(context)

        val open = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            putExtra(EXTRA_ROUTINE_ID, routineId)
        }
        val pending = PendingIntent.getActivity(
            context,
            routineId.toInt(),
            open,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        val body = when (stepCount) {
            0 -> "No products in this routine yet."
            1 -> "1 product to tick off."
            else -> "$stepCount products to tick off."
        }

        val notification = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(title)
            .setContentText(body)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_REMINDER)
            .setContentIntent(pending)
            .setAutoCancel(true)
            .build()

        // POST_NOTIFICATIONS may have been revoked; notify() then throws nothing
        // but silently drops, so check first for clarity.
        if (NotificationManagerCompat.from(context).areNotificationsEnabled()) {
            try {
                NotificationManagerCompat.from(context).notify(routineId.toInt(), notification)
            } catch (e: SecurityException) {
                // Permission revoked between the check and the call — nothing to do.
            }
        }
    }
}
