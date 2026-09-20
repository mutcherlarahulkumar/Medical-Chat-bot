package com.skintracker.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.skintracker.data.Routine
import com.skintracker.data.RoutineWithSteps
import com.skintracker.schedule.Repeat
import com.skintracker.schedule.nextOccurrence
import java.time.LocalTime
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import java.time.temporal.ChronoUnit

private val timeFormat: DateTimeFormatter = DateTimeFormatter.ofPattern("h:mm a")

@Composable
fun RoutinesScreen(
    routines: List<RoutineWithSteps>,
    onEdit: (Long) -> Unit,
    onToggleEnabled: (Routine, Boolean) -> Unit,
    modifier: Modifier = Modifier,
) {
    if (routines.isEmpty()) {
        EmptyState(
            title = "No routines yet",
            body = "Tap + to create one. A routine is a time, the days it repeats, " +
                "and the products you apply.",
            modifier = modifier,
        )
        return
    }

    LazyColumn(
        modifier = modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        items(routines, key = { it.routine.id }) { rws ->
            val r = rws.routine
            Card(Modifier.fillMaxWidth()) {
                Row(
                    Modifier.padding(16.dp).fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(Modifier.weight(1f)) {
                        Text(
                            LocalTime.of(r.hour, r.minute).format(timeFormat),
                            style = MaterialTheme.typography.headlineSmall,
                            fontWeight = FontWeight.Bold,
                            color = if (r.enabled) MaterialTheme.colorScheme.primary
                                    else MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Text(r.name, style = MaterialTheme.typography.titleSmall)
                        Text(
                            Repeat.describe(r.repeatMask) + " · " +
                                "${rws.steps.size} product" + if (rws.steps.size == 1) "" else "s",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        if (r.enabled) {
                            Text(
                                nextFiringText(r),
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                    Switch(checked = r.enabled, onCheckedChange = { onToggleEnabled(r, it) })
                    IconButton(onClick = { onEdit(r.id) }) {
                        Icon(Icons.Default.Edit, contentDescription = "Edit ${r.name}")
                    }
                }
            }
        }
        item { Spacer(Modifier.height(80.dp)) }
    }
}

/** "Next: in 3 h 20 m" — reassurance that the alarm is actually booked. */
private fun nextFiringText(r: Routine): String {
    val now = ZonedDateTime.now()
    val next = nextOccurrence(r.hour, r.minute, r.repeatMask, now) ?: return "Never — no days picked"
    val minutes = ChronoUnit.MINUTES.between(now, next)
    val h = minutes / 60
    val m = minutes % 60
    return when {
        h >= 24 -> "Next: in ${h / 24} day" + if (h / 24 == 1L) "" else "s"
        h > 0 -> "Next: in ${h} h ${m} m"
        else -> "Next: in ${m} m"
    }
}
