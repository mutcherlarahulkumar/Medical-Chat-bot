package com.skintracker.schedule

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import com.skintracker.data.AppDatabase
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

/** Fires at the reminder time: notify, then book the next occurrence. */
class AlarmReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        val routineId = intent.getLongExtra(Notifications.EXTRA_ROUTINE_ID, -1L)
        if (routineId <= 0) return

        // onReceive must return quickly, and the process may be killed straight
        // after, so hold the broadcast open while we touch the database.
        val pending = goAsync()
        CoroutineScope(Dispatchers.IO).launch {
            try {
                val dao = AppDatabase.get(context).dao()
                val routine = dao.routine(routineId)
                if (routine == null) {
                    Log.w("AlarmReceiver", "Routine $routineId is gone; not rescheduling.")
                    return@launch
                }
                if (routine.routine.enabled) {
                    Notifications.show(
                        context,
                        routineId,
                        routine.routine.name,
                        routine.steps.size,
                    )
                }
                // A one-off reminder is done; anything repeating books its next run.
                if (routine.routine.repeatMask == Repeat.ONCE) {
                    dao.setEnabled(routineId, false)
                } else {
                    AlarmScheduler.schedule(context, routine.routine)
                }
            } catch (e: Exception) {
                Log.e("AlarmReceiver", "Failed handling routine $routineId", e)
            } finally {
                pending.finish()
            }
        }
    }
}
