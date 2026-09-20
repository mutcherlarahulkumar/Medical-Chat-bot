package com.skintracker.schedule

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import android.util.Log
import com.skintracker.data.AppDatabase
import com.skintracker.data.Routine
import java.time.ZonedDateTime

/**
 * Turns routines into OS alarms.
 *
 * Android does not have repeating exact alarms that survive Doze, so each
 * alarm is one-shot: when it fires, [AlarmReceiver] immediately books the next
 * one. Everything is also re-booked on reboot, time change and timezone change,
 * because the OS drops pending alarms on reboot.
 */
object AlarmScheduler {
    private const val TAG = "AlarmScheduler"

    private fun intent(context: Context, routineId: Long) =
        Intent(context, AlarmReceiver::class.java).apply {
            action = "com.skintracker.FIRE"
            // The data URI makes each routine's PendingIntent distinct; extras alone
            // do not, so without it every routine would overwrite the same alarm.
            data = android.net.Uri.parse("skintracker://routine/$routineId")
            putExtra(Notifications.EXTRA_ROUTINE_ID, routineId)
        }

    private fun pending(context: Context, routineId: Long, flags: Int) =
        PendingIntent.getBroadcast(context, routineId.toInt(), intent(context, routineId), flags)

    fun canScheduleExact(context: Context): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return true
        return context.getSystemService(AlarmManager::class.java)?.canScheduleExactAlarms() == true
    }

    /** Books the next firing of [routine], or cancels it if disabled. */
    fun schedule(context: Context, routine: Routine, now: ZonedDateTime = ZonedDateTime.now()) {
        val manager = context.getSystemService(AlarmManager::class.java) ?: return
        cancel(context, routine.id)
        if (!routine.enabled) return

        val next = nextOccurrence(routine.hour, routine.minute, routine.repeatMask, now) ?: return
        val at = next.toInstant().toEpochMilli()
        val op = pending(
            context,
            routine.id,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        try {
            if (canScheduleExact(context)) {
                manager.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, op)
            } else {
                // Without the exact-alarm permission the OS may delay us; a window
                // is still far better than nothing.
                manager.setWindow(AlarmManager.RTC_WAKEUP, at, 10 * 60_000L, op)
            }
            Log.i(TAG, "Routine ${routine.id} (${routine.name}) next at $next")
        } catch (e: SecurityException) {
            Log.w(TAG, "Exact alarm denied for routine ${routine.id}", e)
            manager.setWindow(AlarmManager.RTC_WAKEUP, at, 10 * 60_000L, op)
        }
    }

    fun cancel(context: Context, routineId: Long) {
        val manager = context.getSystemService(AlarmManager::class.java) ?: return
        val op = pending(
            context,
            routineId,
            PendingIntent.FLAG_NO_CREATE or PendingIntent.FLAG_IMMUTABLE,
        ) ?: return
        manager.cancel(op)
        op.cancel()
    }

    /** Re-books every enabled routine. Used on boot, time change, and app start. */
    suspend fun rescheduleAll(context: Context) {
        val routines = AppDatabase.get(context).dao().allRoutines()
        routines.forEach { schedule(context, it.routine) }
        Log.i(TAG, "Rescheduled ${routines.count { it.routine.enabled }} routine(s)")
    }
}
