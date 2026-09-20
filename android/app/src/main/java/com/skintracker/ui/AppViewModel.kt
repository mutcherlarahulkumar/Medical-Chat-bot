package com.skintracker.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.skintracker.data.AppDatabase
import com.skintracker.data.CheckOff
import com.skintracker.data.Routine
import com.skintracker.data.RoutineWithSteps
import com.skintracker.data.Step
import com.skintracker.schedule.AlarmScheduler
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import java.time.LocalDate

class AppViewModel(app: Application) : AndroidViewModel(app) {

    private val dao = AppDatabase.get(app).dao()
    private val today: Long get() = LocalDate.now().toEpochDay()

    val routines: StateFlow<List<RoutineWithSteps>> =
        dao.observeRoutines().stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    /** Step ids ticked off today. */
    val doneToday: StateFlow<Set<Long>> =
        dao.observeCheckOffs(today)
            .map { list -> list.map { it.stepId }.toSet() }
            .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptySet())

    // ── checklist ───────────────────────────────────────────────────────────
    fun toggleStep(step: Step, done: Boolean) = viewModelScope.launch {
        if (done) dao.check(CheckOff(stepId = step.id, routineId = step.routineId, epochDay = today))
        else dao.uncheck(step.id, today)
    }

    fun markAllDone(routine: RoutineWithSteps) = viewModelScope.launch {
        routine.steps.forEach {
            dao.check(CheckOff(stepId = it.id, routineId = it.routineId, epochDay = today))
        }
    }

    fun clearRoutine(routine: RoutineWithSteps) = viewModelScope.launch {
        dao.clearRoutine(routine.routine.id, today)
    }

    // ── routines ────────────────────────────────────────────────────────────
    fun saveRoutine(routine: Routine, onSaved: (Long) -> Unit = {}) = viewModelScope.launch {
        val id = dao.upsertRoutine(routine)
        val saved = if (routine.id == 0L) routine.copy(id = id) else routine
        AlarmScheduler.schedule(getApplication(), saved)
        onSaved(saved.id)
    }

    fun setEnabled(routine: Routine, enabled: Boolean) = viewModelScope.launch {
        dao.setEnabled(routine.id, enabled)
        AlarmScheduler.schedule(getApplication(), routine.copy(enabled = enabled))
    }

    fun deleteRoutine(routine: Routine) = viewModelScope.launch {
        AlarmScheduler.cancel(getApplication(), routine.id)
        dao.deleteRoutine(routine)
    }

    // ── steps (the products) ────────────────────────────────────────────────
    fun addStep(routineId: Long, name: String) = viewModelScope.launch {
        val clean = name.trim().take(60)
        if (clean.isEmpty()) return@launch
        dao.upsertStep(Step(routineId = routineId, name = clean, position = dao.nextStepPosition(routineId)))
    }

    fun deleteStep(step: Step) = viewModelScope.launch { dao.deleteStep(step) }

    fun moveStep(steps: List<Step>, from: Int, to: Int) = viewModelScope.launch {
        if (from !in steps.indices || to !in steps.indices) return@launch
        val reordered = steps.toMutableList().apply { add(to, removeAt(from)) }
        dao.updateSteps(reordered.mapIndexed { i, s -> s.copy(position = i) })
    }

    fun rescheduleAll() = viewModelScope.launch {
        AlarmScheduler.rescheduleAll(getApplication())
    }
}
